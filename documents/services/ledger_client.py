from pathlib import Path

import requests
from django.conf import settings


class LedgerError(Exception):
    def __init__(self, message, *, error_code="", status_code=None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class LedgerConfigurationError(LedgerError):
    pass


class LedgerClient:
    DOCUMENTS_PATH = "/documents"
    VERIFY_PATH = "/ledger/verify"

    @classmethod
    def submit_document(
        cls,
        *,
        filename,
        content,
        content_type,
        actor,
        external_id,
        metadata_json,
    ) -> dict:
        cls.ensure_enabled()

        try:
            response = requests.post(
                cls.endpoint(cls.DOCUMENTS_PATH),
                headers=cls.headers(),
                verify=settings.LEDGER_CA_CERT_FILE,
                cert=(
                    settings.LEDGER_CLIENT_CERT_FILE,
                    settings.LEDGER_CLIENT_KEY_FILE,
                ),
                files={
                    "file": (
                        filename,
                        content,
                        content_type,
                    )
                },
                data={
                    "actor": actor,
                    "external_id": external_id,
                    "metadata_json": metadata_json,
                },
                timeout=settings.LEDGER_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise LedgerError(
                f"Could not connect to ledger: {exc}",
                error_code="request_failed",
            ) from exc

        return cls.parse_response(response)

    @classmethod
    def verify(cls, *, deep=True) -> dict:
        cls.ensure_enabled()

        try:
            response = requests.get(
                cls.endpoint(cls.VERIFY_PATH),
                params={"deep": "true" if deep else "false"},
                headers=cls.headers(),
                verify=settings.LEDGER_CA_CERT_FILE,
                cert=(
                    settings.LEDGER_CLIENT_CERT_FILE,
                    settings.LEDGER_CLIENT_KEY_FILE,
                ),
                timeout=settings.LEDGER_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise LedgerError(
                f"Could not connect to ledger: {exc}",
                error_code="request_failed",
            ) from exc

        return cls.parse_response(response)

    @classmethod
    def headers(cls):
        return {"X-API-Key": cls.api_key()}

    @classmethod
    def api_key(cls):
        try:
            return Path(settings.LEDGER_API_KEY_FILE).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LedgerConfigurationError(
                f"Ledger API key file is not available: {settings.LEDGER_API_KEY_FILE}",
                error_code="missing_api_key_file",
            ) from exc

    @staticmethod
    def ensure_enabled():
        if not settings.LEDGER_ENABLED:
            raise LedgerConfigurationError(
                "Ledger integration is disabled.",
                error_code="ledger_disabled",
            )

    @staticmethod
    def endpoint(path):
        return f"{settings.LEDGER_API_URL.rstrip('/')}{path}"

    @staticmethod
    def parse_response(response):
        try:
            payload = response.json()
        except ValueError as exc:
            raise LedgerError(
                "Ledger returned a non-JSON response.",
                error_code="invalid_json",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400:
            raise LedgerError(
                payload.get("error") or payload.get("detail") or "Ledger request failed.",
                error_code=payload.get("error_code", "ledger_error"),
                status_code=response.status_code,
            )

        return payload
