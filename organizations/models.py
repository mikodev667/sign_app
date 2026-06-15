from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(models.Model):
    name = models.CharField(max_length=255)
    bin = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        verbose_name=_("BIN")
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_organizations"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrganizationMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")

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
        verbose_name = _("Organization member")
        verbose_name_plural = _("Organization members")
        unique_together = ("organization", "user")

    def clean(self):
        super().clean()

        if not self.user_id:
            return

        existing_membership = OrganizationMember.objects.filter(
            user_id=self.user_id,
        )

        if self.pk:
            existing_membership = existing_membership.exclude(pk=self.pk)

        if existing_membership.exists():
            raise ValidationError({
                "user": _("This user already belongs to another organization."),
            })

    def __str__(self):
        return f"{self.user} - {self.organization} ({self.role})"
