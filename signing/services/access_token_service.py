import hashlib
import secrets
from dataclasses import dataclass

from django.utils import timezone
from datetime import timedelta

from signing.models import SignerAccessToken


@dataclass
class CreatedAccessToken:
    raw_token: str
    access_token: SignerAccessToken


class SignerAccessTokenService:
    TOKEN_TTL_DAYS = 3

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def create_token(cls, *, signer) -> CreatedAccessToken:
        raw_token = secrets.token_urlsafe(32)
        token_hash = cls.hash_token(raw_token)

        access_token = SignerAccessToken.objects.create(
            signer=signer,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(days=cls.TOKEN_TTL_DAYS),
            is_active=True,
        )

        return CreatedAccessToken(
            raw_token=raw_token,
            access_token=access_token,
        )

    @classmethod
    def get_valid_token(cls, *, raw_token: str):
        token_hash = cls.hash_token(raw_token)

        return (
            SignerAccessToken.objects
            .select_related("signer", "signer__document", "signer__document__organization")
            .filter(
                token_hash=token_hash,
                is_active=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )