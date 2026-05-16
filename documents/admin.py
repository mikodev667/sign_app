from django.contrib import admin

from .models import DocumentTemplate, Document, DocumentFieldValue


class DocumentFieldValueInline(admin.TabularInline):
    model = DocumentFieldValue
    extra = 0


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "organization", "created_by", "status", "created_at")
    search_fields = ("title", "organization__name", "body_template")
    list_filter = ("status", "created_at")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "organization", "template", "status", "created_by", "created_at", "signed_at")
    search_fields = ("title", "organization__name", "template__title", "content_hash")
    list_filter = ("status", "created_at", "signed_at")
    readonly_fields = ("content_hash", "created_at", "updated_at", "signed_at")
    inlines = [DocumentFieldValueInline]


@admin.register(DocumentFieldValue)
class DocumentFieldValueAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "field_name")
    search_fields = ("document__title", "field_name", "field_value")