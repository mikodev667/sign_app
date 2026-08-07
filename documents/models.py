import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils.translation import gettext_lazy as _
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

    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        related_name="document_templates",
        blank=True,
        null=True,
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

    def __str__(self):
        return self.title


class Document(models.Model):
    SYSTEM_CONTRACT_NUMBER = "contract_number"
    SYSTEM_CONTRACT_DATE = "contract_date"
    SYSTEM_CONTRACT_DATE_TEXT_RU = "contract_date_text_ru"
    SYSTEM_CONTRACT_DATE_TEXT_KK = "contract_date_text_kk"
    SYSTEM_DATE = "date"
    SYSTEM_CONTRACT_YEAR = "contract_year"

    SYSTEM_UNIVERSITY_NAME_RU = "university_name_ru"
    SYSTEM_UNIVERSITY_NAME_KK = "university_name_kk"
    SYSTEM_UNIVERSITY_SHORT_NAME_RU = "university_short_name_ru"
    SYSTEM_UNIVERSITY_SHORT_NAME_KK = "university_short_name_kk"
    SYSTEM_UNIVERSITY_BIN = "university_bin"
    SYSTEM_UNIVERSITY_LICENSE_NUMBER = "university_license_number"
    SYSTEM_UNIVERSITY_LICENSE_DATE_RU = "university_license_date_ru"
    SYSTEM_UNIVERSITY_LICENSE_DATE_KK = "university_license_date_kk"
    SYSTEM_UNIVERSITY_LICENSE_ISSUER_RU = "university_license_issuer_ru"
    SYSTEM_UNIVERSITY_LICENSE_ISSUER_KK = "university_license_issuer_kk"
    SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_RU = "university_representative_position_ru"
    SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_KK = "university_representative_position_kk"
    SYSTEM_UNIVERSITY_ADDRESS_RU = "university_address_ru"
    SYSTEM_UNIVERSITY_ADDRESS_KK = "university_address_kk"
    SYSTEM_UNIVERSITY_BANK_NAME_RU = "university_bank_name_ru"
    SYSTEM_UNIVERSITY_BANK_NAME_KK = "university_bank_name_kk"
    SYSTEM_UNIVERSITY_ACCOUNT = "university_account"
    SYSTEM_UNIVERSITY_BIC = "university_bic"
    SYSTEM_UNIVERSITY_KBE = "university_kbe"

    CONTRACT_SYSTEM_FIELD_NAMES = (
        SYSTEM_CONTRACT_NUMBER,
        SYSTEM_CONTRACT_DATE,
        SYSTEM_CONTRACT_DATE_TEXT_RU,
        SYSTEM_CONTRACT_DATE_TEXT_KK,
        SYSTEM_DATE,
        SYSTEM_CONTRACT_YEAR,
    )

    UNIVERSITY_SYSTEM_FIELD_NAMES = (
        SYSTEM_UNIVERSITY_NAME_RU,
        SYSTEM_UNIVERSITY_NAME_KK,
        SYSTEM_UNIVERSITY_SHORT_NAME_RU,
        SYSTEM_UNIVERSITY_SHORT_NAME_KK,
        SYSTEM_UNIVERSITY_BIN,
        SYSTEM_UNIVERSITY_LICENSE_NUMBER,
        SYSTEM_UNIVERSITY_LICENSE_DATE_RU,
        SYSTEM_UNIVERSITY_LICENSE_DATE_KK,
        SYSTEM_UNIVERSITY_LICENSE_ISSUER_RU,
        SYSTEM_UNIVERSITY_LICENSE_ISSUER_KK,
        SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_RU,
        SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_KK,
        SYSTEM_UNIVERSITY_ADDRESS_RU,
        SYSTEM_UNIVERSITY_ADDRESS_KK,
        SYSTEM_UNIVERSITY_BANK_NAME_RU,
        SYSTEM_UNIVERSITY_BANK_NAME_KK,
        SYSTEM_UNIVERSITY_ACCOUNT,
        SYSTEM_UNIVERSITY_BIC,
        SYSTEM_UNIVERSITY_KBE,
    )

    SYSTEM_FIELD_NAMES = CONTRACT_SYSTEM_FIELD_NAMES + UNIVERSITY_SYSTEM_FIELD_NAMES

    CONTRACT_SYSTEM_FIELD_LIBRARY = (
        {
            "label": _("Contract number"),
            "variable_name": SYSTEM_CONTRACT_NUMBER,
        },
        {
            "label": _("Contract date"),
            "variable_name": SYSTEM_CONTRACT_DATE,
        },
        {
            "label": _("Contract date text (RU)"),
            "variable_name": SYSTEM_CONTRACT_DATE_TEXT_RU,
        },
        {
            "label": _("Contract date text (KZ)"),
            "variable_name": SYSTEM_CONTRACT_DATE_TEXT_KK,
        },
        {
            "label": _("Date"),
            "variable_name": SYSTEM_DATE,
        },
        {
            "label": _("Contract year"),
            "variable_name": SYSTEM_CONTRACT_YEAR,
        },
    )
    UNIVERSITY_SYSTEM_FIELD_LIBRARY = (
        {
            "label": _("University name (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_NAME_RU,
        },
        {
            "label": _("University name (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_NAME_KK,
        },
        {
            "label": _("University short name (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_SHORT_NAME_RU,
        },
        {
            "label": _("University short name (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_SHORT_NAME_KK,
        },
        {
            "label": _("University BIN"),
            "variable_name": SYSTEM_UNIVERSITY_BIN,
        },
        {
            "label": _("University license number"),
            "variable_name": SYSTEM_UNIVERSITY_LICENSE_NUMBER,
        },
        {
            "label": _("University license date (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_LICENSE_DATE_RU,
        },
        {
            "label": _("University license date (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_LICENSE_DATE_KK,
        },
        {
            "label": _("University license issuer (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_LICENSE_ISSUER_RU,
        },
        {
            "label": _("University license issuer (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_LICENSE_ISSUER_KK,
        },
        {
            "label": _("University representative position (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_RU,
        },
        {
            "label": _("University representative position (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_KK,
        },
        {
            "label": _("University address (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_ADDRESS_RU,
        },
        {
            "label": _("University address (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_ADDRESS_KK,
        },
        {
            "label": _("University bank name (RU)"),
            "variable_name": SYSTEM_UNIVERSITY_BANK_NAME_RU,
        },
        {
            "label": _("University bank name (KZ)"),
            "variable_name": SYSTEM_UNIVERSITY_BANK_NAME_KK,
        },
        {
            "label": _("University account"),
            "variable_name": SYSTEM_UNIVERSITY_ACCOUNT,
        },
        {
            "label": _("University BIC"),
            "variable_name": SYSTEM_UNIVERSITY_BIC,
        },
        {
            "label": _("University KBE"),
            "variable_name": SYSTEM_UNIVERSITY_KBE,
        },
    )
    SYSTEM_FIELD_LIBRARY = CONTRACT_SYSTEM_FIELD_LIBRARY + UNIVERSITY_SYSTEM_FIELD_LIBRARY
    SYSTEM_FIELD_GROUPS = (
        {
            "title": _("Document"),
            "fields": CONTRACT_SYSTEM_FIELD_LIBRARY,
        },
        {
            "title": _("University"),
            "fields": UNIVERSITY_SYSTEM_FIELD_LIBRARY,
        },
    )
    UNIVERSITY_SYSTEM_FIELD_DEFAULTS = {
        SYSTEM_UNIVERSITY_NAME_RU: (
            "Некоммерческое акционерное общество "
            "«Казахский национальный университет имени аль-Фараби»"
        ),
        SYSTEM_UNIVERSITY_NAME_KK: (
            "«Әл-Фараби атындағы Қазақ ұлттық университеті» "
            "коммерциялық емес акционерлік қоғамы"
        ),
        SYSTEM_UNIVERSITY_SHORT_NAME_RU: (
            "НАО «Казахский национальный университет имени аль-Фараби»"
        ),
        SYSTEM_UNIVERSITY_SHORT_NAME_KK: "«Әл-Фараби атындағы Қазақ ұлттық университеті» КеАҚ",
        SYSTEM_UNIVERSITY_BIN: "990140001154",
        SYSTEM_UNIVERSITY_LICENSE_NUMBER: "KZ89LAM00001798",
        SYSTEM_UNIVERSITY_LICENSE_DATE_RU: "17 апреля 2025 года",
        SYSTEM_UNIVERSITY_LICENSE_DATE_KK: "2025 жылғы 17 сәуір",
        SYSTEM_UNIVERSITY_LICENSE_ISSUER_RU: (
            "Республиканским государственным учреждением «Комитет по обеспечению "
            "качества в сфере образования и науки Министерства образования и науки "
            "Республики Казахстан»"
        ),
        SYSTEM_UNIVERSITY_LICENSE_ISSUER_KK: (
            "«Қазақстан Республикасы Білім және ғылым министрлігінің білім және ғылым "
            "саласындағы сапаны қамтамасыз ету комитеті» республикалық мемлекеттік мекемесі"
        ),
        SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_RU: (
            "Член Правления - проректор по академическим вопросам"
        ),
        SYSTEM_UNIVERSITY_REPRESENTATIVE_POSITION_KK: (
            "Академиялық мәселелер бойынша Басқарма мүшесі - проректор"
        ),
        SYSTEM_UNIVERSITY_ADDRESS_RU: "0500040, г. Алматы, пр. аль-Фараби, 71",
        SYSTEM_UNIVERSITY_ADDRESS_KK: "0500040, Алматы қ-сы, әл-Фараби даңғылы, 71",
        SYSTEM_UNIVERSITY_BANK_NAME_RU: "АО «Народный Банк Казахстана», г. Алматы",
        SYSTEM_UNIVERSITY_BANK_NAME_KK: "«Қазақстан Халық Банкі» АҚ, Алматы қ.",
        SYSTEM_UNIVERSITY_ACCOUNT: "KZ156010131000194743",
        SYSTEM_UNIVERSITY_BIC: "HSBKKZKX",
        SYSTEM_UNIVERSITY_KBE: "16",
    }

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

    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        related_name="documents",
        blank=True,
        null=True,
    )

    template = models.ForeignKey(
        DocumentTemplate,
        on_delete=models.PROTECT,
        related_name="documents",
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_documents",
    )

    title = models.CharField(max_length=255)

    contract_number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique contract number generated when the document is created.",
    )

    contract_date = models.DateField(
        blank=True,
        null=True,
        db_index=True,
        help_text="Contract composition date generated when the document is created.",
    )

    verification_token = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        help_text="Public token for document verification page.",
    )

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

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        adding = self._state.adding
        requested_status = self.status

        if not self.contract_date:
            self.contract_date = timezone.localdate()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"contract_date"}

        if not self.verification_token:
            self.verification_token = self.generate_verification_token()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"verification_token"}

        if adding and requested_status == self.Status.SIGNED and not self.contract_number:
            self.status = self.Status.DRAFT

        if self.pk and not getattr(self, "_allow_final_document_update", False):
            old_status = (
                Document.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            if old_status == self.Status.SIGNED:
                raise ValidationError(_("Signed document is immutable and cannot be updated."))

        super().save(*args, **kwargs)

        if (
            not self.contract_number
            and not getattr(self, "_skip_contract_number_generation", False)
        ):
            self.assign_generated_contract_number(
                adding=adding,
                requested_status=requested_status,
            )

    def delete(self, *args, **kwargs):
        if self.status == self.Status.SIGNED:
            raise ValidationError(_("Signed document is immutable and cannot be deleted."))

        return super().delete(*args, **kwargs)

    def is_locked(self):
        """
        Документ нельзя редактировать, если он уже заблокирован
        или вышел из статуса draft.
        """
        if self.status in {self.Status.PARTIALLY_SIGNED, self.Status.SIGNED}:
            return True

        if self.signed_at:
            return True

        if not self.pk:
            return False

        return self.signers.filter(status="signed").exists()

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

    def generate_contract_number(self):
        if not self.pk:
            return ""

        return str(self.pk)

    def assign_generated_contract_number(self, *, adding=False, requested_status=None):
        if not self.pk:
            return

        last_error = None
        for offset in range(1000):
            contract_number = str(self.pk + offset)
            update_values = {"contract_number": contract_number}

            if adding and requested_status == self.Status.SIGNED:
                update_values["status"] = requested_status

            try:
                with transaction.atomic():
                    Document.objects.filter(pk=self.pk).update(**update_values)
            except IntegrityError as exc:
                last_error = exc
                continue

            self.contract_number = contract_number
            if adding and requested_status == self.Status.SIGNED:
                self.status = requested_status
            return

        if last_error:
            raise last_error

    @classmethod
    def generate_verification_token(cls):
        while True:
            token = secrets.token_urlsafe(24)

            if not cls.objects.filter(verification_token=token).exists():
                return token

    def get_contract_date_display(self):
        contract_date = self.contract_date or timezone.localdate()
        return contract_date.strftime("%d.%m.%Y")

    def get_contract_date_text_ru(self):
        contract_date = self.contract_date or timezone.localdate()
        month_names = {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря",
        }
        return f"«{contract_date.day:02d}» {month_names[contract_date.month]} {contract_date.year} г."

    def get_contract_date_text_kk(self):
        contract_date = self.contract_date or timezone.localdate()
        month_names = {
            1: "қаңтар",
            2: "ақпан",
            3: "наурыз",
            4: "сәуір",
            5: "мамыр",
            6: "маусым",
            7: "шілде",
            8: "тамыз",
            9: "қыркүйек",
            10: "қазан",
            11: "қараша",
            12: "желтоқсан",
        }
        return f"«{contract_date.day:02d}» {month_names[contract_date.month]} {contract_date.year} ж."

    def get_contract_system_values(self):
        contract_date = self.contract_date or timezone.localdate()
        values = {
            self.SYSTEM_CONTRACT_NUMBER: self.contract_number or self.generate_contract_number(),
            self.SYSTEM_CONTRACT_DATE: contract_date.strftime("%d.%m.%Y"),
            self.SYSTEM_CONTRACT_DATE_TEXT_RU: self.get_contract_date_text_ru(),
            self.SYSTEM_CONTRACT_DATE_TEXT_KK: self.get_contract_date_text_kk(),
            self.SYSTEM_DATE: contract_date.strftime("%d.%m.%Y"),
            self.SYSTEM_CONTRACT_YEAR: str(contract_date.year),
        }
        values.update(self.UNIVERSITY_SYSTEM_FIELD_DEFAULTS)
        return values


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
        verbose_name = _("LawVision report")
        verbose_name_plural = _("LawVision reports")
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


class DocumentLedgerRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        FAILED = "failed", "Failed"

    class VerificationStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="ledger_records",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ledger_records",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    actor = models.CharField(max_length=100, default="sign_app")
    external_id = models.CharField(max_length=100, unique=True, db_index=True)
    source_filename = models.CharField(max_length=255, blank=True)
    ledger_pdf_object = models.ForeignKey(
        "documents.StoredObject",
        on_delete=models.SET_NULL,
        related_name="ledger_records",
        blank=True,
        null=True,
    )

    ledger_id = models.CharField(max_length=100, blank=True, db_index=True)
    document_token = models.CharField(max_length=255, blank=True, db_index=True)
    document_hash = models.CharField(max_length=64, blank=True, db_index=True)
    size_bytes = models.PositiveBigIntegerField(blank=True, null=True)

    sequence = models.PositiveBigIntegerField(blank=True, null=True, db_index=True)
    entry_hash = models.CharField(max_length=128, blank=True, db_index=True)
    previous_hash = models.CharField(max_length=128, blank=True)
    server_signature_b64 = models.TextField(blank=True)
    server_key_id = models.CharField(max_length=255, blank=True)
    ledger_created_at = models.DateTimeField(blank=True, null=True)

    request_metadata = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)

    last_verified_at = models.DateTimeField(blank=True, null=True)
    last_verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        blank=True,
        db_index=True,
    )
    last_verification_result = models.JSONField(default=dict, blank=True)
    last_verification_error = models.TextField(blank=True)

    submitted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Document ledger record")
        verbose_name_plural = _("Document ledger records")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ledger record for {self.document_id} ({self.status})"

    def is_successful(self):
        return self.status == self.Status.SUBMITTED


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
        MONEY = "money", "Money amount"

    class SystemField(models.TextChoices):
        FULL_NAME = "full_name", "Full name"
        IIN_BIN = "iin_bin", "IIN / BIN"
        PHONE = "phone", "Phone"
        EMAIL = "email", "Email"
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
    @property
    def display_label(self):
        if not self.is_system:
            return self.label

        system_labels = {
            self.SystemField.FULL_NAME: _("Full name"),
            self.SystemField.IIN_BIN: _("IIN / BIN"),
            self.SystemField.PHONE: _("Phone"),
            self.SystemField.EMAIL: _("Email"),
            self.SystemField.SIGNING_METHOD: _("Signing method"),
        }

        return system_labels.get(self.variable_name, self.label)


class StoredObject(models.Model):
    class ObjectType(models.TextChoices):
        FINAL_PDF = "final_pdf", _("Final PDF")
        FINAL_DOCX = "final_docx", _("Final DOCX")
        LEDGER_PDF = "ledger_pdf", _("Ledger PDF")
        SIGNATURE = "signature", _("Signature")
        EVIDENCE_BUNDLE = "evidence_bundle", _("Evidence bundle")
        OTHER = "other", _("Other")

    class RetentionMode(models.TextChoices):
        COMPLIANCE = "COMPLIANCE", _("Compliance")
        GOVERNANCE = "GOVERNANCE", _("Governance")
        NONE = "NONE", _("None")

    class StorageStatus(models.TextChoices):
        STORED = "stored", _("Stored")
        FAILED = "failed", _("Failed")

    document = models.ForeignKey(
        Document,
        on_delete=models.PROTECT,
        related_name="stored_objects",
    )

    object_type = models.CharField(
        max_length=30,
        choices=ObjectType.choices,
        default=ObjectType.OTHER,
        db_index=True,
    )

    bucket = models.CharField(max_length=255)
    object_key = models.CharField(max_length=1024)
    version_id = models.CharField(max_length=255, blank=True)
    etag = models.CharField(max_length=255, blank=True)

    sha256 = models.CharField(max_length=64, db_index=True)
    content_type = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)

    retention_mode = models.CharField(
        max_length=20,
        choices=RetentionMode.choices,
        default=RetentionMode.COMPLIANCE,
    )
    retention_until = models.DateTimeField(blank=True, null=True)

    storage_status = models.CharField(
        max_length=20,
        choices=StorageStatus.choices,
        default=StorageStatus.STORED,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="stored_objects",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("Stored object")
        verbose_name_plural = _("Stored objects")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="stored_object_sha256_hex",
            ),
            models.UniqueConstraint(
                fields=["bucket", "object_key", "version_id"],
                name="uniq_stored_object_version",
            ),
        ]

    def __str__(self):
        return f"{self.object_type} {self.object_key}"
