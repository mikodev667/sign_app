from django.contrib import admin
from .services.docx_template_service import DocxTemplateService
from .models import DocumentTemplate, Document, DocumentFieldValue, TemplateParty, TemplatePartyField
from .services.document_docx_render_service import DocumentDocxRenderService

class DocumentFieldValueInline(admin.TabularInline):
    model = DocumentFieldValue
    extra = 0


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "organization", "created_by", "status", "created_at")
    search_fields = ("title", "organization__name", "body_template")
    list_filter = ("status", "created_at")
    readonly_fields = ("variables", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        if obj.template_file:
            obj.variables = DocxTemplateService.extract_variables(
                obj.template_file.path
            )
            obj.save(update_fields=["variables", "updated_at"])

class TemplatePartyFieldInline(admin.TabularInline):
    model = TemplatePartyField
    extra = 1


class TemplatePartyInline(admin.TabularInline):
    model = TemplateParty
    extra = 1
    
@admin.register(TemplateParty)
class TemplatePartyAdmin(admin.ModelAdmin):
    list_display = ("title", "template", "variable_prefix", "signing_order", "is_signer")
    list_filter = ("template", "is_signer")
    search_fields = ("title", "variable_prefix")
    inlines = [TemplatePartyFieldInline]


@admin.register(TemplatePartyField)
class TemplatePartyFieldAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "party",
        "variable_name",
        "field_type",
        "is_required",
        "is_system",
        "order",
    )
    list_filter = ("field_type", "is_required", "is_system")
    search_fields = ("label", "variable_name")

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "organization",
        "template",
        "status",
        "created_by",
        "created_at",
        "signed_at"
    )

    search_fields = (
        "title",
        "organization__name",
        "template__title",
        "content_hash"
    )

    list_filter = ("status", "created_at", "signed_at")

    readonly_fields = (
        "content_hash",
        "created_at",
        "updated_at",
        "signed_at",
        "rendered_docx_file",
    )

    inlines = [DocumentFieldValueInline]

    actions = ["render_docx_documents"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        template_variables = obj.template.variables or []

        for variable in template_variables:
            DocumentFieldValue.objects.get_or_create(
                document=obj,
                field_name=variable,
                defaults={"field_value": ""}
            )

    @admin.action(description="Render selected DOCX documents")
    def render_docx_documents(self, request, queryset):
        success_count = 0

        for document in queryset:
            try:
                DocumentDocxRenderService.render(document)
                success_count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error rendering document #{document.id}: {e}",
                    level="error"
                )

        self.message_user(
            request,
            f"Successfully rendered {success_count} document(s)."
        )


@admin.register(DocumentFieldValue)
class DocumentFieldValueAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "field_name")
    search_fields = ("document__title", "field_name", "field_value")