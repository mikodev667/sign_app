import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AdmissionApiClient(models.Model):
    name = models.CharField(max_length=255)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Admission API client")
        verbose_name_plural = _("Admission API clients")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def is_valid(self):
        if not self.is_active:
            return False

        return not self.expires_at or self.expires_at > timezone.now()

    @staticmethod
    def generate_raw_token():
        return f"qlq_adm_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class AdmissionViceRectorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admission_vice_rector_profile",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="admission_vice_rectors",
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        related_name="admission_vice_rectors",
        blank=True,
        null=True,
    )
    full_name = models.CharField(max_length=255)
    iin = models.CharField(max_length=12)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Admission vice rector profile")
        verbose_name_plural = _("Admission vice rector profiles")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def clean(self):
        super().clean()

        if (
            self.department_id
            and self.organization_id
            and self.department.organization_id != self.organization_id
        ):
            raise ValidationError({
                "department": _("Department must belong to the selected organization."),
            })


class AdmissionCommissionProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admission_commission_profile",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="admission_commission_members",
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        related_name="admission_commission_members",
        blank=True,
        null=True,
    )
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Admission commission profile")
        verbose_name_plural = _("Admission commission profiles")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def clean(self):
        super().clean()

        if (
            self.department_id
            and self.organization_id
            and self.department.organization_id != self.organization_id
        ):
            raise ValidationError({
                "department": _("Department must belong to the selected organization."),
            })


class AdmissionTemplateRule(models.Model):
    class EducationLevel(models.TextChoices):
        ANY = "any", _("Any")
        BACHELOR = "bachelor", _("Bachelor")
        MASTER = "master", _("Master")
        DOCTORAL = "doctoral", _("Doctoral")
        OTHER = "other", _("Other")

    class FundingType(models.TextChoices):
        PAID = "paid", _("Paid")
        GRANT = "grant", _("Grant")
        OTHER = "other", _("Other")

    class Language(models.TextChoices):
        RU = "ru", _("Russian")
        KK = "kk", _("Kazakh")
        EN = "en", _("English")
        ANY = "any", _("Any")

    title = models.CharField(max_length=255)
    education_level = models.CharField(
        max_length=30,
        choices=EducationLevel.choices,
        default=EducationLevel.BACHELOR,
        db_index=True,
    )
    funding_type = models.CharField(
        max_length=30,
        choices=FundingType.choices,
        default=FundingType.PAID,
        db_index=True,
    )
    language = models.CharField(
        max_length=10,
        choices=Language.choices,
        default=Language.ANY,
        db_index=True,
    )
    program_code = models.CharField(max_length=100, blank=True, db_index=True)
    template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.PROTECT,
        related_name="admission_template_rules",
    )
    application_template = models.ForeignKey(
        "documents.DocumentTemplate",
        on_delete=models.PROTECT,
        related_name="admission_application_template_rules",
        blank=True,
        null=True,
    )
    vice_rector = models.ForeignKey(
        AdmissionViceRectorProfile,
        on_delete=models.PROTECT,
        related_name="template_rules",
        blank=True,
        null=True,
    )
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Admission template rule")
        verbose_name_plural = _("Admission template rules")
        ordering = ["priority", "id"]

    def __str__(self):
        return self.title

    def matches(self, *, education_level, funding_type, language, program_code=""):
        if self.education_level not in {self.EducationLevel.ANY, education_level}:
            return False

        if self.funding_type != funding_type:
            return False

        if self.language not in {self.Language.ANY, language}:
            return False

        return not self.program_code or self.program_code == (program_code or "")


class AdmissionContract(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", _("Received")
        DOCUMENT_CREATED = "document_created", _("Document created")
        STUDENT_SIGNING = "student_signing", _("Waiting for student signature")
        STUDENT_SIGNED = "student_signed", _("Student signed")
        VICE_RECTOR_PENDING = "vice_rector_pending", _("Waiting for vice rector")
        VICE_RECTOR_SIGNED = "vice_rector_signed", _("Vice rector signed")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    api_client = models.ForeignKey(
        AdmissionApiClient,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    template_rule = models.ForeignKey(
        AdmissionTemplateRule,
        on_delete=models.PROTECT,
        related_name="contracts",
        blank=True,
        null=True,
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="admission_contracts",
        blank=True,
        null=True,
    )
    application_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="admission_applications",
        blank=True,
        null=True,
    )
    student_signer = models.ForeignKey(
        "signing.Signer",
        on_delete=models.SET_NULL,
        related_name="student_admission_contracts",
        blank=True,
        null=True,
    )
    vice_rector_signer = models.ForeignKey(
        "signing.Signer",
        on_delete=models.SET_NULL,
        related_name="vice_rector_admission_contracts",
        blank=True,
        null=True,
    )
    external_id = models.CharField(max_length=255, unique=True, db_index=True)
    access_token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    public_url = models.TextField(blank=True)
    protected_access_token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        blank=True,
        null=True,
    )
    protected_url = models.TextField(blank=True)

    education_level = models.CharField(
        max_length=30,
        choices=AdmissionTemplateRule.EducationLevel.choices,
        default=AdmissionTemplateRule.EducationLevel.BACHELOR,
        db_index=True,
    )
    funding_type = models.CharField(
        max_length=30,
        choices=AdmissionTemplateRule.FundingType.choices,
        default=AdmissionTemplateRule.FundingType.PAID,
        db_index=True,
    )
    language = models.CharField(
        max_length=10,
        choices=AdmissionTemplateRule.Language.choices,
        default=AdmissionTemplateRule.Language.RU,
        db_index=True,
    )
    program_code = models.CharField(max_length=100, blank=True, db_index=True)
    program_name_ru = models.CharField(max_length=255, blank=True)
    program_name_kk = models.CharField(max_length=255, blank=True)

    applicant_full_name = models.CharField(max_length=255)
    applicant_iin = models.CharField(max_length=12, db_index=True)
    applicant_phone = models.CharField(max_length=30, blank=True)
    applicant_email = models.EmailField(blank=True)
    tuition_amount = models.PositiveBigIntegerField(blank=True, null=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=40,
        choices=Status.choices,
        default=Status.RECEIVED,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Admission contract")
        verbose_name_plural = _("Admission contracts")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.external_id} - {self.applicant_full_name}"

    @staticmethod
    def generate_raw_access_token():
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_access_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def default_expires_at(cls):
        return timezone.now() + timedelta(days=30)

    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def refresh_status_from_signers(self, save=True):
        if self.status == self.Status.FAILED:
            return self

        student_signed = bool(self.student_signer and self.student_signer.is_signed())
        vice_rector_signed = bool(
            self.vice_rector_signer and self.vice_rector_signer.is_signed()
        )

        if student_signed and (vice_rector_signed or not self.vice_rector_signer_id):
            self.status = self.Status.COMPLETED
        elif vice_rector_signed:
            self.status = self.Status.VICE_RECTOR_SIGNED
        elif student_signed:
            self.status = self.Status.VICE_RECTOR_PENDING
        elif self.student_signer_id:
            self.status = self.Status.STUDENT_SIGNING
        elif self.document_id:
            self.status = self.Status.DOCUMENT_CREATED

        if save:
            self.save(update_fields=["status", "updated_at"])

        return self


class AdmissionRenderJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        PROCESSING = "processing", _("Processing")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    contract = models.OneToOneField(
        AdmissionContract,
        on_delete=models.CASCADE,
        related_name="render_job",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(blank=True, null=True, db_index=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Admission render job")
        verbose_name_plural = _("Admission render jobs")
        ordering = ["next_attempt_at", "created_at"]

    def __str__(self):
        return f"{self.contract.external_id} - {self.status}"

    def can_retry(self):
        return self.attempts < self.max_attempts


class AdmissionMssqlContractRecord(models.Model):
    external_id = models.CharField(max_length=255, unique=True, db_index=True)

    admission_contract_id = models.PositiveBigIntegerField(blank=True, null=True, db_index=True)
    document_id = models.PositiveBigIntegerField(blank=True, null=True, db_index=True)
    application_document_id = models.PositiveBigIntegerField(blank=True, null=True, db_index=True)
    student_signer_id = models.PositiveBigIntegerField(blank=True, null=True)
    vice_rector_signer_id = models.PositiveBigIntegerField(blank=True, null=True)
    api_client_id = models.PositiveBigIntegerField(blank=True, null=True)
    api_client_name = models.CharField(max_length=255, blank=True)
    template_rule_id = models.PositiveBigIntegerField(blank=True, null=True)

    education_level = models.CharField(max_length=30, blank=True, db_index=True)
    funding_type = models.CharField(max_length=30, blank=True, db_index=True)
    language = models.CharField(max_length=10, blank=True, db_index=True)
    program_code = models.CharField(max_length=100, blank=True, db_index=True)
    program_name_ru = models.CharField(max_length=255, blank=True)
    program_name_kk = models.CharField(max_length=255, blank=True)

    applicant_full_name = models.CharField(max_length=255, blank=True)
    applicant_iin = models.CharField(max_length=12, blank=True, db_index=True)
    applicant_phone = models.CharField(max_length=30, blank=True)
    applicant_email = models.EmailField(blank=True)
    tuition_amount = models.PositiveBigIntegerField(blank=True, null=True)

    status = models.CharField(max_length=40, blank=True, db_index=True)
    public_url = models.TextField(blank=True)
    raw_payload_json = models.TextField(blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        verbose_name = _("Admission MSSQL contract record")
        verbose_name_plural = _("Admission MSSQL contract records")
        db_table = "admission_contract_records"
        ordering = ["-synced_at"]

    def __str__(self):
        return f"{self.external_id} - {self.applicant_full_name}"
