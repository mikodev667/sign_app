import logging

from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.utils.translation import gettext as _

from documents.models import Document, StoredObject
from signing.models import (
    Signer,
    SignerAccessToken,
    SigningAuditLog,
    SigningSession,
    Signature,
)

from admissions.models import AdmissionContract
from admissions.services.mssql_mirror_service import AdmissionMssqlMirrorService


logger = logging.getLogger(__name__)


class AdmissionContractDeletionError(ValueError):
    pass


class AdmissionContractDeletionService:
    postgres_cleanup_flag = "qolqoyu.allow_admission_contract_delete"

    @classmethod
    def can_delete(cls, contract):
        if not contract:
            return False

        return not (
            contract.vice_rector_signer
            and contract.vice_rector_signer.is_signed()
        )

    @classmethod
    @transaction.atomic
    def delete_contract(cls, *, contract):
        locked_contract = (
            AdmissionContract.objects
            .select_for_update()
            .get(pk=contract.pk)
        )
        locked_contract.refresh_status_from_signers(save=False)

        if not cls.can_delete(locked_contract):
            logger.warning(
                "admission_contract_delete_blocked external_id=%s contract_id=%s status=%s vice_rector_signer_id=%s",
                locked_contract.external_id,
                locked_contract.pk,
                locked_contract.status,
                locked_contract.vice_rector_signer_id,
            )
            raise AdmissionContractDeletionError(
                _("The applicant cannot be deleted after the vice rector has signed.")
            )

        external_id = locked_contract.external_id
        document_ids = [
            document_id
            for document_id in [
                locked_contract.document_id,
                locked_contract.application_document_id,
            ]
            if document_id
        ]
        file_names = cls.collect_document_file_names(document_ids)

        logger.info(
            "admission_contract_delete_started external_id=%s contract_id=%s document_ids=%s file_count=%s",
            external_id,
            locked_contract.pk,
            ",".join(str(document_id) for document_id in document_ids),
            len(file_names),
        )

        cls.enable_postgres_admission_cleanup()

        AdmissionContract.objects.filter(pk=locked_contract.pk).delete()

        if document_ids:
            SigningAuditLog.objects.filter(document_id__in=document_ids).delete()
            Signature.objects.filter(document_id__in=document_ids).delete()
            SigningSession.objects.filter(signer__document_id__in=document_ids).delete()
            SignerAccessToken.objects.filter(signer__document_id__in=document_ids).delete()
            Signer.objects.filter(document_id__in=document_ids).delete()
            StoredObject.objects.filter(document_id__in=document_ids).delete()
            Document.objects.filter(pk__in=document_ids).delete()

        AdmissionMssqlMirrorService.delete_contract_record(
            external_id=external_id,
            raise_on_error=False,
        )
        transaction.on_commit(lambda: cls.delete_files(file_names))

        logger.info(
            "admission_contract_delete_done external_id=%s document_ids=%s file_count=%s",
            external_id,
            ",".join(str(document_id) for document_id in document_ids),
            len(file_names),
        )

        return {
            "external_id": external_id,
            "document_ids": document_ids,
        }

    @classmethod
    def enable_postgres_admission_cleanup(cls):
        if connection.vendor != "postgresql":
            return

        with connection.cursor() as cursor:
            cursor.execute(
                f"SET LOCAL {cls.postgres_cleanup_flag} = 'on'"
            )

    @staticmethod
    def collect_document_file_names(document_ids):
        if not document_ids:
            return []

        file_names = []
        for document in Document.objects.filter(pk__in=document_ids):
            for field_name in ["rendered_pdf_file", "rendered_docx_file"]:
                file_field = getattr(document, field_name, None)
                if file_field and file_field.name:
                    file_names.append(file_field.name)

        return file_names

    @staticmethod
    def delete_files(file_names):
        for file_name in file_names:
            try:
                default_storage.delete(file_name)
            except Exception:
                logger.exception("Could not delete admission document file '%s'.", file_name)
