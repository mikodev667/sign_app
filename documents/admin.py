from django.contrib import admin
from django.http import HttpResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import (
    DocumentTemplate,
    Document,
    DocumentFieldValue,
    DocumentLawVisionReport,
    DocumentLedgerRecord,
    StoredObject,
    TemplateParty,
    TemplatePartyField,
)
from .services.document_docx_render_service import DocumentDocxRenderService
from .services.evidence_bundle_service import (
    EvidenceBundleError,
    EvidenceBundleService,
)
from .services.template_file_service import TemplateFileService

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
            TemplateFileService.normalize_template_file_to_docx(obj)
            obj.body_template = TemplateFileService.convert_to_html(
                obj.template_file.path
            )
            obj.variables = TemplateFileService.extract_variables(
                obj.template_file.path
            )
            obj.save(update_fields=["body_template", "variables", "updated_at"])

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
        "contract_number",
        "contract_date",
        "organization",
        "template",
        "status",
        "created_by",
        "created_at",
        "signed_at"
    )

    search_fields = (
        "title",
        "contract_number",
        "organization__name",
        "template__title",
        "content_hash"
    )

    list_filter = ("status", "contract_date", "created_at", "signed_at")

    readonly_fields = (
        "contract_number",
        "contract_date",
        "content_hash",
        "created_at",
        "updated_at",
        "signed_at",
        "rendered_docx_file",
        "rendered_pdf_file",
    )

    inlines = [DocumentFieldValueInline]

    actions = ["render_documents", "download_evidence_bundle"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        if not obj.template:
            return

        template_variables = obj.template.variables or []

        for variable in template_variables:
            DocumentFieldValue.objects.get_or_create(
                document=obj,
                field_name=variable,
                defaults={"field_value": ""}
            )

    @admin.action(description="Render selected documents")
    def render_documents(self, request, queryset):
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

    @admin.action(description=gettext_lazy("Download evidence bundle for selected document"))
    def download_evidence_bundle(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                _("Select exactly one document to download an evidence bundle."),
                level="error",
            )
            return None

        document = queryset.prefetch_related("stored_objects").first()

        try:
            bundle = EvidenceBundleService.build_bundle(
                document=document,
                created_by=request.user,
                persist=True,
            )
        except EvidenceBundleError as exc:
            self.message_user(
                request,
                _("Evidence bundle could not be generated: %(error)s") % {
                    "error": exc,
                },
                level="error",
            )
            return None

        response = HttpResponse(bundle.content, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{bundle.filename}"'
        response["X-Evidence-Bundle-SHA256"] = bundle.sha256
        return response


@admin.register(DocumentFieldValue)
class DocumentFieldValueAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "field_name")
    search_fields = ("document__title", "field_name", "field_value")


@admin.register(DocumentLawVisionReport)
class DocumentLawVisionReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "status",
        "overall_score",
        "risk_level",
        "contract_type_detected",
        "source",
        "created_at",
    )
    list_filter = ("status", "risk_level", "source", "created_at")
    search_fields = (
        "document__title",
        "content_hash",
        "summary",
        "error_code",
        "error_message",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "analysis",
        "metadata",
        "raw_response",
    )


@admin.register(DocumentLedgerRecord)
class DocumentLedgerRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "status",
        "external_id",
        "ledger_id",
        "document_token",
        "sequence",
        "last_verification_status",
        "submitted_at",
        "created_at",
    )
    list_filter = (
        "status",
        "last_verification_status",
        "actor",
        "created_at",
        "submitted_at",
    )
    search_fields = (
        "document__title",
        "external_id",
        "ledger_id",
        "document_token",
        "document_hash",
        "entry_hash",
        "error_code",
        "error_message",
    )
    readonly_fields = (
        "document",
        "requested_by",
        "status",
        "actor",
        "external_id",
        "source_filename",
        "ledger_pdf_object",
        "ledger_id",
        "document_token",
        "document_hash",
        "size_bytes",
        "sequence",
        "entry_hash",
        "previous_hash",
        "server_signature_b64",
        "server_key_id",
        "ledger_created_at",
        "request_metadata",
        "raw_response",
        "error_code",
        "error_message",
        "last_verified_at",
        "last_verification_status",
        "last_verification_result",
        "last_verification_error",
        "submitted_at",
        "created_at",
        "updated_at",
    )


@admin.register(StoredObject)
class StoredObjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "object_type",
        "bucket",
        "version_id",
        "sha256",
        "retention_until",
        "storage_status",
        "created_at",
    )
    list_filter = ("object_type", "storage_status", "retention_mode", "created_at")
    search_fields = ("document__title", "object_key", "sha256", "version_id")
    readonly_fields = (
        "document",
        "object_type",
        "bucket",
        "object_key",
        "version_id",
        "etag",
        "sha256",
        "content_type",
        "size_bytes",
        "retention_mode",
        "retention_until",
        "storage_status",
        "created_by",
        "created_at",
    )
