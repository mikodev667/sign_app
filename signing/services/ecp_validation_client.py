import json
import urllib.error
import urllib.request

from django.conf import settings


class EcpValidationClient:
    DEFAULT_TIMEOUT_SECONDS = 15

    @classmethod
    def verify(
        cls,
        *,
        cms_signature: str,
        expected_document_hash: str,
        expected_iin: str,
    ) -> dict:
        verifier_url = getattr(
            settings,
            "ECP_VERIFIER_URL",
            "http://127.0.0.1:9001/verify-ecp",
        )

        payload = {
            "cms": cms_signature,
            "expected_document_hash": expected_document_hash,
            "expected_iin": expected_iin,
        }

        request_data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            verifier_url,
            data=request_data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
            ) as response:
                response_body = response.read().decode("utf-8")

        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(
                f"ECP verifier returned HTTP {exc.code}: {error_body}"
            )

        except urllib.error.URLError as exc:
            raise ValueError(
                f"ECP verifier is not available: {exc}"
            )

        except TimeoutError:
            raise ValueError("ECP verifier request timed out.")

        try:
            result = json.loads(response_body)
        except json.JSONDecodeError:
            raise ValueError(
                f"ECP verifier returned invalid JSON: {response_body[:500]}"
            )

        return result