import hashlib
import random
from datetime import timedelta

from django.utils import timezone

from documents.models import Document
from signing.models import Signer, SigningSession, Signature
from signing.services.sms_gateway_service import SmsGatewayService

class SmsSigningService:
    OTP_TTL_MINUTES = 10

    @classmethod
    def generate_otp(cls) -> str:
        return str(random.randint(100000, 999999))

    @classmethod
    def hash_otp(cls, otp: str) -> str:
        return hashlib.sha256(otp.encode("utf-8")).hexdigest()

    @classmethod
    def create_session(cls, *, signer: Signer) -> SigningSession:
        if signer.status == Signer.Status.SIGNED:
            raise ValueError("This document has already been signed.")

        otp = cls.generate_otp()
        otp_hash = cls.hash_otp(otp)

        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.SMS,
            status=SigningSession.Status.WAITING,
            expires_at=timezone.now() + timedelta(minutes=cls.OTP_TTL_MINUTES),
            raw_request={
                "phone": signer.phone,
                "otp_hash": otp_hash,
                "otp_ttl_minutes": cls.OTP_TTL_MINUTES,
            },
            raw_response={
                "message": "SMS OTP generated.",
            },
        )

        sms_text = (
            f"TrustMe: Код подтверждения подписи документа "
            f"'{signer.document.title}': {otp}. "
            f"Никому не сообщайте этот код."
        )

        sms_result = SmsGatewayService.send_sms(
            phone=signer.phone,
            text=sms_text,
        )

        session.raw_response = {
            **(session.raw_response or {}),
            "sms_result": sms_result,
        }
        session.save(update_fields=["raw_response", "updated_at"])

        signer.status = Signer.Status.SIGNING_STARTED
        signer.save(update_fields=["status", "updated_at"])

        return session

    @classmethod
    def verify_otp(cls, *, session: SigningSession, otp: str) -> bool:
        if session.status == SigningSession.Status.SIGNED:
            raise ValueError("This signing session is already completed.")

        if session.expires_at and session.expires_at <= timezone.now():
            session.status = SigningSession.Status.EXPIRED
            session.save(update_fields=["status", "updated_at"])
            raise ValueError("SMS code expired.")

        expected_hash = session.raw_request.get("otp_hash")

        if not expected_hash:
            raise ValueError("SMS code was not generated for this session.")

        return cls.hash_otp(otp) == expected_hash

    @classmethod
    def complete_session(cls, *, session: SigningSession, otp: str, ip_address: str = "", user_agent: str = "",) -> Signature:
        signer = session.signer
        document = signer.document

        if not cls.verify_otp(session=session, otp=otp):
            raise ValueError("Invalid SMS code.")

        signed_content = (
            f"SMS_CONFIRMATION:"
            f"document_id={document.id};"
            f"signer_id={signer.id};"
            f"iin={signer.iin};"
            f"phone={signer.phone};"
            f"signed_at={timezone.now().isoformat()}"
        )

        signed_content_hash = hashlib.sha256(
            signed_content.encode("utf-8")
        ).hexdigest()

        signature = Signature.objects.create(
            signer=signer,
            document=document,
            signing_session=session,
            provider=SigningSession.Provider.SMS,
            certificate_iin=signer.iin,
            certificate_subject=signer.full_name,
            certificate_serial="SMS_CONFIRMATION",
            signature_value=signed_content,
            signed_content_hash=signed_content_hash,
            signed_at=timezone.now(),
            is_valid=True,
            raw_payload={
                "type": "SMS_CONFIRMATION",
                "phone": signer.phone,
                "iin": signer.iin,
                "document_id": document.id,
                "signer_id": signer.id,
                "ip_address": ip_address,
                "user_agent": user_agent,
            },
        )

        session.status = SigningSession.Status.SIGNED
        session.raw_response = {
            **(session.raw_response or {}),
            "message": "SMS signing completed.",
            "signed_at": timezone.now().isoformat(),
        }
        session.save(update_fields=["status", "raw_response", "updated_at"])

        signer.status = Signer.Status.SIGNED
        signer.signed_at = timezone.now()
        signer.save(update_fields=["status", "signed_at", "updated_at"])

        total_signers = document.signers.count()
        signed_signers = document.signers.filter(status=Signer.Status.SIGNED).count()

        if total_signers > 0 and total_signers == signed_signers:
            document.status = Document.Status.SIGNED
            document.signed_at = timezone.now()
            document.save(update_fields=["status", "signed_at", "updated_at"])
        else:
            document.status = Document.Status.PARTIALLY_SIGNED
            document.save(update_fields=["status", "updated_at"])

        return signature