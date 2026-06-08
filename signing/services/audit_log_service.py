from signing.models import SigningAuditLog


class SigningAuditLogService:
    @classmethod
    def get_client_ip(cls, request) -> str:
        if not request:
            return ""

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        return request.META.get("REMOTE_ADDR", "")

    @classmethod
    def get_user_agent(cls, request) -> str:
        if not request:
            return ""

        return request.META.get("HTTP_USER_AGENT", "")

    @classmethod
    def log(
        cls,
        *,
        document=None,
        event,
        signer=None,
        signing_session=None,
        request=None,
        document_hash="",
        signed_content_hash="",
        metadata=None,
    ):
        """
        Единый сервис для записи SigningAuditLog.

        Можно вызывать так:

        SigningAuditLogService.log(
            signer=signer,
            event=SigningAuditLog.Event.SMS_CODE_SENT,
            request=request,
            signing_session=session,
        )

        document можно не передавать, если есть signer.
        """

        if document is None and signer is not None:
            document = signer.document

        if document is None and signing_session is not None:
            document = signing_session.signer.document

        if document is None:
            raise ValueError("Document is required for SigningAuditLog.")

        if signer is None and signing_session is not None:
            signer = signing_session.signer

        ip_address = cls.get_client_ip(request) or None
        user_agent = cls.get_user_agent(request)

        resolved_document_hash = (
            document_hash
            or getattr(document, "content_hash", "")
            or getattr(signing_session, "document_hash", "")
            or ""
        )

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
            document_hash=resolved_document_hash,
            signed_content_hash=signed_content_hash or "",
            metadata=metadata or {},
        )

    @classmethod
    def log_signer_event(
        cls,
        *,
        signer,
        event,
        request=None,
        signing_session=None,
        document_hash="",
        signed_content_hash="",
        metadata=None,
    ):
        return cls.log(
            document=signer.document,
            signer=signer,
            signing_session=signing_session,
            event=event,
            request=request,
            document_hash=document_hash,
            signed_content_hash=signed_content_hash,
            metadata=metadata,
        )

    @classmethod
    def log_session_event(
        cls,
        *,
        signing_session,
        event,
        request=None,
        document_hash="",
        signed_content_hash="",
        metadata=None,
    ):
        signer = signing_session.signer

        return cls.log(
            document=signer.document,
            signer=signer,
            signing_session=signing_session,
            event=event,
            request=request,
            document_hash=document_hash,
            signed_content_hash=signed_content_hash,
            metadata=metadata,
        )