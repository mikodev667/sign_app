import re

from django.db import transaction
from django.utils import timezone

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
            },
        )

        return signature