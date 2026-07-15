import hashlib
import html

from documents.models import Document, DocumentFieldValue
from documents.services.template_service import TemplateService


class DocumentRenderService:
    @classmethod
    def render_from_template(cls, *, template_body: str, values: dict[str, str]) -> str:
        """
        Simple safe renderer for MVP.

        Replaces:
            {{ field_name }}

        With escaped values.
        """
        rendered = template_body or ""

        variables = TemplateService.extract_variables(rendered)

        for variable in variables:
            raw_value = values.get(variable, "")
            safe_value = html.escape(str(raw_value))

            rendered = rendered.replace(f"{{{{ {variable} }}}}", safe_value)
            rendered = rendered.replace(f"{{{{{variable}}}}}", safe_value)

        return rendered

    @classmethod
    def calculate_hash(cls, content: str) -> str:
        content = content or ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def render_document(cls, *, document: Document) -> Document:
        """
        Re-render document from its template and saved field values.
        """
        values = {
            item.field_name: item.field_value
            for item in document.field_values.all()
        }
        values.update(document.get_contract_system_values())

        rendered_html = cls.render_from_template(
            template_body=document.template.body_template,
            values=values,
        )

        document.rendered_html = rendered_html
        document.content_hash = cls.calculate_hash(rendered_html)
        document.save(update_fields=["rendered_html", "content_hash", "updated_at"])

        return document

    @classmethod
    def create_field_values(cls, *, document: Document, values: dict[str, str]) -> None:
        """
        Create or update field values for document.
        """
        for field_name, field_value in values.items():
            DocumentFieldValue.objects.update_or_create(
                document=document,
                field_name=field_name,
                defaults={"field_value": field_value},
            )
