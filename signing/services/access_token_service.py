import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from documents.services.object_storage_service import ObjectStorageService
from signing.models import SignerAccessToken, SigningAuditLog


@dataclass
class CreatedAccessToken:
    raw_token: str
    access_token: SignerAccessToken


class SignerAccessTokenService:
    TOKEN_TTL_DAYS = 3

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def create_token(
        cls,
        *,
        signer,
        request=None,
    ) -> CreatedAccessToken:
        """
        Создаёт публичный access token для подписанта.

        ВАЖНО:
        Именно в этот момент документ блокируется.
        После создания ссылки документ нельзя редактировать.
        """

        document = signer.document

        if signer.status == signer.Status.SIGNED:
            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                request=request,
                metadata={
                    "reason": "signer_already_signed",
                },
            )
            raise ValueError("This signer has already signed the document.")

        if hasattr(signer, "signature"):
            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.REPEAT_SIGN_BLOCKED,
                request=request,
                metadata={
                    "reason": "signature_already_exists",
                },
            )
            raise ValueError("Signature already exists for this signer.")

        old_hash = document.content_hash

        if not document.content_hash:
            document.update_content_hash(save=True)

            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.DOCUMENT_HASH_FIXED,
                request=request,
                document_hash=document.content_hash,
                metadata={
                    "old_hash": old_hash,
                    "new_hash": document.content_hash,
                },
            )

        was_locked = document.locked_at is not None

        document.lock_for_signing(save=True)

        if not was_locked:
            cls.create_audit_log(
                signer=signer,
                event=SigningAuditLog.Event.DOCUMENT_LOCKED,
                request=request,
                document_hash=document.content_hash,
                metadata={
                    "locked_at": document.locked_at.isoformat() if document.locked_at else None,
                    "document_status": document.status,
                },
            )

        try:
            stored_objects = ObjectStorageService.ensure_final_document_objects(
                document=document,
                created_by=getattr(request, "user", None) if request else None,
            )
        except Exception as exc:
            raise ValueError(
                f"Final document could not be stored in immutable object storage: {exc}"
            ) from exc

        if ObjectStorageService.is_enabled() and not stored_objects:
            raise ValueError(
                "Final document has no rendered PDF or DOCX file to store in immutable object storage."
            )

        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)

        access_token = SignerAccessToken.objects.create(
            signer=signer,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(days=cls.TOKEN_TTL_DAYS),
            is_active=True,
        )

        cls.create_audit_log(
            signer=signer,
            event=SigningAuditLog.Event.ACCESS_LINK_CREATED,
            request=request,
            document_hash=document.content_hash,
            metadata={
                "access_token_id": access_token.id,
                "expires_at": access_token.expires_at.isoformat(),
                "ttl_days": cls.TOKEN_TTL_DAYS,
                "stored_objects": [
                    {
                        "id": stored_object.id,
                        "object_type": stored_object.object_type,
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
                    for stored_object in stored_objects
                ],
            },
        )

        return CreatedAccessToken(
            raw_token=raw_token,
            access_token=access_token,
        )

    @classmethod
    def get_valid_token(cls, *, raw_token: str):
        token_hash = cls.hash_token(raw_token)

        return (
            SignerAccessToken.objects
            .select_related(
                "signer",
                "signer__document",
                "signer__document__organization",
            )
            .filter(
                token_hash=token_hash,
                is_active=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )

    @classmethod
    def deactivate_token(cls, *, access_token: SignerAccessToken, save=True):
        access_token.is_active = False
        access_token.used_at = timezone.now()

        if save:
            access_token.save(update_fields=["is_active", "used_at"])

        return access_token

    @classmethod
    def create_audit_log(
        cls,
        *,
        signer,
        event,
        request=None,
        document_hash: str = "",
        signed_content_hash: str = "",
        metadata: dict = None,
    ):
        document = signer.document

        ip_address = ""
        user_agent = ""

        if request:
            ip_address = cls.get_client_ip(request) or ""
            user_agent = request.META.get("HTTP_USER_AGENT", "")

        return SigningAuditLog.objects.create(
            document=document,
            signer=signer,
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

    @staticmethod
    def get_client_ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()

        return request.META.get("REMOTE_ADDR")
