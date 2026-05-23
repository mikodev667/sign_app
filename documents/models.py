import hashlib

from django.conf import settings
from django.db import models


class DocumentTemplate(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="document_templates"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_document_templates"
    )

    title = models.CharField(max_length=255)

    body_template = models.TextField(
        blank=True,
        help_text="Use variables like {{ client_name }}, {{ amount }}"
    )

    template_file = models.FileField(
        upload_to="document_templates/docx/",
        blank=True,
        null=True
    )

    variables = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Document template"
        verbose_name_plural = "Document templates"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Document(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        WAITING_FOR_SIGNERS = "waiting_for_signers", "Waiting for signers"
        PARTIALLY_SIGNED = "partially_signed", "Partially signed"
        SIGNED = "signed", "Signed"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="documents"
    )

    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.PROTECT,
        related_name="documents"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_documents"
    )

    title = models.CharField(max_length=255)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT
    )

    rendered_html = models.TextField(blank=True)

    rendered_pdf_file = models.FileField(
        upload_to="documents/pdf/",
        blank=True,
        null=True
    )

    rendered_docx_file = models.FileField(
        upload_to="documents/docx/",
        blank=True,
        null=True
    )

    content_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    signed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def calculate_content_hash(self):
        source = self.rendered_html or ""

        for value in self.field_values.all().order_by("field_name"):
            source += f"{value.field_name}:{value.field_value};"

        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def update_content_hash(self, save=True):
        self.content_hash = self.calculate_content_hash()
        if save:
            self.save(update_fields=["content_hash", "updated_at"])


class DocumentFieldValue(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="field_values"
    )

    field_name = models.CharField(max_length=100)
    field_value = models.TextField(blank=True)

    class Meta:
        verbose_name = "Document field value"
        verbose_name_plural = "Document field values"
        unique_together = ("document", "field_name")
        ordering = ["field_name"]

    def __str__(self):
        return f"{self.document} - {self.field_name}"
