import re

from django.db import transaction
from django.utils import timezone

import base64
import binascii

from documents.models import StoredObject
from documents.services.object_storage_service import ObjectStorageService
from signing.models import (
    Signer,
    SigningSession,
    Signature,
    SigningAuditLog,
)
from signing.services.audit_log_service import SigningAuditLogService
from signing.services.ecp_validation_client import EcpValidationClient

class EcpSigningService:
    @staticmethod
    def extract_iin_from_subject(subject: str) -> str:
        if not subject:
            return ""

        match = re.search(r"\b\d{12}\b", subject)
        return match.group(0) if match else ""

    @staticmethod
    def cms_to_der_bytes(cms_signature: str) -> bytes:
        """
        Converts NCALayer CMS string to DER bytes for .cms file.

        NCALayer may return:
        1) PEM-like CMS:
        -----BEGIN CMS-----
        MIIF...
        -----END CMS-----

        2) plain base64 CMS:
        MIIF...

        For ezSigner, we should store raw DER bytes, not PEM text.
        """
        if not cms_signature:
            return b""

        cms_text = cms_signature.strip()

        cms_text = cms_text.replace("-----BEGIN CMS-----", "")
        cms_text = cms_text.replace("-----END CMS-----", "")
        cms_text = cms_text.replace("-----BEGIN PKCS7-----", "")
        cms_text = cms_text.replace("-----END PKCS7-----", "")

        cms_text = "".join(cms_text.split())

        try:
            return base64.b64decode(cms_text, validate=True)
        except (binascii.Error, ValueError):
            return cms_signature.encode("utf-8")

    @staticmethod
    def build_cms_filename(
        *,
        document_id: int,
        signer_id: int,
        signature_id: int,
    ) -> str:
        return f"document_{document_id}_signature_{signature_id}_signer_{signer_id}.cms"

    @classmethod
    @transaction.atomic
    def complete_signing(
        cls,
        *,
        signer: Signer,
        cms_signature: str,
        signed_payload: dict,
        certificate_subject: str = "",
        certificate_serial_number: str = "",
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> Signature:
        if signer.status == Signer.Status.SIGNED:
            raise ValueError("Signer already signed this document.")

        if signer.signing_method != Signer.SigningMethod.ECP:
            raise ValueError("Signer is not configured for ECP signing.")

        document = signer.document

        if not document.content_hash:
            raise ValueError("Document hash is missing.")

        certificate_iin = cls.extract_iin_from_subject(certificate_subject)

        if signer.iin and certificate_iin and signer.iin != certificate_iin:
            raise ValueError("Certificate IIN does not match signer IIN.")

        validation_result = EcpValidationClient.verify(
            cms_signature=cms_signature,
            expected_document_hash=document.content_hash,
            expected_iin=signer.iin,
        )

        is_valid = bool(validation_result.get("ok"))

        certificate_iin = validation_result.get("certificate_iin", "")
        certificate_subject = validation_result.get("certificate_subject", certificate_subject)
        certificate_serial_number = validation_result.get(
            "certificate_serial",
            certificate_serial_number,
        )

        validation_error = validation_result.get("error", "")

        if not is_valid and not validation_error:
            failed_checks = []

            if not validation_result.get("cms_valid"):
                failed_checks.append("CMS signature is invalid")

            if not validation_result.get("document_hash_matches"):
                failed_checks.append("Document hash does not match signed payload")

            if not validation_result.get("iin_matches"):
                failed_checks.append("Certificate IIN does not match signer IIN")

            if not validation_result.get("certificate_date_valid"):
                failed_checks.append("Certificate is expired or not yet valid")

            if validation_result.get("chain_valid") is False:
                failed_checks.append("Certificate chain is not trusted")

            if validation_result.get("certificate_type_valid") is False:
                failed_checks.append("Certificate type is not allowed for signing")

            if validation_result.get("ocsp_good") is False:
                ocsp_status = validation_result.get("ocsp_status", "unknown")
                failed_checks.append(f"OCSP revocation check failed: {ocsp_status}")

            validation_error = "; ".join(failed_checks) or "ECP signature validation failed."

        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.ECP,
            status=SigningSession.Status.SIGNED,
            document_hash=document.content_hash,
            used_at=timezone.now(),
            raw_request=signed_payload,
            raw_response={
                "cms_signature_received": True,
                "certificate_subject": certificate_subject,
                "certificate_serial_number": certificate_serial_number,
            },
        )

        signature = Signature.objects.create(
            signer=signer,
            document=document,
            signing_session=session,
            provider=SigningSession.Provider.ECP,
            certificate_iin=certificate_iin,
            certificate_subject=certificate_subject,
            certificate_serial=certificate_serial_number,
            signature_value=cms_signature,
            signed_content_hash=document.content_hash,
            signed_at=timezone.now(),
            is_valid=is_valid,
            validation_error=validation_error,
            ip_address=ip_address,
            user_agent=user_agent,
            raw_payload={
                "request": signed_payload,
                "validation_result": validation_result,
            },
            confirmation_text=(
                f"Document '{document.title}' was signed using ECP via NCALayer. "
                f"Signer: {signer.full_name}, IIN: {signer.iin}. "
                f"Document hash: {document.content_hash}. "
                f"Backend validation result: {'valid' if is_valid else 'invalid'}."
            ),
        )

        cms_file_bytes = cls.cms_to_der_bytes(cms_signature)

        stored_cms_object = ObjectStorageService.store_bytes(
            document=document,
            data=cms_file_bytes,
            filename=cls.build_cms_filename(
                document_id=document.id,
                signer_id=signer.id,
                signature_id=signature.id,
            ),
            content_type="application/pkcs7-mime",
            object_type=StoredObject.ObjectType.SIGNATURE,
        )

        if is_valid:
            signer.mark_signed()
            session.mark_signed()
        else:
            signer.status = Signer.Status.FAILED
            signer.save(update_fields=["status", "updated_at"])
            session.mark_failed()

        SigningAuditLog.objects.create(
            document=document,
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.ECP_SIGNATURE_RECEIVED,
            signing_method=Signer.SigningMethod.ECP,
            phone=signer.phone,
            iin=signer.iin,
            full_name=signer.full_name,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            signed_content_hash=document.content_hash,
            metadata={
                "signature_id": signature.id,
                "certificate_iin": certificate_iin,
                "certificate_subject": certificate_subject,
                "certificate_serial_number": certificate_serial_number,
                "backend_validation": "not_implemented",
                "validation_result": validation_result,
                "stored_cms_object": cls.serialize_stored_cms_object(stored_cms_object),
            },
        )

        SigningAuditLog.objects.create(
            document=document,
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.SIGNATURE_CREATED,
            signing_method=Signer.SigningMethod.ECP,
            phone=signer.phone,
            iin=signer.iin,
            full_name=signer.full_name,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            signed_content_hash=document.content_hash,
            metadata={
                "signature_id": signature.id,
                "provider": SigningSession.Provider.ECP,
                "is_valid": is_valid,
                "validation_error": validation_error,
                "stored_cms_object": cls.serialize_stored_cms_object(stored_cms_object),
            },
        )

        return signature

    @staticmethod
    def serialize_stored_cms_object(stored_object):
        if not stored_object:
            return None

        return {
            "id": stored_object.id,
            "bucket": stored_object.bucket,
            "object_key": stored_object.object_key,
            "version_id": stored_object.version_id,
            "sha256": stored_object.sha256,
            "retention_until": (
                stored_object.retention_until.isoformat()
                if stored_object.retention_until
                else None
            ),
        }
