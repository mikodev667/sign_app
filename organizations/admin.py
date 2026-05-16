from django.contrib import admin

from .models import Organization, OrganizationMember


class OrganizationMemberInline(admin.TabularInline):
    model = OrganizationMember
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "bin", "created_by", "created_at")
    search_fields = ("name", "bin")
    list_filter = ("created_at",)
    inlines = [OrganizationMemberInline]


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "user", "role", "created_at")
    search_fields = ("organization__name", "user__username", "user__email")
    list_filter = ("role", "created_at")