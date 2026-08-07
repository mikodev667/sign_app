from admissions.models import AdmissionApiClient


class AdmissionApiAuthError(ValueError):
    pass


class AdmissionApiAuthService:
    @classmethod
    def authenticate(cls, request):
        header = request.META.get("HTTP_AUTHORIZATION", "").strip()

        if not header:
            raise AdmissionApiAuthError("Authorization header is required.")

        scheme, separator, raw_token = header.partition(" ")
        if not separator or scheme.lower() != "bearer":
            raise AdmissionApiAuthError("Authorization header must use Bearer token.")

        raw_token = raw_token.strip()

        if not raw_token:
            raise AdmissionApiAuthError("Bearer token is empty.")

        token_hash = AdmissionApiClient.hash_token(raw_token)
        client = AdmissionApiClient.objects.filter(token_hash=token_hash).first()

        if not client or not client.is_valid():
            raise AdmissionApiAuthError("Invalid or inactive API token.")

        return client
