from django.contrib import admin

from admissions.models import (
    AdmissionApiClient,
    AdmissionCommissionProfile,
    AdmissionContract,
    AdmissionRenderJob,
    AdmissionTemplateRule,
    AdmissionViceRectorProfile,
)


@admin.register(AdmissionApiClient)
class AdmissionApiClientAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "expires_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("token_hash", "created_at")


@admin.register(AdmissionViceRectorProfile)
class AdmissionViceRectorProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "organization", "department", "is_active")
    list_filter = ("is_active", "organization", "department")
    search_fields = ("full_name", "iin", "phone", "user__username")


@admin.register(AdmissionCommissionProfile)
class AdmissionCommissionProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "organization", "department", "is_active")
    list_filter = ("is_active", "organization", "department")
    search_fields = ("full_name", "user__username")


@admin.register(AdmissionTemplateRule)
class AdmissionTemplateRuleAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "education_level",
        "funding_type",
        "language",
        "program_code",
        "template",
        "application_template",
        "vice_rector",
        "priority",
        "is_active",
    )
    list_filter = ("education_level", "funding_type", "language", "is_active")
    search_fields = ("title", "program_code", "template__title")


@admin.register(AdmissionContract)
class AdmissionContractAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "applicant_full_name",
        "education_level",
        "funding_type",
        "status",
        "document",
        "application_document",
        "created_at",
    )
    list_filter = ("status", "education_level", "funding_type", "language")
    search_fields = ("external_id", "applicant_full_name", "applicant_iin")
    readonly_fields = (
        "access_token_hash",
        "raw_payload",
        "created_at",
        "updated_at",
    )


@admin.register(AdmissionRenderJob)
class AdmissionRenderJobAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "status",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "locked_at",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = (
        "contract__external_id",
        "contract__applicant_full_name",
        "last_error",
    )
    readonly_fields = (
        "contract",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "locked_at",
        "last_error",
        "created_at",
        "updated_at",
    )
