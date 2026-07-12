from django.contrib import admin

from .models import (
    Signer,
    SignerAccessToken,
    SigningAuditLog,
    SigningSession,
    Signature,
)


class SigningSessionInline(admin.TabularInline):
    model = SigningSession
    extra = 0
    readonly_fields = ("provider_session_id", "status", "document_hash", "created_at", "updated_at")


@admin.register(Signer)
class SignerAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "iin", "phone", "email", "document", "signing_order", "status", "created_at", "signed_at")
    search_fields = ("full_name", "iin", "phone", "email", "document__title")
    list_filter = ("status", "signing_order", "created_at", "signed_at")
    inlines = [SigningSessionInline]


@admin.register(SignerAccessToken)
class SignerAccessTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "signer", "expires_at", "used_at", "is_active", "created_at")
    search_fields = ("signer__full_name", "signer__iin", "token_hash")
    list_filter = ("is_active", "expires_at", "created_at")
    readonly_fields = ("token_hash", "created_at")


@admin.register(SigningSession)
class SigningSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "signer", "provider", "provider_session_id", "status", "document_hash", "created_at")
    search_fields = ("signer__full_name", "signer__iin", "provider_session_id", "document_hash")
    list_filter = ("provider", "status", "created_at")
    readonly_fields = ("raw_request", "raw_response", "created_at", "updated_at")


@admin.register(Signature)
class SignatureAdmin(admin.ModelAdmin):
    list_display = ("id", "signer", "document", "provider", "certificate_iin", "is_valid", "signed_at", "created_at")
    search_fields = ("signer__full_name", "signer__iin", "certificate_iin", "certificate_serial", "document__title")
    list_filter = ("provider", "is_valid", "signed_at", "created_at")
    readonly_fields = ("raw_payload", "created_at")


@admin.register(SigningAuditLog)
class SigningAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "signer",
        "event",
        "document_hash",
        "entry_hash",
        "created_at",
    )
    search_fields = (
        "document__title",
        "signer__full_name",
        "event",
        "document_hash",
        "entry_hash",
        "previous_hash",
    )
    list_filter = ("event", "created_at")
    readonly_fields = (
        "document",
        "signer",
        "signing_session",
        "event",
        "signing_method",
        "phone",
        "iin",
        "full_name",
        "ip_address",
        "user_agent",
        "document_hash",
        "signed_content_hash",
        "metadata",
        "payload_hash",
        "previous_hash",
        "entry_hash",
        "created_at",
    )
