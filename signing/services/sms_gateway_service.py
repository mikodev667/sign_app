import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SmsGatewayError(Exception):
    pass


class SmsGatewayService:
    @classmethod
    def send_sms(cls, *, phone: str, text: str) -> dict:
        backend = getattr(settings, "SMS_BACKEND", "console")

        if backend == "console":
            return cls._send_console(phone=phone, text=text)

        if backend == "mobizon":
            return cls._send_mobizon(phone=phone, text=text)

        raise SmsGatewayError(f"Unsupported SMS backend: {backend}")

    @classmethod
    def _send_console(cls, *, phone: str, text: str) -> dict:
        logger.warning("SMS console backend: phone=%s text=%s", phone, text)

        print("\n========== SMS CONSOLE BACKEND ==========")
        print(f"TO: {phone}")
        print(f"TEXT: {text}")
        print("=========================================\n")

        return {
            "ok": True,
            "backend": "console",
            "phone": phone,
            "text": text,
        }

    @classmethod
    def _normalize_phone(cls, phone: str) -> str:
        cleaned = re.sub(r"\D", "", phone or "")

        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "7" + cleaned[1:]

        return cleaned

    @classmethod
    def _send_mobizon(cls, *, phone: str, text: str) -> dict:
        api_url = getattr(
            settings,
            "MOBIZON_API_URL",
            "https://api.mobizon.kz/service",
        )
        api_key = getattr(settings, "MOBIZON_API_KEY", "")
        sender = getattr(settings, "MOBIZON_SENDER", "")
        timeout = getattr(settings, "SMS_TIMEOUT_SECONDS", 10)

        if not api_key:
            raise SmsGatewayError("MOBIZON_API_KEY is not configured.")

        recipient = cls._normalize_phone(phone)

        if not recipient:
            raise SmsGatewayError("Recipient phone is empty.")

        endpoint = f"{api_url.rstrip('/')}/message/sendsmsmessage"

        payload = {
            "apiKey": api_key,
            "recipient": recipient,
            "text": text,
            "output": "json",
        }

        if sender:
            payload["from"] = sender

        try:
            response = requests.post(
                endpoint,
                data=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise SmsGatewayError(f"Mobizon request failed: {exc}") from exc

        try:
            response_data = response.json()
        except ValueError as exc:
            raise SmsGatewayError(
                f"Mobizon returned non-JSON response: {response.text}"
            ) from exc

        if response.status_code >= 400:
            raise SmsGatewayError(
                f"Mobizon HTTP {response.status_code}: {response_data}"
            )

        if response_data.get("code") != 0:
            raise SmsGatewayError(f"Mobizon rejected SMS: {response_data}")

        return {
            "ok": True,
            "backend": "mobizon",
            "recipient": recipient,
            "provider_response": response_data,
        }