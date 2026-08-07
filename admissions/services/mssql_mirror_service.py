import json
import logging

from django.conf import settings
from django.utils import timezone

from admissions.models import AdmissionMssqlContractRecord


logger = logging.getLogger(__name__)


class AdmissionMssqlMirrorError(RuntimeError):
    pass


class AdmissionMssqlMirrorService:
    db_alias = "admissions_mssql"

    @classmethod
    def is_enabled(cls):
        return (
            getattr(settings, "ADMISSIONS_MSSQL_ENABLED", False)
            and cls.db_alias in settings.DATABASES
        )

    @classmethod
    def sync_contract(cls, *, contract, public_url="", raise_on_error=None):
        if not cls.is_enabled():
            return False

        if raise_on_error is None:
            raise_on_error = getattr(settings, "ADMISSIONS_MSSQL_REQUIRED", False)

        try:
            defaults = cls.build_defaults(contract=contract, public_url=public_url)
            AdmissionMssqlContractRecord.objects.using(cls.db_alias).update_or_create(
                external_id=contract.external_id,
                defaults=defaults,
            )
            logger.info(
                "admission_mssql_sync_done external_id=%s contract_id=%s document_id=%s status=%s",
                contract.external_id,
                contract.pk,
                contract.document_id,
                contract.status,
            )
            return True
        except Exception as exc:
            message = f"Could not sync admission contract '{contract.external_id}' to MSSQL."
            if raise_on_error:
                raise AdmissionMssqlMirrorError(message) from exc

            logger.exception(message)
            return False

    @classmethod
    def delete_contract_record(cls, *, external_id, raise_on_error=None):
        if not cls.is_enabled():
            return False

        if raise_on_error is None:
            raise_on_error = getattr(settings, "ADMISSIONS_MSSQL_REQUIRED", False)

        try:
            AdmissionMssqlContractRecord.objects.using(cls.db_alias).filter(
                external_id=external_id,
            ).delete()
            logger.info("admission_mssql_delete_done external_id=%s", external_id)
            return True
        except Exception as exc:
            message = f"Could not delete admission contract '{external_id}' from MSSQL."
            if raise_on_error:
                raise AdmissionMssqlMirrorError(message) from exc

            logger.exception(message)
            return False

    @classmethod
    def build_defaults(cls, *, contract, public_url=""):
        api_client_name = ""
        if getattr(contract, "api_client_id", None):
            api_client_name = getattr(contract.api_client, "name", "") or ""

        defaults = {
            "admission_contract_id": contract.pk,
            "document_id": contract.document_id,
            "application_document_id": contract.application_document_id,
            "student_signer_id": contract.student_signer_id,
            "vice_rector_signer_id": contract.vice_rector_signer_id,
            "api_client_id": contract.api_client_id,
            "api_client_name": api_client_name,
            "template_rule_id": contract.template_rule_id,
            "education_level": contract.education_level or "",
            "funding_type": contract.funding_type or "",
            "language": contract.language or "",
            "program_code": contract.program_code or "",
            "program_name_ru": contract.program_name_ru or "",
            "program_name_kk": contract.program_name_kk or "",
            "applicant_full_name": contract.applicant_full_name or "",
            "applicant_iin": contract.applicant_iin or "",
            "applicant_phone": contract.applicant_phone or "",
            "applicant_email": contract.applicant_email or "",
            "tuition_amount": contract.tuition_amount,
            "status": contract.status or "",
            "raw_payload_json": json.dumps(
                contract.raw_payload or {},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            "synced_at": timezone.now(),
        }

        public_url = public_url or getattr(contract, "public_url", "")
        if public_url:
            defaults["public_url"] = public_url

        return defaults
