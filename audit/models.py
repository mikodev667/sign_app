from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="audit_logs",
        blank=True,
        null=True
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        blank=True,
        null=True
    )

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        blank=True,
        null=True
    )

    signer = models.ForeignKey(
        "signing.Signer",
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        blank=True,
        null=True
    )

    action = models.CharField(max_length=100, db_index=True)

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)

    metadata = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Audit log"
        verbose_name_plural = "Audit logs"
        ordering = ["-created_at"]

    def __str__(self):
        return self.action