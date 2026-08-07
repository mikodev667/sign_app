from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from admissions.models import AdmissionContract
from admissions.services.mssql_mirror_service import AdmissionMssqlMirrorService


@receiver(post_save, sender=AdmissionContract)
def sync_admission_contract_to_mssql(sender, instance, using, **kwargs):
    if using == AdmissionMssqlMirrorService.db_alias:
        return

    transaction.on_commit(
        lambda: AdmissionMssqlMirrorService.sync_contract(
            contract=instance,
            raise_on_error=False,
        ),
        using=using,
    )
