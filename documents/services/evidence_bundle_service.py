import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO

from django.utils import timezone
from django.utils.translation import gettext as _

from documents.models import StoredObject
from documents.services.object_storage_service import ObjectStorageService
from signing.models import SigningAuditLog
from signing.services.audit_chain_service import AuditChainService


class EvidenceBundleError(Exception):
    pass


@dataclass(frozen=True)
class EvidenceBundle:
    filename: str
    content: bytes
    sha256: str
    size_bytes: int
    stored_object: StoredObject | None = None


class EvidenceBundleService:
    @classmethod
    def build_bundle(cls, *, document, created_by=None, persist=True) -> EvidenceBundle:
        final_objects = list(
            document.stored_objects
            .filter(
                object_type__in=[
                    StoredObject.ObjectType.FINAL_PDF,
                    StoredObject.ObjectType.FINAL_DOCX,
                ],
                storage_status=StoredObject.StorageStatus.STORED,
            )
            .order_by("object_type", "-created_at")
        )

        if not final_objects:
            raise EvidenceBundleError(_("No final stored PDF/DOCX objects found for this document."))

        verified_files = cls._load_verified_files(final_objects)
        audit_result = AuditChainService.verify_document(document_id=document.id)

        stored_objects_payload = cls._serialize_stored_objects(
            document.stored_objects
            .exclude(object_type=StoredObject.ObjectType.EVIDENCE_BUNDLE)
            .order_by("object_type", "id")
        )
        signatures_payload = cls._serialize_signatures(document)
        audit_payload = cls._serialize_audit_trail(document)

        generated_at = timezone.now()
        integrity_report = {
            "ok": True,
            "generated_at": generated_at.isoformat(),
            "document_id": document.id,
            "document_content_hash": document.content_hash,
            "audit_chain": audit_result,
            "stored_object_verification": [
                {
                    "stored_object_id": item["stored_object"].id,
                    "object_type": item["stored_object"].object_type,
                    "object_key": item["stored_object"].object_key,
                    "version_id": item["stored_object"].version_id,
                    "sha256": item["stored_object"].sha256,
                    "verified": True,
                    "archive_path": item["archive_path"],
                }
                for item in verified_files
            ],
        }
        manifest = {
            "bundle_format": "sign_app_evidence_bundle_v1",
            "generated_at": generated_at.isoformat(),
            "document": cls._serialize_document(document),
            "integrity": {
                "ok": True,
                "audit_head_hash": audit_result["head_hash"],
                "stored_objects_verified": len(verified_files),
            },
        }

        content = cls._build_zip(
            manifest=manifest,
            stored_objects=stored_objects_payload,
            signatures=signatures_payload,
            audit_trail=audit_payload,
            integrity_report=integrity_report,
            verified_files=verified_files,
        )
        sha256 = hashlib.sha256(content).hexdigest()
        filename = cls._bundle_filename(document=document, sha256=sha256)

        stored_object = None
        if persist:
            stored_object = ObjectStorageService.store_bytes(
                document=document,
                data=content,
                filename=filename,
                content_type="application/zip",
                object_type=StoredObject.ObjectType.EVIDENCE_BUNDLE,
                created_by=created_by,
            )

        return EvidenceBundle(
            filename=filename,
            content=content,
            sha256=sha256,
            size_bytes=len(content),
            stored_object=stored_object,
        )

    @classmethod
    def _load_verified_files(cls, stored_objects):
        verified_files = []

        for stored_object in stored_objects:
            try:
                data = ObjectStorageService.get_stored_object_bytes(stored_object)
            except Exception as exc:
                raise EvidenceBundleError(
                    _("Stored object verification failed for #%(object_id)s: %(error)s") % {
                        "object_id": stored_object.id,
                        "error": exc,
                    }
                ) from exc

            archive_path = cls._archive_file_path(stored_object)
            verified_files.append({
                "stored_object": stored_object,
                "archive_path": archive_path,
                "data": data,
            })

        return verified_files

    @classmethod
    def _build_zip(
        cls,
        *,
        manifest,
        stored_objects,
        signatures,
        audit_trail,
        integrity_report,
        verified_files,
    ) -> bytes:
        buffer = BytesIO()

        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", cls._json_bytes(manifest))
            archive.writestr("stored_objects.json", cls._json_bytes(stored_objects))
            archive.writestr("signatures.json", cls._json_bytes(signatures))
            archive.writestr("audit_trail.json", cls._json_bytes(audit_trail))
            archive.writestr("integrity_report.json", cls._json_bytes(integrity_report))

            for item in verified_files:
                archive.writestr(item["archive_path"], item["data"])

        return buffer.getvalue()

    @staticmethod
    def _json_bytes(value) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ).encode("utf-8")

    @classmethod
    def _serialize_document(cls, document):
        return {
            "id": document.id,
            "title": document.title,
            "status": document.status,
            "organization_id": document.organization_id,
            "template_id": document.template_id,
            "created_by_id": document.created_by_id,
            "content_hash": document.content_hash,
            "locked_at": document.locked_at.isoformat() if document.locked_at else None,
            "signed_at": document.signed_at.isoformat() if document.signed_at else None,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }

    @classmethod
    def _serialize_stored_objects(cls, stored_objects):
        return [
            {
                "id": item.id,
                "document_id": item.document_id,
                "object_type": item.object_type,
                "bucket": item.bucket,
                "object_key": item.object_key,
                "version_id": item.version_id,
                "etag": item.etag,
                "sha256": item.sha256,
                "content_type": item.content_type,
                "size_bytes": item.size_bytes,
                "retention_mode": item.retention_mode,
                "retention_until": item.retention_until.isoformat() if item.retention_until else None,
                "storage_status": item.storage_status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "created_by_id": item.created_by_id,
            }
            for item in stored_objects
        ]

    @classmethod
    def _serialize_signatures(cls, document):
        return [
            {
                "id": signature.id,
                "signer_id": signature.signer_id,
                "signer_full_name": signature.signer.full_name,
                "signer_iin": signature.signer.iin,
                "signing_session_id": signature.signing_session_id,
                "provider": signature.provider,
                "certificate_iin": signature.certificate_iin,
                "certificate_subject": signature.certificate_subject,
                "certificate_serial": signature.certificate_serial,
                "signed_content_hash": signature.signed_content_hash,
                "signed_at": signature.signed_at.isoformat() if signature.signed_at else None,
                "is_valid": signature.is_valid,
                "validation_error": signature.validation_error,
                "ip_address": str(signature.ip_address or ""),
                "user_agent": signature.user_agent,
                "raw_payload": signature.raw_payload,
            }
            for signature in document.signatures.select_related("signer").order_by("id")
        ]

    @classmethod
    def _serialize_audit_trail(cls, document):
        return [
            {
                "id": log.id,
                "event": log.event,
                "signer_id": log.signer_id,
                "signing_session_id": log.signing_session_id,
                "signing_method": log.signing_method,
                "phone": log.phone,
                "iin": log.iin,
                "full_name": log.full_name,
                "ip_address": str(log.ip_address or ""),
                "user_agent": log.user_agent,
                "document_hash": log.document_hash,
                "signed_content_hash": log.signed_content_hash,
                "metadata": log.metadata,
                "payload_hash": log.payload_hash,
                "previous_hash": log.previous_hash,
                "entry_hash": log.entry_hash,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in SigningAuditLog.objects.filter(document=document).order_by("id")
        ]

    @classmethod
    def _archive_file_path(cls, stored_object):
        filename = stored_object.object_key.replace("\\", "/").split("/")[-1]
        return f"files/{stored_object.object_type}/{filename}"

    @classmethod
    def _bundle_filename(cls, *, document, sha256: str):
        title = re.sub(r"[^A-Za-z0-9._-]+", "_", document.title).strip("_") or "document"
        return f"evidence_document_{document.id}_{title}_{sha256[:12]}.zip"
