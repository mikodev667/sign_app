from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=255)
    bin = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        verbose_name="BIN"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_organizations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrganizationMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships"
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Organization member"
        verbose_name_plural = "Organization members"
        unique_together = ("organization", "user")

    def __str__(self):
        return f"{self.user} - {self.organization} ({self.role})"