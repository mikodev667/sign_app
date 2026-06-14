import mimetypes
import os
import time

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from documents.models import Document, DocumentLawVisionReport


class LawVisionError(Exception):
    def __init__(self, message, *, error_code="", status_code=None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class LawVisionConfigurationError(LawVisionError):
    pass


class LawVisionService:
    ANALYZE_PATH = "/contracts/analyze"
    RETRY_STATUSES = {502, 503}
    RETRY_DELAYS = (2, 4, 8)

    @classmethod
    def get_or_analyze_document(
        cls,
        *,
        document: Document,
        requested_by=None,
        source=DocumentLawVisionReport.Source.MANAGER,
        language="ru",
        contract_type="",
        perspective="",
        force=False,
    ) -> tuple[DocumentLawVisionReport, bool]:
        content_hash = cls.ensure_content_hash(document)

        lookup = {
            "document": document,
            "content_hash": content_hash,
            "language": language,
            "contract_type": contract_type,
            "perspective": perspective,
        }

        if not force:
            cached_report = (
                DocumentLawVisionReport.objects
                .filter(**lookup, status=DocumentLawVisionReport.Status.SUCCESS)
                .order_by("-created_at")
                .first()
            )

            if cached_report:
                return cached_report, True

        report, _ = DocumentLawVisionReport.objects.update_or_create(
            **lookup,
            defaults={
                "requested_by": requested_by if getattr(requested_by, "is_authenticated", False) else None,
                "source": source,
                "status": DocumentLawVisionReport.Status.PROCESSING,
                "error_code": "",
                "error_message": "",
            },
        )

        try:
            payload = cls.request_analysis(
                document=document,
                language=language,
                contract_type=contract_type,
                perspective=perspective,
            )
        except LawVisionError as exc:
            report.status = DocumentLawVisionReport.Status.FAILED
            report.error_code = exc.error_code
            report.error_message = str(exc)
            report.save(update_fields=[
                "status",
                "error_code",
                "error_message",
                "updated_at",
            ])
            raise

        cls.apply_success_payload(report=report, payload=payload)
        return report, False

    @classmethod
    def ensure_content_hash(cls, document: Document) -> str:
        current_hash = document.calculate_content_hash()

        if document.content_hash != current_hash and document.can_be_edited():
            document.content_hash = current_hash
            document.save(update_fields=["content_hash", "updated_at"])
            return current_hash

        if not document.content_hash:
            document.content_hash = current_hash
            document.save(update_fields=["content_hash", "updated_at"])
            return current_hash

        return document.content_hash

    @classmethod
    def request_analysis(
        cls,
        *,
        document: Document,
        language="ru",
        contract_type="",
        perspective="",
    ) -> dict:
        api_key = getattr(settings, "LAWVISION_API_KEY", "")

        if not api_key:
            raise LawVisionConfigurationError(
                "LawVision API key is not configured.",
                error_code="missing_api_key",
            )

        url = cls.get_endpoint_url()
        headers = {"Authorization": f"Bearer {api_key}"}
        data = cls.build_form_data(
            language=language,
            contract_type=contract_type,
            perspective=perspective,
        )

        file_field = cls.get_document_file_field(document)

        if file_field:
            return cls.request_file_analysis(
                url=url,
                headers=headers,
                data=data,
                file_field=file_field,
            )

        text = cls.extract_document_text(document)
        if len(text) < 50:
            raise LawVisionError(
                "Document text is shorter than LawVision minimum of 50 characters.",
                error_code="too_short",
            )

        return cls.post_with_retries(
            url=url,
            headers={
                **headers,
                "Content-Type": "application/json",
            },
            json={
                **data,
                "text": text,
            },
        )

    @classmethod
    def get_endpoint_url(cls) -> str:
        base_url = getattr(
            settings,
            "LAWVISION_API_URL",
            "https://lawvision.kz/api/v1",
        ).rstrip("/")

        return f"{base_url}{cls.ANALYZE_PATH}"

    @classmethod
    def build_form_data(cls, *, language, contract_type, perspective) -> dict:
        data = {"language": language or "ru"}

        if contract_type:
            data["contract_type"] = contract_type

        if perspective:
            data["perspective"] = perspective

        return data

    @classmethod
    def get_document_file_field(cls, document: Document):
        if document.rendered_pdf_file:
            return document.rendered_pdf_file

        if document.rendered_docx_file:
            return document.rendered_docx_file

        return None

    @classmethod
    def request_file_analysis(cls, *, url, headers, data, file_field) -> dict:
        file_name = os.path.basename(file_field.name)
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        file_field.open("rb")
        try:
            return cls.post_with_retries(
                url=url,
                headers=headers,
                data=data,
                files={
                    "file": (
                        file_name,
                        file_field.file,
                        mime_type,
                    )
                },
            )
        finally:
            file_field.close()

    @classmethod
    def extract_document_text(cls, document: Document) -> str:
        if document.rendered_html:
            soup = BeautifulSoup(document.rendered_html, "html.parser")
            return " ".join(soup.get_text(" ").split())

        parts = [document.title or ""]

        for value in document.field_values.all().order_by("field_name"):
            if value.field_value:
                parts.append(f"{value.field_name}: {value.field_value}")

        return "\n".join(parts).strip()

    @classmethod
    def post_with_retries(cls, *, url, headers, json=None, data=None, files=None) -> dict:
        timeout = int(getattr(settings, "LAWVISION_TIMEOUT_SECONDS", 90))
        last_response = None

        for attempt, delay in enumerate(cls.RETRY_DELAYS, start=1):
            try:
                cls.rewind_files(files)
                response = requests.post(
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    files=files,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise LawVisionError(
                    f"Could not connect to LawVision: {exc}",
                    error_code="request_failed",
                ) from exc

            last_response = response

            if response.status_code not in cls.RETRY_STATUSES or attempt == len(cls.RETRY_DELAYS):
                break

            time.sleep(delay)

        return cls.parse_response(last_response)

    @staticmethod
    def rewind_files(files) -> None:
        if not files:
            return

        for file_value in files.values():
            if isinstance(file_value, tuple) and len(file_value) >= 2:
                stream = file_value[1]
            else:
                stream = file_value

            if hasattr(stream, "seek"):
                stream.seek(0)

    @classmethod
    def parse_response(cls, response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise LawVisionError(
                "LawVision returned a non-JSON response.",
                error_code="invalid_json",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400 or not payload.get("success"):
            raise LawVisionError(
                payload.get("error") or "LawVision analysis failed.",
                error_code=payload.get("error_code", "lawvision_error"),
                status_code=response.status_code,
            )

        return payload

    @classmethod
    def apply_success_payload(cls, *, report: DocumentLawVisionReport, payload: dict) -> None:
        analysis = payload.get("analysis") or {}
        metadata = payload.get("metadata") or {}

        report.status = DocumentLawVisionReport.Status.SUCCESS
        report.contract_type_detected = analysis.get("contract_type_detected", "") or ""
        report.overall_score = cls.normalize_score(analysis.get("overall_score"))
        report.risk_level = analysis.get("risk_level", "") or ""
        report.summary = analysis.get("summary", "") or ""
        report.analysis = analysis
        report.metadata = metadata
        report.raw_response = payload
        report.error_code = ""
        report.error_message = ""
        report.save(update_fields=[
            "status",
            "contract_type_detected",
            "overall_score",
            "risk_level",
            "summary",
            "analysis",
            "metadata",
            "raw_response",
            "error_code",
            "error_message",
            "updated_at",
        ])

    @staticmethod
    def normalize_score(value):
        try:
            score = int(value)
        except (TypeError, ValueError):
            return None

        return max(0, min(score, 100))
