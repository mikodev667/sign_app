import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse


class OnlyOfficeTokenError(ValueError):
    pass


class OnlyOfficeService:
    @classmethod
    def build_editor_config(cls, *, document, user, request=None):
        access_token = cls.encode_token({
            "document_id": document.pk,
            "action": "download",
            "exp": int(time.time()) + settings.ONLYOFFICE_ACCESS_TOKEN_TTL_SECONDS,
        })
        callback_token = cls.encode_token({
            "document_id": document.pk,
            "action": "callback",
            "exp": int(time.time()) + settings.ONLYOFFICE_ACCESS_TOKEN_TTL_SECONDS,
        })

        file_url = cls.build_internal_url(
            reverse("documents:document_onlyoffice_file", args=[document.pk]),
            {"token": access_token},
        )
        callback_url = cls.build_internal_url(
            reverse("documents:document_onlyoffice_callback", args=[document.pk]),
            {"token": callback_token},
        )
        config = {
            "documentType": "word",
            "document": {
                "fileType": "docx",
                "key": cls.document_key(document),
                "title": document.rendered_docx_file.name.rsplit("/", 1)[-1] or f"document-{document.pk}.docx",
                "url": file_url,
                "permissions": {
                    "download": True,
                    "edit": document.can_be_edited(),
                    "print": True,
                    "review": True,
                },
            },
            "editorConfig": {
                "callbackUrl": callback_url,
                "lang": "ru",
                "mode": "edit" if document.can_be_edited() else "view",
                "user": {
                    "id": str(user.pk),
                    "name": user.get_full_name() or user.get_username(),
                },
                "customization": {
                    "autosave": True,
                    "forcesave": True,
                },
            },
            "height": "100%",
            "width": "100%",
        }
        config["token"] = cls.encode_token(config)
        return config

    @classmethod
    def build_template_editor_config(cls, *, template, user, request=None):
        access_token = cls.encode_token({
            "template_id": template.pk,
            "action": "download_template",
            "exp": int(time.time()) + settings.ONLYOFFICE_ACCESS_TOKEN_TTL_SECONDS,
        })
        callback_token = cls.encode_token({
            "template_id": template.pk,
            "action": "callback_template",
            "exp": int(time.time()) + settings.ONLYOFFICE_ACCESS_TOKEN_TTL_SECONDS,
        })

        file_url = cls.build_internal_url(
            reverse("documents:template_onlyoffice_file", args=[template.pk]),
            {"token": access_token},
        )
        callback_url = cls.build_internal_url(
            reverse("documents:template_onlyoffice_callback", args=[template.pk]),
            {"token": callback_token},
        )
        config = {
            "documentType": "word",
            "document": {
                "fileType": "docx",
                "key": cls.template_key(template),
                "title": template.template_file.name.rsplit("/", 1)[-1] or f"template-{template.pk}.docx",
                "url": file_url,
                "permissions": {
                    "download": True,
                    "edit": True,
                    "print": True,
                    "review": True,
                },
            },
            "editorConfig": {
                "callbackUrl": callback_url,
                "lang": "ru",
                "mode": "edit",
                "user": {
                    "id": str(user.pk),
                    "name": user.get_full_name() or user.get_username(),
                },
                "customization": {
                    "autosave": True,
                    "forcesave": True,
                },
            },
            "height": "100%",
            "width": "100%",
        }
        config["token"] = cls.encode_token(config)
        return config

    @classmethod
    def document_key(cls, document):
        source = "|".join([
            str(document.pk),
            document.content_hash or "",
            document.rendered_docx_file.name or "",
            str(int(document.updated_at.timestamp())) if document.updated_at else "",
        ])
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]

    @classmethod
    def template_key(cls, template):
        source = "|".join([
            str(template.pk),
            template.template_file.name or "",
            str(int(template.updated_at.timestamp())) if template.updated_at else "",
        ])
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]

    @classmethod
    def force_save_key(cls, key):
        payload = {
            "c": "forcesave",
            "key": key,
        }
        payload["token"] = cls.encode_token(payload)
        response = requests.post(
            settings.ONLYOFFICE_COMMAND_SERVICE_URL,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    @classmethod
    def build_internal_url(cls, path, params=None):
        base = settings.ONLYOFFICE_DJANGO_URL.rstrip("/")
        url = f"{base}{path}"

        if params:
            url = f"{url}?{urlencode(params)}"

        return url

    @classmethod
    def verify_action_token(cls, token, *, document_id=None, template_id=None, action):
        payload = cls.decode_token(token)

        if document_id is not None and str(payload.get("document_id")) != str(document_id):
            raise OnlyOfficeTokenError("Token document mismatch.")

        if template_id is not None and str(payload.get("template_id")) != str(template_id):
            raise OnlyOfficeTokenError("Token template mismatch.")

        if payload.get("action") != action:
            raise OnlyOfficeTokenError("Token action mismatch.")

        exp = payload.get("exp")

        if exp and int(exp) < int(time.time()):
            raise OnlyOfficeTokenError("Token expired.")

        return payload

    @classmethod
    def encode_token(cls, payload):
        header = {"alg": "HS256", "typ": "JWT"}
        header_part = cls.base64url_encode(cls.json_bytes(header))
        payload_part = cls.base64url_encode(cls.json_bytes(payload))
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        signature = hmac.new(
            cls.secret_bytes(),
            signing_input,
            hashlib.sha256,
        ).digest()
        return f"{header_part}.{payload_part}.{cls.base64url_encode(signature)}"

    @classmethod
    def decode_token(cls, token):
        try:
            header_part, payload_part, signature_part = token.split(".")
        except ValueError as exc:
            raise OnlyOfficeTokenError("Invalid token format.") from exc

        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected_signature = hmac.new(
            cls.secret_bytes(),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_signature = cls.base64url_decode(signature_part)

        if not hmac.compare_digest(expected_signature, actual_signature):
            raise OnlyOfficeTokenError("Invalid token signature.")

        try:
            return json.loads(cls.base64url_decode(payload_part))
        except (TypeError, ValueError) as exc:
            raise OnlyOfficeTokenError("Invalid token payload.") from exc

    @staticmethod
    def json_bytes(value):
        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @staticmethod
    def secret_bytes():
        return settings.ONLYOFFICE_JWT_SECRET.encode("utf-8")

    @staticmethod
    def base64url_encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def base64url_decode(value):
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
