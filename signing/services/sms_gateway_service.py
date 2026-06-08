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

        phone = cls._normalize_phone(phone)

        if not phone:
            raise SmsGatewayError("Recipient phone is empty.")

        if not cls._is_valid_kz_phone(phone):
            raise SmsGatewayError(f"Invalid Kazakhstan phone number: {phone}")

        if not text or not text.strip():
            raise SmsGatewayError("SMS text is empty.")

        text = text.strip()

        if len(text) > 500:
            raise SmsGatewayError("SMS text is too long.")

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
            "recipient": phone,
            "provider_message_id": None,
            "provider_response": {
                "message": "SMS printed to console.",
                "text": text,
            },
        }

    @classmethod
    def _normalize_phone(cls, phone: str) -> str:
        """
        Приводим номер к формату 7XXXXXXXXXX.

        Примеры:
        +7 777 123 45 67 -> 77771234567
        8 777 123 45 67  -> 77771234567
        77771234567       -> 77771234567
        """

        cleaned = re.sub(r"\D", "", phone or "")

        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "7" + cleaned[1:]

        if cleaned.startswith("7") and len(cleaned) == 11:
            return cleaned

        return cleaned

    @classmethod
    def _is_valid_kz_phone(cls, phone: str) -> bool:
        """
        Базовая проверка для Казахстана:
        номер должен быть 11 цифр и начинаться с 7.
        """

        return bool(re.fullmatch(r"7\d{10}", phone or ""))

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

        endpoint = f"{api_url.rstrip('/')}/message/sendsmsmessage"

        payload = {
            "apiKey": api_key,
            "recipient": phone,
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
            logger.exception("Mobizon request failed.")
            raise SmsGatewayError(f"Mobizon request failed: {exc}") from exc

        try:
            response_data = response.json()
        except ValueError as exc:
            logger.error(
                "Mobizon returned non-JSON response. status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise SmsGatewayError(
                f"Mobizon returned non-JSON response: {response.text}"
            ) from exc

        if response.status_code >= 400:
            logger.error(
                "Mobizon HTTP error. status=%s response=%s",
                response.status_code,
                response_data,
            )
            raise SmsGatewayError(
                f"Mobizon HTTP {response.status_code}: {response_data}"
            )

        if response_data.get("code") != 0:
            logger.error("Mobizon rejected SMS: %s", response_data)
            raise SmsGatewayError(f"Mobizon rejected SMS: {response_data}")

        provider_message_id = None

        data = response_data.get("data")
        if isinstance(data, dict):
            provider_message_id = data.get("messageId") or data.get("id")

        return {
            "ok": True,
            "backend": "mobizon",
            "recipient": phone,
            "provider_message_id": provider_message_id,
            "provider_response": response_data,
        }