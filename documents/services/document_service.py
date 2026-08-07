from django.db import transaction

from documents.models import Document, DocumentTemplate
from documents.services.document_render_service import DocumentRenderService
from documents.services.template_service import TemplateService


class DocumentService:
    @classmethod
    @transaction.atomic
    def create_document_from_template(
        cls,
        *,
        template: DocumentTemplate,
        created_by,
        title: str,
        values: dict[str, str],
    ) -> Document:
        """
        Create a document from template:
        1. Validate template
        2. Validate provided field values
        3. Create Document
        4. Save field values
        5. Render final HTML
        6. Calculate content hash
        """

        is_valid, errors = TemplateService.validate_template(template.body_template)

        if not is_valid:
            raise ValueError("; ".join(errors))

        required_variables = TemplateService.extract_variables(template.body_template)

        missing_fields = [
            variable
            for variable in required_variables
            if variable not in values
        ]

        if missing_fields:
            raise ValueError(
                "Missing document fields: " + ", ".join(missing_fields)
            )

        document = Document.objects.create(
            organization=template.organization,
            department=template.department,
            template=template,
            created_by=created_by,
            title=title,
            status=Document.Status.DRAFT,
        )

        cleaned_values = {
            variable: values.get(variable, "")
            for variable in required_variables
        }

        DocumentRenderService.create_field_values(
            document=document,
            values=cleaned_values,
        )

        DocumentRenderService.render_document(document=document)

        return document

    @classmethod
    @transaction.atomic
    def update_document_values(
        cls,
        *,
        document: Document,
        values: dict[str, str],
    ) -> Document:
        """
        Update field values and re-render document.
        Allowed only while document is draft.
        """

        if document.status != Document.Status.DRAFT:
            raise ValueError("Only draft documents can be edited.")

        required_variables = TemplateService.extract_variables(
            document.template.body_template
        )

        cleaned_values = {
            variable: values.get(variable, "")
            for variable in required_variables
        }

        DocumentRenderService.create_field_values(
            document=document,
            values=cleaned_values,
        )

        DocumentRenderService.render_document(document=document)

        return document
