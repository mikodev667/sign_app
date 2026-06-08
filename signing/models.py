import hashlib
import secrets

from django.db import models
from django.utils import timezone


class Signer(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SMS_SENT = "sms_sent", "SMS sent"
        OPENED = "opened", "Opened"
        SIGNING_STARTED = "signing_started", "Signing started"
        SIGNED = "signed", "Signed"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    class SigningMethod(models.TextChoices):
        EGOV_MOBILE = "egov_mobile", "eGov Mobile"
        SMS = "sms", "SMS confirmation"
        ECP = "ecp", "ЭЦП"

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="signers",
    )

    full_name = models.CharField(max_length=255)
    iin = models.CharField(max_length=12, db_index=True)
    phone = models.CharField(max_length=30)

    signing_order = models.PositiveIntegerField(default=1)

    signing_method = models.CharField(
        max_length=32,
        choices=SigningMethod.choices,
        default=SigningMethod.EGOV_MOBILE,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    signed_at = models.DateTimeField(blank=True, null=True)

    template_party = models.ForeignKey(
        "documents.TemplateParty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signers",
    )

    role_title = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        verbose_name = "Signer"
        verbose_name_plural = "Signers"
        ordering = ["signing_order", "created_at"]

    def __str__(self):
        return f"{self.full_name} ({self.iin})"

    def is_signed(self):
        return self.status == self.Status.SIGNED

    def can_sign(self):
        return self.status not in [
            self.Status.SIGNED,
            self.Status.REJECTED,
            self.Status.EXPIRED,
        ]

    def mark_opened(self, save=True):
        if self.status in [self.Status.PENDING, self.Status.SMS_SENT]:
            self.status = self.Status.OPENED

            if save:
                self.save(update_fields=["status", "updated_at"])

        return self

    def mark_signing_started(self, save=True):
        if self.can_sign():
            self.status = self.Status.SIGNING_STARTED

            if save:
                self.save(update_fields=["status", "updated_at"])

        return self

    def mark_signed(self, save=True):
        self.status = self.Status.SIGNED
        self.signed_at = timezone.now()

        if save:
            self.save(update_fields=["status", "signed_at", "updated_at"])

        return self


class SignerAccessToken(models.Model):
    signer = models.ForeignKey(
        Signer,
        on_delete=models.CASCADE,
        related_name="access_tokens",
    )

    token_hash = models.CharField(max_length=64, unique=True, db_index=True)

    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signer access token"
        verbose_name_plural = "Signer access tokens"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Token for {self.signer}"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def is_valid(self):
        return self.is_active and not self.is_expired()

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class SigningSession(models.Model):
    class Provider(models.TextChoices):
        EGOV_MOBILE = "egov_mobile", "eGov Mobile"
        MOCK = "mock", "Mock"
        SMS = "sms", "SMS confirmation"
        ECP = "ecp", "ЭЦП"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        WAITING = "waiting", "Waiting"
        CODE_SENT = "code_sent", "Code sent"
        SIGNED = "signed", "Signed"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        CANCELED = "canceled", "Canceled"
        USED = "used", "Used"

    signer = models.ForeignKey(
        Signer,
        on_delete=models.CASCADE,
        related_name="signing_sessions",
    )

    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
        default=Provider.MOCK,
        db_index=True,
    )

    provider_session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )

    deep_link = models.TextField(blank=True)
    qr_payload = models.TextField(blank=True)

    document_hash = models.CharField(max_length=64, db_index=True)

    expires_at = models.DateTimeField(blank=True, null=True)

    # SMS signing fields
    code_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hash of SMS code",
    )

    attempts_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)

    cooldown_until = models.DateTimeField(blank=True, null=True)

    used_at = models.DateTimeField(blank=True, null=True)

    raw_request = models.JSONField(blank=True, null=True)
    raw_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signing session"
        verbose_name_plural = "Signing sessions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} session for {self.signer}"

    def is_sms(self):
        return self.provider == self.Provider.SMS

    def is_expired(self):
        return self.expires_at is not None and timezone.now() > self.expires_at

    def is_in_cooldown(self):
        return self.cooldown_until is not None and timezone.now() < self.cooldown_until

    def attempts_exceeded(self):
        return self.attempts_count >= self.max_attempts

    def set_sms_code(self, raw_code, save=True):
        self.code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()

        if save:
            self.save(update_fields=["code_hash", "updated_at"])

        return self

    def verify_sms_code(self, raw_code):
        raw_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
        return secrets.compare_digest(raw_hash, self.code_hash)

    def mark_code_sent(self, save=True):
        self.status = self.Status.CODE_SENT

        if save:
            self.save(update_fields=["status", "updated_at"])

        return self

    def mark_used(self, save=True):
        self.status = self.Status.USED
        self.used_at = timezone.now()

        if save:
            self.save(update_fields=["status", "used_at", "updated_at"])

        return self

    def mark_signed(self, save=True):
        self.status = self.Status.SIGNED
        self.used_at = timezone.now()

        if save:
            self.save(update_fields=["status", "used_at", "updated_at"])

        return self

    def mark_failed(self, save=True):
        self.status = self.Status.FAILED

        if save:
            self.save(update_fields=["status", "updated_at"])

        return self

    def mark_expired(self, save=True):
        self.status = self.Status.EXPIRED

        if save:
            self.save(update_fields=["status", "updated_at"])

        return self


class Signature(models.Model):
    signer = models.OneToOneField(
        Signer,
        on_delete=models.CASCADE,
        related_name="signature",
    )

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="signatures",
    )

    signing_session = models.OneToOneField(
        SigningSession,
        on_delete=models.PROTECT,
        related_name="signature",
    )

    provider = models.CharField(max_length=50, db_index=True)

    certificate_iin = models.CharField(max_length=12, db_index=True, blank=True)
    certificate_subject = models.TextField(blank=True)
    certificate_serial = models.CharField(max_length=255, blank=True)

    signature_value = models.TextField(blank=True)

    signed_content_hash = models.CharField(max_length=64, db_index=True)

    consent_text = models.TextField(
        blank=True,
        help_text="Text of consent accepted by signer before SMS signing",
    )

    confirmation_text = models.TextField(
        blank=True,
        help_text="Human-readable signing confirmation sheet text",
    )

    signed_at = models.DateTimeField()

    is_valid = models.BooleanField(default=False)
    validation_error = models.CharField(max_length=255, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    raw_payload = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signature"
        verbose_name_plural = "Signatures"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Signature for {self.signer}"


class SigningAuditLog(models.Model):
    class Event(models.TextChoices):
        SIGNER_ADDED = "signer_added", "Signer added"

        DOCUMENT_LOCKED = "document_locked", "Document locked"
        DOCUMENT_HASH_FIXED = "document_hash_fixed", "Document hash fixed"

        ACCESS_LINK_CREATED = "access_link_created", "Access link created"
        INVITATION_SMS_SENT = "invitation_sms_sent", "Invitation SMS sent"

        LINK_OPENED = "link_opened", "Link opened"

        EGOV_SESSION_STARTED = "egov_session_started", "eGov Mobile session started"

        ECP_SIGNING_STARTED = "ecp_signing_started", "ECP signing started"
        ECP_SIGNATURE_RECEIVED = "ecp_signature_received", "ECP signature received"
        ECP_SIGNATURE_VALIDATED = "ecp_signature_validated", "ECP signature validated"
        ECP_SIGNATURE_INVALID = "ecp_signature_invalid", "ECP signature invalid"

        SMS_CONSENT_ACCEPTED = "sms_consent_accepted", "SMS consent accepted"
        SMS_CODE_REQUESTED = "sms_code_requested", "SMS code requested"
        SMS_CODE_SENT = "sms_code_sent", "SMS code sent"
        SMS_CODE_FAILED = "sms_code_failed", "SMS code failed"

        SMS_CODE_INVALID = "sms_code_invalid", "SMS code invalid"
        SMS_CODE_EXPIRED = "sms_code_expired", "SMS code expired"
        SMS_CODE_COOLDOWN = "sms_code_cooldown", "SMS code cooldown"
        SMS_CODE_ATTEMPTS_EXCEEDED = (
            "sms_code_attempts_exceeded",
            "SMS code attempts exceeded",
        )
        SMS_CODE_CONFIRMED = "sms_code_confirmed", "SMS code confirmed"

        SIGNATURE_CREATED = "signature_created", "Signature created"
        DOCUMENT_SIGNED = "document_signed", "Document signed"

        STATUS_RECALCULATED = "status_recalculated", "Status recalculated"

        REPEAT_SIGN_BLOCKED = "repeat_sign_blocked", "Repeat signing blocked"

        SIGNING_FAILED = "signing_failed", "Signing failed"

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="signing_audit_logs",
    )

    signer = models.ForeignKey(
        "signing.Signer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signing_audit_logs",
    )

    signing_session = models.ForeignKey(
        "signing.SigningSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signing_audit_logs",
    )

    event = models.CharField(
        max_length=64,
        choices=Event.choices,
        db_index=True,
    )

    signing_method = models.CharField(
        max_length=32,
        blank=True,
    )

    phone = models.CharField(max_length=32, blank=True)
    iin = models.CharField(max_length=12, blank=True)
    full_name = models.CharField(max_length=255, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    document_hash = models.CharField(max_length=128, blank=True)
    signed_content_hash = models.CharField(max_length=128, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signing audit log"
        verbose_name_plural = "Signing audit logs"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.event} — document={self.document_id} — {self.created_at}"