import os
from uuid import uuid4

from django.conf import settings
from django.core.files import File

from .docx_template_service import DocxTemplateService
from .html_to_docx_service import HtmlToDocxService


class DocumentDocxRenderService:
    @classmethod
    def render(cls, document):
        template = document.template

        values = {
            field.field_name: field.field_value
            for field in document.field_values.all()
        }

        output_dir = os.path.join(settings.MEDIA_ROOT, "documents", "docx")
        os.makedirs(output_dir, exist_ok=True)

        filename = f"document_{document.id}_{uuid4().hex}.docx"
        output_path = os.path.join(output_dir, filename)

        if document.rendered_html:
            HtmlToDocxService.render_html_to_docx(
                html=document.rendered_html,
                output_path=output_path,
            )
        else:
            if not template.template_file:
                raise ValueError("Document template has no DOCX file.")

            template_path = template.template_file.path

            if not os.path.exists(template_path):
                raise FileNotFoundError(
                    f"Template DOCX file not found: {template_path}. "
                    f"Please upload the template file again."
                )

            if not template_path.lower().endswith(".docx"):
                raise ValueError("Template file must be a .docx file.")

            DocxTemplateService.render_docx(
                template_path=template_path,
                output_path=output_path,
                values=values,
            )

        with open(output_path, "rb") as f:
            document.rendered_docx_file.save(filename, File(f), save=False)

        document.rendered_pdf_file = None
        document.update_content_hash(save=False)
        document.save(update_fields=[
            "rendered_docx_file",
            "rendered_pdf_file",
            "content_hash",
            "updated_at",
        ])

        return document
