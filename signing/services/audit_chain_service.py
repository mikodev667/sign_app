from django.utils.translation import gettext as _


class AuditChainVerificationError(Exception):
    pass


class AuditChainService:
    @classmethod
    def verify_document(cls, *, document_id: int) -> dict:
        from signing.models import SigningAuditLog

        previous_hash = ""
        checked = 0

        logs = SigningAuditLog.objects.filter(document_id=document_id).order_by("id")

        for log in logs:
            expected_payload_hash = log.calculate_payload_hash()
            expected_entry_hash = log.calculate_entry_hash()

            if log.previous_hash != previous_hash:
                raise AuditChainVerificationError(
                    _("Audit chain break at log #%(log_id)s: previous_hash mismatch.") % {
                        "log_id": log.id,
                    }
                )

            if log.payload_hash != expected_payload_hash:
                raise AuditChainVerificationError(
                    _("Audit chain break at log #%(log_id)s: payload_hash mismatch.") % {
                        "log_id": log.id,
                    }
                )

            if log.entry_hash != expected_entry_hash:
                raise AuditChainVerificationError(
                    _("Audit chain break at log #%(log_id)s: entry_hash mismatch.") % {
                        "log_id": log.id,
                    }
                )

            previous_hash = log.entry_hash
            checked += 1

        return {
            "document_id": document_id,
            "checked": checked,
            "head_hash": previous_hash,
        }

    @classmethod
    def verify_all(cls) -> list[dict]:
        from signing.models import SigningAuditLog

        document_ids = (
            SigningAuditLog.objects
            .order_by("document_id")
            .values_list("document_id", flat=True)
            .distinct()
        )

        return [
            cls.verify_document(document_id=document_id)
            for document_id in document_ids
        ]
