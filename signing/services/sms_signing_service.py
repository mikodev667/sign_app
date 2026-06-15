import random
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from documents.models import Document
from signing.models import Signer, SigningSession, Signature, SigningAuditLog
from signing.services.sms_gateway_service import SmsGatewayService


class SmsSigningService:
    OTP_TTL_MINUTES = 10
    COOLDOWN_SECONDS = 60
    MAX_ATTEMPTS = 5

    CONSENT_TEXT = (
        "I confirm that I have reviewed the document, agree with its content, "
        "and confirm signing this document using an SMS verification code."
    )

    @classmethod
    def generate_otp(cls) -> str:
        return str(random.randint(100000, 999999))

    @classmethod
    def create_session(
        cls,
        *,
        signer: Signer,
        consent_accepted: bool = False,
        ip_address: str = "",
        user_agent: str = "",
    ) -> SigningSession:
        if signer.status == Signer.Status.SIGNED:
            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "reason": "signer_already_signed",
                },
            )
            raise ValueError("This document has already been signed.")

        if hasattr(signer, "signature"):
            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "reason": "signature_already_exists",
                },
            )
            raise ValueError("Signature already exists for this signer.")

        if signer.signing_method != Signer.SigningMethod.SMS:
            raise ValueError("This signer is not configured for SMS signing.")

        if not signer.can_sign():
            raise ValueError("This signer cannot sign the document.")

        if not consent_accepted:
            raise ValueError("Consent is required before SMS signing.")

        document = signer.document

        if not document.content_hash:
            document.update_content_hash(save=True)

        document.lock_for_signing(save=True)

        active_session = (
            SigningSession.objects
            .filter(
                signer=signer,
                provider=SigningSession.Provider.SMS,
            )
            .exclude(
                status__in=[
                    SigningSession.Status.SIGNED,
                    SigningSession.Status.USED,
                    SigningSession.Status.EXPIRED,
                    SigningSession.Status.CANCELED,
                    SigningSession.Status.FAILED,
                ]
            )
            .order_by("-created_at")
            .first()
        )

        if active_session and active_session.is_in_cooldown():
            seconds_left = int(
                (active_session.cooldown_until - timezone.now()).total_seconds()
            )

            cls.create_audit_log(
                signer=signer,
                signing_session=active_session,
                event=SigningAuditLog.Event.SMS_CODE_COOLDOWN,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "seconds_left": seconds_left,
                },
            )

            raise ValueError(f"Please wait {seconds_left} seconds before requesting another SMS code.")

        cls.create_audit_log(
            signer=signer,
            event=SigningAuditLog.Event.SMS_CONSENT_ACCEPTED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            metadata={
                "consent_text": cls.CONSENT_TEXT,
            },
        )

        otp = cls.generate_otp()

        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.SMS,
            status=SigningSession.Status.CREATED,
            document_hash=document.content_hash,
            expires_at=timezone.now() + timedelta(minutes=cls.OTP_TTL_MINUTES),
            max_attempts=cls.MAX_ATTEMPTS,
            cooldown_until=timezone.now() + timedelta(seconds=cls.COOLDOWN_SECONDS),
            raw_request={
                "phone": signer.phone,
                "otp_ttl_minutes": cls.OTP_TTL_MINUTES,
                "max_attempts": cls.MAX_ATTEMPTS,
                "cooldown_seconds": cls.COOLDOWN_SECONDS,
                "consent_text": cls.CONSENT_TEXT,
            },
            raw_response={
                "message": "SMS OTP generated.",
            },
        )

        session.set_sms_code(otp, save=True)

        cls.create_audit_log(
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.SMS_CODE_REQUESTED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            metadata={
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            },
        )

        sms_text = (
            f"TrustMe: Код подтверждения подписи документа "
            f"'{signer.document.title}': {otp}. "
            f"Никому не сообщайте этот код."
        )

        try:
            sms_result = SmsGatewayService.send_sms(
                phone=signer.phone,
                text=sms_text,
            )

            session.status = SigningSession.Status.CODE_SENT
            session.raw_response = {
                **(session.raw_response or {}),
                "sms_result": sms_result,
                "message": "SMS code sent.",
            }
            if getattr(settings, "SMS_BACKEND", "console") == "console":
                session.raw_response["dev_otp"] = otp
            session.save(update_fields=["status", "raw_response", "updated_at"])

            signer.status = Signer.Status.SMS_SENT
            signer.save(update_fields=["status", "updated_at"])

            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SMS_CODE_SENT,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=document.content_hash,
                metadata={
                    "sms_result": sms_result,
                    "phone": signer.phone,
                },
            )

        except Exception as exc:
            session.status = SigningSession.Status.FAILED
            session.raw_response = {
                **(session.raw_response or {}),
                "error": str(exc),
            }
            session.save(update_fields=["status", "raw_response", "updated_at"])

            signer.status = Signer.Status.FAILED
            signer.save(update_fields=["status", "updated_at"])

            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SMS_CODE_FAILED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=document.content_hash,
                metadata={
                    "error": str(exc),
                },
            )

            raise

        return session

    @classmethod
    def verify_otp(
        cls,
        *,
        session: SigningSession,
        otp: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> bool:
        signer = session.signer

        if session.status in [
            SigningSession.Status.SIGNED,
            SigningSession.Status.USED,
        ]:
            raise ValueError("This signing session is already completed.")

        if session.is_expired():
            session.mark_expired(save=True)

            signer.status = Signer.Status.EXPIRED
            signer.save(update_fields=["status", "updated_at"])

            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SMS_CODE_EXPIRED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=session.document_hash,
            )

            raise ValueError("SMS code expired.")

        if session.attempts_exceeded():
            session.mark_failed(save=True)

            signer.status = Signer.Status.FAILED
            signer.save(update_fields=["status", "updated_at"])

            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SMS_CODE_ATTEMPTS_EXCEEDED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=session.document_hash,
                metadata={
                    "attempts_count": session.attempts_count,
                    "max_attempts": session.max_attempts,
                },
            )

            raise ValueError("Too many incorrect attempts.")

        if not session.code_hash:
            raise ValueError("SMS code was not generated for this session.")

        is_valid = session.verify_sms_code(otp)

        if not is_valid:
            session.attempts_count += 1
            session.cooldown_until = timezone.now() + timedelta(seconds=cls.COOLDOWN_SECONDS)
            session.save(update_fields=["attempts_count", "cooldown_until", "updated_at"])

            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SMS_CODE_INVALID,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=session.document_hash,
                metadata={
                    "attempts_count": session.attempts_count,
                    "max_attempts": session.max_attempts,
                },
            )

            raise ValueError("Invalid SMS code.")

        cls.create_audit_log(
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.SMS_CODE_CONFIRMED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=session.document_hash,
        )

        return True

    @classmethod
    @transaction.atomic
    def complete_session(
        cls,
        *,
        session: SigningSession,
        otp: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Signature:
        session = (
            SigningSession.objects
            .select_for_update()
            .select_related("signer", "signer__document")
            .get(id=session.id)
        )

        signer = session.signer
        document = signer.document

        if signer.status == Signer.Status.SIGNED:
            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=document.content_hash,
                metadata={
                    "reason": "signer_already_signed",
                },
            )
            raise ValueError("This document has already been signed.")

        if hasattr(signer, "signature"):
            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=document.content_hash,
                metadata={
                    "reason": "signature_already_exists",
                },
            )
            raise ValueError("Signature already exists for this signer.")

        cls.verify_otp(
            session=session,
            otp=otp,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        current_document_hash = document.calculate_content_hash()

        if not document.content_hash:
            document.content_hash = current_document_hash
            document.save(update_fields=["content_hash", "updated_at"])

        if current_document_hash != document.content_hash:
            cls.create_audit_log(
                signer=signer,
                signing_session=session,
                event=SigningAuditLog.Event.SIGNING_FAILED,
                ip_address=ip_address,
                user_agent=user_agent,
                document_hash=document.content_hash,
                signed_content_hash=current_document_hash,
                metadata={
                    "reason": "document_hash_mismatch",
                },
            )
            raise ValueError("Document content was changed after invitation. Signing blocked.")

        signed_at = timezone.now()

        signed_content = cls.build_signed_content(
            signer=signer,
            document=document,
            session=session,
            signed_at=signed_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        signed_content_hash = document.content_hash

        confirmation_text = cls.build_confirmation_text(
            signer=signer,
            document=document,
            session=session,
            signed_at=signed_at,
            document_hash=document.content_hash,
        )

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
            consent_text=cls.CONSENT_TEXT,
            confirmation_text=confirmation_text,
            signed_at=signed_at,
            is_valid=True,
            ip_address=ip_address or None,
            user_agent=user_agent,
            raw_payload={
                "type": "SMS_CONFIRMATION",
                "phone": signer.phone,
                "iin": signer.iin,
                "document_id": document.id,
                "signer_id": signer.id,
                "signing_session_id": session.id,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "document_hash": document.content_hash,
                "signed_at": signed_at.isoformat(),
                "consent_text": cls.CONSENT_TEXT,
            },
        )

        session.status = SigningSession.Status.SIGNED
        session.used_at = signed_at
        session.raw_response = {
            **(session.raw_response or {}),
            "message": "SMS signing completed.",
            "signed_at": signed_at.isoformat(),
            "signature_id": signature.id,
        }
        session.save(update_fields=["status", "used_at", "raw_response", "updated_at"])

        signer.status = Signer.Status.SIGNED
        signer.signed_at = signed_at
        signer.save(update_fields=["status", "signed_at", "updated_at"])

        cls.recalculate_document_status(document=document)

        cls.create_audit_log(
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.SIGNATURE_CREATED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            signed_content_hash=signed_content_hash,
            metadata={
                "signature_id": signature.id,
            },
        )

        cls.create_audit_log(
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.DOCUMENT_SIGNED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            signed_content_hash=signed_content_hash,
            metadata={
                "signature_id": signature.id,
                "document_status": document.status,
                "signer_status": signer.status,
            },
        )

        cls.create_audit_log(
            signer=signer,
            signing_session=session,
            event=SigningAuditLog.Event.STATUS_RECALCULATED,
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document.content_hash,
            metadata={
                "document_status": document.status,
                "signer_status": signer.status,
            },
        )

        return signature

    @classmethod
    def recalculate_document_status(cls, *, document: Document) -> Document:
        total_signers = document.signers.count()
        signed_signers = document.signers.filter(status=Signer.Status.SIGNED).count()

        if total_signers > 0 and total_signers == signed_signers:
            document.status = Document.Status.SIGNED
            document.signed_at = timezone.now()
            document.save(update_fields=["status", "signed_at", "updated_at"])
        elif signed_signers > 0:
            document.status = Document.Status.PARTIALLY_SIGNED
            document.save(update_fields=["status", "updated_at"])
        else:
            document.status = Document.Status.WAITING_FOR_SIGNERS
            document.save(update_fields=["status", "updated_at"])

        return document

    @classmethod
    def build_signed_content(
        cls,
        *,
        signer: Signer,
        document: Document,
        session: SigningSession,
        signed_at,
        ip_address: str = "",
        user_agent: str = "",
    ) -> str:
        return (
            f"SMS_CONFIRMATION:"
            f"document_id={document.id};"
            f"document_title={document.title};"
            f"document_hash={document.content_hash};"
            f"signer_id={signer.id};"
            f"full_name={signer.full_name};"
            f"iin={signer.iin};"
            f"phone={signer.phone};"
            f"signing_session_id={session.id};"
            f"signed_at={signed_at.isoformat()};"
            f"ip_address={ip_address};"
            f"user_agent={user_agent}"
        )

    @classmethod
    def build_confirmation_text(
        cls,
        *,
        signer: Signer,
        document: Document,
        session: SigningSession,
        signed_at,
        document_hash: str,
    ) -> str:
        return (
            "Signing confirmation sheet\n\n"
            f"Document: {document.title}\n"
            f"Document ID: {document.id}\n"
            f"Signer: {signer.full_name}\n"
            f"IIN: {signer.iin}\n"
            f"Phone: {signer.phone}\n"
            f"Signing method: SMS confirmation\n"
            f"Signing session ID: {session.id}\n"
            f"Signed at: {signed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Document SHA-256 hash: {document_hash}\n\n"
            f"Consent text:\n{cls.CONSENT_TEXT}\n"
        )

    @classmethod
    def create_audit_log(
        cls,
        *,
        signer: Signer,
        event,
        signing_session: SigningSession = None,
        ip_address: str = "",
        user_agent: str = "",
        document_hash: str = "",
        signed_content_hash: str = "",
        metadata: dict = None,
    ) -> SigningAuditLog:
        document = signer.document

        return SigningAuditLog.objects.create(
            document=document,
            signer=signer,
            signing_session=signing_session,
            event=event,
            signing_method=signer.signing_method,
            phone=signer.phone,
            iin=signer.iin,
            full_name=signer.full_name,
            ip_address=ip_address or None,
            user_agent=user_agent,
            document_hash=document_hash or document.content_hash or "",
            signed_content_hash=signed_content_hash,
            metadata=metadata or {},
        )
