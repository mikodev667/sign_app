import hashlib
import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from documents.models import Document, DocumentLedgerRecord, StoredObject
from documents.services.ledger_client import LedgerClient, LedgerError
from documents.services.object_storage_service import ObjectStorageService
from documents.services.pdf_export_service import OnlyOfficePdfExportService, PdfExportError


class DocumentLedgerError(Exception):
    def __init__(self, message, *, error_code=""):
        super().__init__(message)
        self.error_code = error_code


class DocumentLedgerService:
    @classmethod
    def submit_document(cls, *, document: Document, requested_by=None, force=False):
        if document.status != Document.Status.SIGNED:
            raise DocumentLedgerError(
                "Only fully signed documents can be submitted to ledger.",
                error_code="document_not_signed",
            )

        try:
            LedgerClient.ensure_enabled()
        except LedgerError as exc:
            raise DocumentLedgerError(str(exc), error_code=exc.error_code or "ledger_disabled") from exc

        external_id = cls.external_id(document)
        metadata = cls.build_metadata(document)

        record, created = DocumentLedgerRecord.objects.get_or_create(
            external_id=external_id,
            defaults={
                "document": document,
                "requested_by": requested_by if getattr(requested_by, "is_authenticated", False) else None,
                "actor": settings.LEDGER_ACTOR,
                "request_metadata": metadata,
            },
        )

        if record.status == DocumentLedgerRecord.Status.SUBMITTED and not force:
            return record, True

        if not created:
            record.document = document
            record.requested_by = requested_by if getattr(requested_by, "is_authenticated", False) else None
            record.actor = settings.LEDGER_ACTOR
            record.request_metadata = metadata
            record.status = DocumentLedgerRecord.Status.PENDING
            record.error_code = ""
            record.error_message = ""
            record.last_verified_at = None
            record.last_verification_status = ""
            record.last_verification_result = {}
            record.last_verification_error = ""
            record.save(update_fields=[
                "document",
                "requested_by",
                "actor",
                "request_metadata",
                "status",
                "error_code",
                "error_message",
                "last_verified_at",
                "last_verification_status",
                "last_verification_result",
                "last_verification_error",
                "updated_at",
            ])

        try:
            pdf = OnlyOfficePdfExportService.export_document_pdf(document)
        except PdfExportError as exc:
            cls.mark_failed(record, exc, "pdf_export_failed")
            raise DocumentLedgerError(str(exc), error_code="pdf_export_failed") from exc

        try:
            ledger_pdf_object = cls.store_ledger_pdf(
                document=document,
                pdf=pdf,
                created_by=requested_by,
            )
            record.ledger_pdf_object = ledger_pdf_object
            record.source_filename = pdf.filename
            record.save(update_fields=[
                "ledger_pdf_object",
                "source_filename",
                "updated_at",
            ])
        except Exception as exc:
            cls.mark_failed(record, exc, "ledger_pdf_storage_failed")
            raise DocumentLedgerError(
                f"Could not store ledger PDF before submission: {exc}",
                error_code="ledger_pdf_storage_failed",
            ) from exc

        try:
            payload = LedgerClient.submit_document(
                filename=pdf.filename,
                content=pdf.content,
                content_type=pdf.content_type,
                actor=settings.LEDGER_ACTOR,
                external_id=external_id,
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )
        except LedgerError as exc:
            cls.mark_failed(record, exc, exc.error_code or "ledger_error")
            raise DocumentLedgerError(str(exc), error_code=exc.error_code or "ledger_error") from exc

        cls.apply_success_payload(
            record=record,
            payload=payload,
            source_filename=pdf.filename,
            fallback_size=len(pdf.content),
            ledger_pdf_object=ledger_pdf_object,
        )
        return record, False

    @classmethod
    def submit_document_safely(cls, *, document: Document, requested_by=None):
        if not getattr(settings, "LEDGER_ENABLED", False):
            return None

        if document.status != Document.Status.SIGNED:
            return None

        try:
            record, _ = cls.submit_document(
                document=document,
                requested_by=requested_by,
            )
            return record
        except DocumentLedgerError:
            return document.ledger_records.order_by("-updated_at").first()

    @classmethod
    def submit_document_after_commit(cls, *, document_id: int, requested_by=None):
        if not getattr(settings, "LEDGER_ENABLED", False):
            return

        def submit():
            document = Document.objects.filter(pk=document_id).first()
            if not document:
                return None

            return cls.submit_document_safely(
                document=document,
                requested_by=requested_by,
            )

        transaction.on_commit(submit)

    @staticmethod
    def external_id(document: Document) -> str:
        source_date = document.signed_at or document.created_at or timezone.now()
        return f"{settings.LEDGER_EXTERNAL_ID_PREFIX}-{source_date.year}-{document.pk:06d}"

    @staticmethod
    def build_metadata(document: Document) -> dict:
        return {
            "document_type": "contract",
            "source": "sign_app",
            "status": document.status,
            "document_id": document.pk,
            "title": document.title,
            "content_hash": document.content_hash,
            "signed_at": document.signed_at.isoformat() if document.signed_at else None,
            "signers_count": document.signers.count() if document.pk else 0,
        }

    @staticmethod
    def store_ledger_pdf(*, document: Document, pdf, created_by=None):
        return ObjectStorageService.store_bytes(
            document=document,
            data=pdf.content,
            filename=pdf.filename,
            content_type=pdf.content_type,
            object_type=StoredObject.ObjectType.LEDGER_PDF,
            created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
        )

    @staticmethod
    def mark_failed(record, exc, error_code):
        record.status = DocumentLedgerRecord.Status.FAILED
        record.error_code = error_code
        record.error_message = str(exc)
        record.save(update_fields=[
            "status",
            "error_code",
            "error_message",
            "updated_at",
        ])

    @staticmethod
    def apply_success_payload(*, record, payload, source_filename, fallback_size, ledger_pdf_object=None):
        proof = payload.get("ledger_proof") or {}

        ledger_created_at = payload.get("created_at") or proof.get("created_at")
        parsed_ledger_created_at = parse_datetime(ledger_created_at) if ledger_created_at else None

        record.status = DocumentLedgerRecord.Status.SUBMITTED
        record.ledger_id = payload.get("id", "") or ""
        record.document_token = payload.get("document_token", "") or ""
        record.document_hash = payload.get("document_hash", "") or ""
        record.size_bytes = payload.get("size_bytes") or fallback_size
        record.source_filename = source_filename
        record.ledger_pdf_object = ledger_pdf_object
        record.sequence = proof.get("sequence")
        record.entry_hash = proof.get("entry_hash", "") or ""
        record.previous_hash = proof.get("previous_hash", "") or ""
        record.server_signature_b64 = proof.get("server_signature_b64", "") or ""
        record.server_key_id = proof.get("server_key_id", "") or ""
        record.ledger_created_at = parsed_ledger_created_at
        record.raw_response = payload
        record.error_code = ""
        record.error_message = ""
        record.last_verified_at = None
        record.last_verification_status = ""
        record.last_verification_result = {}
        record.last_verification_error = ""
        record.submitted_at = timezone.now()
        record.save(update_fields=[
            "status",
            "ledger_id",
            "document_token",
            "document_hash",
            "size_bytes",
            "source_filename",
            "ledger_pdf_object",
            "sequence",
            "entry_hash",
            "previous_hash",
            "server_signature_b64",
            "server_key_id",
            "ledger_created_at",
            "raw_response",
            "error_code",
            "error_message",
            "last_verified_at",
            "last_verification_status",
            "last_verification_result",
            "last_verification_error",
            "submitted_at",
            "updated_at",
        ])

    @classmethod
    def verify_record(cls, record: DocumentLedgerRecord) -> dict:
        if record.status != DocumentLedgerRecord.Status.SUBMITTED:
            raise DocumentLedgerError(
                "Only submitted ledger records can be verified.",
                error_code="ledger_record_not_submitted",
            )

        checked_at = timezone.now()
        result = {
            "checked_at": checked_at.isoformat(),
            "document_id": record.document_id,
            "external_id": record.external_id,
            "ledger_id": record.ledger_id,
            "document_token": record.document_token,
            "ledger_hash": record.document_hash,
            "stored_object_id": record.ledger_pdf_object_id,
            "hash_matches": False,
            "ledger_chain_ok": False,
        }

        try:
            if not record.ledger_pdf_object_id:
                raise DocumentLedgerError(
                    "Ledger PDF object is not stored for this record.",
                    error_code="missing_ledger_pdf",
                )

            pdf_content = ObjectStorageService.get_stored_object_bytes(record.ledger_pdf_object)
            local_hash = hashlib.sha256(pdf_content).hexdigest()
            result.update({
                "local_hash": local_hash,
                "stored_object_hash": record.ledger_pdf_object.sha256,
                "stored_object_size": record.ledger_pdf_object.size_bytes,
                "hash_matches": bool(record.document_hash) and local_hash == record.document_hash,
            })

            ledger_verify_response = LedgerClient.verify(deep=True)
            result["ledger_chain_ok"] = True
            result["ledger_verify_response"] = ledger_verify_response

        except DocumentLedgerError as exc:
            cls.apply_verification_result(
                record=record,
                status=DocumentLedgerRecord.VerificationStatus.ERROR,
                result=result,
                error=str(exc),
            )
            raise
        except LedgerError as exc:
            result["ledger_error_code"] = exc.error_code
            result["ledger_status_code"] = exc.status_code
            cls.apply_verification_result(
                record=record,
                status=DocumentLedgerRecord.VerificationStatus.ERROR,
                result=result,
                error=str(exc),
            )
            raise DocumentLedgerError(str(exc), error_code=exc.error_code or "ledger_verify_failed") from exc
        except Exception as exc:
            cls.apply_verification_result(
                record=record,
                status=DocumentLedgerRecord.VerificationStatus.ERROR,
                result=result,
                error=str(exc),
            )
            raise DocumentLedgerError(str(exc), error_code="ledger_verify_failed") from exc

        if result["hash_matches"] and result["ledger_chain_ok"]:
            status = DocumentLedgerRecord.VerificationStatus.PASSED
            error = ""
        else:
            status = DocumentLedgerRecord.VerificationStatus.FAILED
            error = "Stored ledger PDF hash does not match the hash returned by ledger."

        cls.apply_verification_result(
            record=record,
            status=status,
            result=result,
            error=error,
        )
        return result

    @staticmethod
    def apply_verification_result(*, record, status, result, error=""):
        record.last_verified_at = timezone.now()
        record.last_verification_status = status
        record.last_verification_result = result
        record.last_verification_error = error
        record.save(update_fields=[
            "last_verified_at",
            "last_verification_status",
            "last_verification_result",
            "last_verification_error",
            "updated_at",
        ])
