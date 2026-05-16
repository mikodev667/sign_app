from django.db import models


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

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="signers"
    )

    full_name = models.CharField(max_length=255)
    iin = models.CharField(max_length=12, db_index=True)
    phone = models.CharField(max_length=30)

    signing_order = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    signed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Signer"
        verbose_name_plural = "Signers"
        ordering = ["signing_order", "created_at"]

    def __str__(self):
        return f"{self.full_name} ({self.iin})"


class SignerAccessToken(models.Model):
    signer = models.ForeignKey(
        Signer,
        on_delete=models.CASCADE,
        related_name="access_tokens"
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


class SigningSession(models.Model):
    class Provider(models.TextChoices):
        EGOV_MOBILE = "egov_mobile", "eGov Mobile"
        MOCK = "mock", "Mock"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        WAITING = "waiting", "Waiting"
        SIGNED = "signed", "Signed"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        CANCELED = "canceled", "Canceled"

    signer = models.ForeignKey(
        Signer,
        on_delete=models.CASCADE,
        related_name="signing_sessions"
    )

    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
        default=Provider.MOCK
    )

    provider_session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.CREATED
    )

    deep_link = models.TextField(blank=True)
    qr_payload = models.TextField(blank=True)

    document_hash = models.CharField(max_length=64, db_index=True)

    expires_at = models.DateTimeField(blank=True, null=True)

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


class Signature(models.Model):
    signer = models.OneToOneField(
        Signer,
        on_delete=models.CASCADE,
        related_name="signature"
    )

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="signatures"
    )

    signing_session = models.OneToOneField(
        SigningSession,
        on_delete=models.PROTECT,
        related_name="signature"
    )

    provider = models.CharField(max_length=50)

    certificate_iin = models.CharField(max_length=12, db_index=True)
    certificate_subject = models.TextField(blank=True)
    certificate_serial = models.CharField(max_length=255, blank=True)

    signature_value = models.TextField(blank=True)

    signed_content_hash = models.CharField(max_length=64, db_index=True)

    signed_at = models.DateTimeField()

    is_valid = models.BooleanField(default=False)
    validation_error = models.CharField(max_length=255, blank=True)

    raw_payload = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signature"
        verbose_name_plural = "Signatures"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Signature for {self.signer}"