from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "organization", "user", "document", "signer", "ip_address", "created_at")
    search_fields = (
        "action",
        "organization__name",
        "user__username",
        "document__title",
        "signer__full_name",
        "signer__iin",
    )
    list_filter = ("action", "created_at")
    readonly_fields = ("created_at", "metadata")