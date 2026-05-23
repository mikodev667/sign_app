import os
from uuid import uuid4

from django.core.files import File
from django.conf import settings

from .docx_template_service import DocxTemplateService


class DocumentDocxRenderService:
    @classmethod
    def render(cls, document):
        template = document.template

        if not template.template_file:
            raise ValueError("Document template has no DOCX file.")

        values = {
            field.field_name: field.field_value
            for field in document.field_values.all()
        }

        output_dir = os.path.join(settings.MEDIA_ROOT, "documents", "docx")
        os.makedirs(output_dir, exist_ok=True)

        filename = f"document_{document.id}_{uuid4().hex}.docx"
        output_path = os.path.join(output_dir, filename)

        DocxTemplateService.render_docx(
            template_path=template.template_file.path,
            output_path=output_path,
            values=values,
        )

        with open(output_path, "rb") as f:
            document.rendered_docx_file.save(filename, File(f), save=False)

        document.update_content_hash(save=False)
        document.save(update_fields=["rendered_docx_file", "content_hash", "updated_at"])

        return document