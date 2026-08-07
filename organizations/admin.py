from django.contrib import admin

from .models import Department, Organization, OrganizationMember


class DepartmentInline(admin.TabularInline):
    model = Department
    extra = 0


class OrganizationMemberInline(admin.TabularInline):
    model = OrganizationMember
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "bin", "created_by", "created_at")
    search_fields = ("name", "bin")
    list_filter = ("created_at",)
    inlines = [DepartmentInline, OrganizationMemberInline]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization", "is_active", "created_at")
    search_fields = ("name", "organization__name")
    list_filter = ("is_active", "created_at")


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "department", "user", "role", "created_at")
    search_fields = ("organization__name", "department__name", "user__username", "user__email")
    list_filter = ("role", "department", "created_at")
