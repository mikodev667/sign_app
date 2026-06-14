import hashlib

from django.conf import settings
from django.db import models
from django.utils import timezone


class DocumentTemplate(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="document_templates",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_document_templates",
    )

    title = models.CharField(max_length=255)

    body_template = models.TextField(
        blank=True,
        help_text="Use variables like {{ client_name }}, {{ amount }}",
    )

    template_file = models.FileField(
        upload_to="document_templates/files/",
        blank=True,
        null=True,
    )

    variables = models.JSONField(default=list, blank=True)

    field_schema = models.JSONField(
        default=list,
        blank=True,
        help_text="Groups and fields for document form editor",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
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
        related_name="documents",
    )

    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.PROTECT,
        related_name="documents",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_documents",
    )

    title = models.CharField(max_length=255)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    rendered_html = models.TextField(blank=True)

    rendered_pdf_file = models.FileField(
        upload_to="documents/pdf/",
        blank=True,
        null=True,
    )

    rendered_docx_file = models.FileField(
        upload_to="documents/docx/",
        blank=True,
        null=True,
    )

    content_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="SHA-256 hash of the final document content",
    )

    locked_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        help_text="Document becomes locked after signer invitation",
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

    def is_locked(self):
        """
        Документ нельзя редактировать, если он уже заблокирован
        или вышел из статуса draft.
        """
        return self.locked_at is not None or self.status != self.Status.DRAFT

    def can_be_edited(self):
        """
        Используем это во views/forms перед любым изменением документа.
        """
        return not self.is_locked()

    def calculate_content_hash(self):
        """
        Считаем SHA-256 хеш финального содержимого документа.

        Приоритет:
        1. PDF-файл, если он есть.
        2. DOCX-файл, если он есть.
        3. rendered_html + значения полей.
        """

        sha256 = hashlib.sha256()

        file_field = None

        if self.rendered_pdf_file:
            file_field = self.rendered_pdf_file
        elif self.rendered_docx_file:
            file_field = self.rendered_docx_file

        if file_field:
            file_field.open("rb")
            try:
                for chunk in file_field.chunks():
                    sha256.update(chunk)
            finally:
                file_field.close()

            return sha256.hexdigest()

        source_parts = [
            f"document_id:{self.id}",
            f"title:{self.title}",
            f"template_id:{self.template_id}",
            f"rendered_html:{self.rendered_html or ''}",
        ]

        for value in self.field_values.all().order_by("field_name"):
            source_parts.append(
                f"{value.field_name}:{value.field_value}"
            )

        source = "|".join(source_parts)

        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def update_content_hash(self, save=True):
        """
        Обновляет content_hash.

        Важно:
        Этот метод нельзя вызывать для изменения документа после блокировки.
        Но в момент самой блокировки или подписания использовать можно.
        """
        self.content_hash = self.calculate_content_hash()

        if save:
            self.save(update_fields=["content_hash", "updated_at"])

        return self.content_hash

    def lock_for_signing(self, save=True):
        """
        Блокирует документ после приглашения подписанта.

        После этого документ нельзя редактировать.
        Также фиксируем content_hash на момент отправки на подписание.
        """

        if not self.content_hash:
            self.content_hash = self.calculate_content_hash()

        if not self.locked_at:
            self.locked_at = timezone.now()

        if self.status == self.Status.DRAFT:
            self.status = self.Status.WAITING_FOR_SIGNERS

        if save:
            self.save(
                update_fields=[
                    "content_hash",
                    "locked_at",
                    "status",
                    "updated_at",
                ]
            )

        return self


class DocumentLawVisionReport(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        MANAGER = "manager", "Manager"
        PUBLIC_SIGNER = "public_signer", "Public signer"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="lawvision_reports",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="lawvision_reports",
        blank=True,
        null=True,
    )

    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.MANAGER,
    )

    content_hash = models.CharField(max_length=64, db_index=True)
    language = models.CharField(max_length=5, default="ru")
    contract_type = models.CharField(max_length=100, blank=True)
    perspective = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
        db_index=True,
    )

    contract_type_detected = models.CharField(max_length=100, blank=True)
    overall_score = models.PositiveSmallIntegerField(blank=True, null=True)
    risk_level = models.CharField(max_length=20, blank=True)
    summary = models.TextField(blank=True)

    analysis = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LawVision report"
        verbose_name_plural = "LawVision reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "document",
                    "content_hash",
                    "language",
                    "contract_type",
                    "perspective",
                ],
                name="uniq_lawvision_doc_hash_options",
            )
        ]

    def __str__(self):
        return f"LawVision report for {self.document_id} ({self.status})"

    def is_successful(self):
        return self.status == self.Status.SUCCESS


class DocumentFieldValue(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="field_values",
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


class TemplateParty(models.Model):
    class PartyType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        COMPANY = "company", "Company"

    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.CASCADE,
        related_name="parties",
    )

    title = models.CharField(max_length=255)
    variable_prefix = models.SlugField(max_length=100)

    party_type = models.CharField(
        max_length=30,
        choices=PartyType.choices,
        default=PartyType.INDIVIDUAL,
    )

    signing_order = models.PositiveIntegerField(default=1)

    is_signer = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["signing_order", "id"]
        unique_together = ("template", "variable_prefix")

    def __str__(self):
        return f"{self.template.title} — {self.title}"


class TemplatePartyField(models.Model):
    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        PHONE = "phone", "Phone"
        IIN_BIN = "iin_bin", "IIN / BIN"
        SIGNING_METHOD = "signing_method", "Signing method"
        EMAIL = "email", "Email"
        DATE = "date", "Date"
        NUMBER = "number", "Number"

    class SystemField(models.TextChoices):
        FULL_NAME = "full_name", "Full name"
        IIN_BIN = "iin_bin", "IIN / BIN"
        PHONE = "phone", "Phone"
        SIGNING_METHOD = "signing_method", "Signing method"

    party = models.ForeignKey(
        TemplateParty,
        on_delete=models.CASCADE,
        related_name="fields",
    )

    label = models.CharField(max_length=255)

    variable_name = models.SlugField(
        max_length=100,
        help_text="Example: full_name, iin_bin, phone, address, iban",
    )

    field_type = models.CharField(
        max_length=30,
        choices=FieldType.choices,
        default=FieldType.TEXT,
    )

    is_required = models.BooleanField(default=True)

    is_system = models.BooleanField(
        default=False,
        help_text="System fields are required for signing logic",
    )

    order = models.PositiveIntegerField(default=1)

    default_value = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("party", "variable_name")

    def __str__(self):
        return f"{self.party.title} — {self.label}"
