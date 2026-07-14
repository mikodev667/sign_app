import hashlib
from dataclasses import dataclass

import requests

from documents.services.onlyoffice_service import OnlyOfficeService


class PdfExportError(Exception):
    pass


@dataclass
class ExportedPdf:
    filename: str
    content: bytes
    content_type: str = "application/pdf"


class OnlyOfficePdfExportService:
    @classmethod
    def export_document_pdf(cls, document) -> ExportedPdf:
        if document.rendered_pdf_file:
            return cls.read_existing_pdf(document)

        if not document.rendered_docx_file:
            raise PdfExportError("Document has no DOCX file to convert to PDF.")

        return cls.convert_docx_to_pdf(document)

    @staticmethod
    def read_existing_pdf(document) -> ExportedPdf:
        document.rendered_pdf_file.open("rb")
        try:
            content = document.rendered_pdf_file.read()
        finally:
            document.rendered_pdf_file.close()

        filename = document.rendered_pdf_file.name.rsplit("/", 1)[-1] or f"document-{document.pk}.pdf"
        return ExportedPdf(filename=filename, content=content)

    @classmethod
    def convert_docx_to_pdf(cls, document) -> ExportedPdf:
        source_filename = document.rendered_docx_file.name.rsplit("/", 1)[-1] or f"document-{document.pk}.docx"
        output_filename = f"{source_filename.rsplit('.', 1)[0]}.pdf"
        file_url = OnlyOfficeService.build_document_file_url(document)

        payload = {
            "async": False,
            "filetype": "docx",
            "key": cls.conversion_key(document),
            "outputtype": "pdf",
            "title": source_filename,
            "url": file_url,
        }
        payload["token"] = OnlyOfficeService.encode_token(payload)

        try:
            response = requests.post(
                OnlyOfficeService.convert_service_url(payload["key"]),
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PdfExportError(f"OnlyOffice PDF conversion request failed: {exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            content_type = response.headers.get("Content-Type", "")
            snippet = response.text[:500].strip()
            raise PdfExportError(
                "OnlyOffice PDF conversion returned non-JSON response "
                f"(HTTP {response.status_code}, content-type: {content_type}). "
                f"Response: {snippet}"
            ) from exc

        if result.get("error"):
            raise PdfExportError(f"OnlyOffice PDF conversion failed with error {result.get('error')}.")

        if result.get("endConvert") is False:
            raise PdfExportError("OnlyOffice PDF conversion is not finished yet.")

        pdf_url = result.get("fileUrl") or result.get("url")
        if not pdf_url:
            raise PdfExportError("OnlyOffice PDF conversion did not return a file URL.")

        pdf_url = OnlyOfficeService.get_server_internal_url(pdf_url)

        try:
            pdf_response = requests.get(pdf_url, timeout=60)
            pdf_response.raise_for_status()
        except requests.RequestException as exc:
            raise PdfExportError(f"Converted PDF download failed: {exc}") from exc

        return ExportedPdf(filename=output_filename, content=pdf_response.content)

    @staticmethod
    def conversion_key(document) -> str:
        source = "|".join([
            "ledger-pdf",
            str(document.pk),
            document.content_hash or "",
            document.rendered_docx_file.name or "",
            str(int(document.updated_at.timestamp())) if document.updated_at else "",
        ])
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
