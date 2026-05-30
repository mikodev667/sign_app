from signing.models import SigningAuditLog


class SigningAuditLogService:
    @classmethod
    def get_client_ip(cls, request) -> str:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        return request.META.get("REMOTE_ADDR", "")

    @classmethod
    def get_user_agent(cls, request) -> str:
        return request.META.get("HTTP_USER_AGENT", "")

    @classmethod
    def log(
        cls,
        *,
        document,
        event,
        signer=None,
        signing_session=None,
        request=None,
        document_hash="",
        signed_content_hash="",
        metadata=None,
    ):
        ip_address = None
        user_agent = ""

        if request:
            ip_address = cls.get_client_ip(request) or None
            user_agent = cls.get_user_agent(request)

        return SigningAuditLog.objects.create(
            document=document,
            signer=signer,
            signing_session=signing_session,
            event=event,
            signing_method=getattr(signer, "signing_method", "") if signer else "",
            phone=getattr(signer, "phone", "") if signer else "",
            iin=getattr(signer, "iin", "") if signer else "",
            full_name=getattr(signer, "full_name", "") if signer else "",
            ip_address=ip_address,
            user_agent=user_agent,
            document_hash=document_hash or "",
            signed_content_hash=signed_content_hash or "",
            metadata=metadata or {},
        )