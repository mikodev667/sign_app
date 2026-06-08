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
            is_valid=False,
            validation_error="CMS signature saved. Backend validation via KalkanCrypt is not implemented yet.",
            ip_address=ip_address,
            user_agent=user_agent,
            raw_payload=signed_payload,
            confirmation_text=(
                f"Document '{document.title}' was signed using ECP via NCALayer. "
                f"Signer: {signer.full_name}, IIN: {signer.iin}. "
                f"Document hash: {document.content_hash}."
            ),
        )

        signer.mark_signed()

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
            },
        )

        return signature