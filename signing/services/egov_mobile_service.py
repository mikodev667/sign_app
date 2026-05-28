import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from documents.models import Document
from signing.models import Signer, SigningSession, Signature


class EgovMobileSigningService:
    SIGN_METHOD = "CMS_WITH_DATA"

    @classmethod
    def get_file_bytes(cls, document: Document) -> bytes:
        if document.rendered_pdf_file:
            with document.rendered_pdf_file.open("rb") as file:
                return file.read()

        if document.rendered_docx_file:
            with document.rendered_docx_file.open("rb") as file:
                return file.read()

        raise ValueError("Document does not have rendered PDF or DOCX file.")

    @classmethod
    def get_mime_type(cls, document: Document) -> str:
        if document.rendered_pdf_file:
            return "application/pdf"

        if document.rendered_docx_file:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        return "application/octet-stream"

    @classmethod
    def calculate_file_hash(cls, file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    @classmethod
    def create_session(cls, *, signer: Signer, request) -> SigningSession:
        file_bytes = cls.get_file_bytes(signer.document)
        document_hash = cls.calculate_file_hash(file_bytes)

        provider_session_id = secrets.token_urlsafe(24)

        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.EGOV_MOBILE,
            provider_session_id=provider_session_id,
            status=SigningSession.Status.WAITING,
            document_hash=document_hash,
            expires_at=timezone.now() + timedelta(minutes=30),
            raw_request={
                "signer_id": signer.id,
                "document_id": signer.document_id,
                "sign_method": cls.SIGN_METHOD,
            },
        )

        api_1_url = request.build_absolute_uri(
            reverse("signing:egov_api_1", kwargs={"session_id": session.provider_session_id})
        )

        android_link = "https://mgovsign.page.link/?link={api}&apn=kz.mobile.mgov".format(
            api=quote(api_1_url, safe="")
        )

        ios_link = "https://mgovsign.page.link/?link={api}&isi=1476128386&ibi=kz.egov.mobile".format(
            api=quote(api_1_url, safe="")
        )

        session.deep_link = android_link
        session.qr_payload = f"mobileSign:{api_1_url}"
        session.raw_response = {
            "api_1_url": api_1_url,
            "android_link": android_link,
            "ios_link": ios_link,
            "qr_payload": session.qr_payload,
        }
        session.save(update_fields=["deep_link", "qr_payload", "raw_response", "updated_at"])

        signer.status = Signer.Status.SIGNING_STARTED
        signer.save(update_fields=["status", "updated_at"])

        return session

    @classmethod
    def build_api_1_response(cls, *, session: SigningSession, request) -> dict:
        api_2_url = request.build_absolute_uri(
            reverse("signing:egov_api_2", kwargs={"session_id": session.provider_session_id})
        )

        organisation = session.signer.document.organization

        return {
            "description": f"Подписание документа: {session.signer.document.title}",
            "expiry_date": session.expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "organisation": {
                "nameRu": organisation.name,
                "nameKz": organisation.name,
                "nameEn": organisation.name,
                "bin": getattr(organisation, "bin", "") or "000000000000",
            },
            "document": {
                "uri": api_2_url,
                "auth_type": "Token",
                "auth_token": session.provider_session_id,
            },
        }

    @classmethod
    def build_api_2_get_response(cls, *, session: SigningSession) -> dict:
        document = session.signer.document
        file_bytes = cls.get_file_bytes(document)
        encoded_file = base64.b64encode(file_bytes).decode("utf-8")

        return {
            "signMethod": cls.SIGN_METHOD,
            "version": 1,
            "documentsToSign": [
                {
                    "id": document.id,
                    "nameRu": document.title,
                    "nameKz": document.title,
                    "nameEn": document.title,
                    "meta": [
                        {
                            "name": "ИИН подписанта",
                            "value": session.signer.iin,
                        },
                        {
                            "name": "ФИО подписанта",
                            "value": session.signer.full_name,
                        },
                        {
                            "name": "Hash документа",
                            "value": session.document_hash,
                        },
                    ],
                    "document": {
                        "file": {
                            "mime": cls.get_mime_type(document),
                            "data": encoded_file,
                        }
                    },
                }
            ],
        }

    @classmethod
    def complete_session(cls, *, session: SigningSession, payload: dict) -> Signature:
        signer = session.signer
        document = signer.document

        documents_to_sign = payload.get("documentsToSign") or []

        if not documents_to_sign:
            raise ValueError("documentsToSign is empty.")

        signed_document = documents_to_sign[0]
        signed_data = (
            signed_document
            .get("document", {})
            .get("file", {})
            .get("data", "")
        )

        if not signed_data:
            raise ValueError("Signed data is empty.")

        signed_content_hash = hashlib.sha256(signed_data.encode("utf-8")).hexdigest()

        signature = Signature.objects.create(
            signer=signer,
            document=document,
            signing_session=session,
            provider=SigningSession.Provider.EGOV_MOBILE,
            certificate_iin=signer.iin,
            certificate_subject=signer.full_name,
            certificate_serial="",
            signature_value=signed_data,
            signed_content_hash=signed_content_hash,
            signed_at=timezone.now(),
            is_valid=True,
            raw_payload=payload,
        )

        session.status = SigningSession.Status.SIGNED
        session.raw_response = payload
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

    @classmethod
    def check_bearer_token(cls, *, request, session: SigningSession) -> bool:
        auth_header = request.headers.get("Authorization", "")

        expected = f"Bearer {session.provider_session_id}"

        return auth_header == expected