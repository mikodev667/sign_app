import logging
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from admissions.models import AdmissionContract, AdmissionRenderJob
from admissions.services.contract_builder import AdmissionContractBuilder
from admissions.services.mssql_mirror_service import AdmissionMssqlMirrorService


logger = logging.getLogger(__name__)


class AdmissionRenderQueueService:
    stale_processing_after = timedelta(minutes=20)
    retry_delay = timedelta(minutes=1)

    @classmethod
    def is_contract_ready(cls, contract):
        render_job = getattr(contract, "render_job", None)
        if render_job and render_job.status in {
            AdmissionRenderJob.Status.QUEUED,
            AdmissionRenderJob.Status.PROCESSING,
        }:
            return False

        document = getattr(contract, "document", None)
        if not document or not contract.student_signer_id:
            return False

        return bool(document.rendered_docx_file or document.rendered_pdf_file or document.rendered_html)

    @classmethod
    def enqueue_contract(cls, *, contract, reset_failed=False):
        if not reset_failed and cls.is_contract_ready(contract):
            logger.info(
                "admission_render_enqueue_skipped_ready external_id=%s contract_id=%s",
                contract.external_id,
                contract.pk,
            )
            return None

        job, created = AdmissionRenderJob.objects.get_or_create(
            contract=contract,
            defaults={
                "status": AdmissionRenderJob.Status.QUEUED,
                "next_attempt_at": timezone.now(),
            },
        )

        if created:
            logger.info(
                "admission_render_job_created external_id=%s contract_id=%s job_id=%s reset_failed=%s",
                contract.external_id,
                contract.pk,
                job.pk,
                reset_failed,
            )

        if reset_failed:
            should_requeue = not created and job.status != AdmissionRenderJob.Status.PROCESSING
        else:
            should_requeue = (
                not created
                and job.status not in {
                    AdmissionRenderJob.Status.DONE,
                    AdmissionRenderJob.Status.PROCESSING,
                }
                and job.status != AdmissionRenderJob.Status.FAILED
            )

        if should_requeue:
            old_status = job.status
            job.status = AdmissionRenderJob.Status.QUEUED
            job.next_attempt_at = timezone.now()
            job.locked_at = None
            if reset_failed:
                job.attempts = 0
            job.save(update_fields=[
                "status",
                "next_attempt_at",
                "locked_at",
                "attempts",
                "updated_at",
            ])
            logger.info(
                "admission_render_job_requeued external_id=%s contract_id=%s job_id=%s old_status=%s reset_failed=%s",
                contract.external_id,
                contract.pk,
                job.pk,
                old_status,
                reset_failed,
            )
        elif not created:
            logger.info(
                "admission_render_enqueue_kept_existing external_id=%s contract_id=%s job_id=%s status=%s reset_failed=%s",
                contract.external_id,
                contract.pk,
                job.pk,
                job.status,
                reset_failed,
            )

        return job

    @classmethod
    def process_pending(cls, *, limit=1):
        cls.requeue_stale_processing_jobs()

        processed = 0
        while processed < limit:
            job = cls.acquire_next_job()
            if not job:
                break

            cls.process_job(job)
            processed += 1

        return processed

    @classmethod
    def acquire_next_job(cls):
        now = timezone.now()

        with transaction.atomic():
            jobs = (
                AdmissionRenderJob.objects
                .filter(
                    status=AdmissionRenderJob.Status.QUEUED,
                    next_attempt_at__lte=now,
                    attempts__lt=F("max_attempts"),
                )
                .select_related("contract")
                .order_by("next_attempt_at", "created_at")
            )

            if connection.features.has_select_for_update:
                if getattr(connection.features, "has_select_for_update_skip_locked", False):
                    jobs = jobs.select_for_update(skip_locked=True)
                else:
                    jobs = jobs.select_for_update()

            job = jobs.first()
            if not job:
                return None

            job.status = AdmissionRenderJob.Status.PROCESSING
            job.locked_at = now
            job.attempts += 1
            job.save(update_fields=[
                "status",
                "locked_at",
                "attempts",
                "updated_at",
            ])
            logger.info(
                "admission_render_job_acquired external_id=%s contract_id=%s job_id=%s attempts=%s",
                job.contract.external_id,
                job.contract_id,
                job.pk,
                job.attempts,
            )
            return job

    @classmethod
    def process_job(cls, job):
        try:
            contract = AdmissionContractBuilder.render_contract_documents(
                contract=job.contract,
            )
        except Exception as exc:
            cls.mark_failed_attempt(job=job, exc=exc)
            return False

        job.status = AdmissionRenderJob.Status.DONE
        job.locked_at = None
        job.last_error = ""
        job.save(update_fields=[
            "status",
            "locked_at",
            "last_error",
            "updated_at",
        ])

        AdmissionMssqlMirrorService.sync_contract(
            contract=contract,
            raise_on_error=False,
        )
        logger.info(
            "admission_render_job_done external_id=%s contract_id=%s job_id=%s document_id=%s application_document_id=%s",
            contract.external_id,
            contract.pk,
            job.pk,
            contract.document_id,
            contract.application_document_id,
        )
        return True

    @classmethod
    def mark_failed_attempt(cls, *, job, exc):
        error_message = str(exc) or exc.__class__.__name__
        logger.exception(
            "Could not render admission contract %s.",
            job.contract.external_id,
        )

        contract = job.contract
        contract.error_message = error_message

        if job.attempts >= job.max_attempts:
            job.status = AdmissionRenderJob.Status.FAILED
            contract.status = AdmissionContract.Status.FAILED
        else:
            job.status = AdmissionRenderJob.Status.QUEUED
            job.next_attempt_at = timezone.now() + cls.retry_delay

        job.locked_at = None
        job.last_error = error_message

        job.save(update_fields=[
            "status",
            "next_attempt_at",
            "locked_at",
            "last_error",
            "updated_at",
        ])
        contract.save(update_fields=[
            "status",
            "error_message",
            "updated_at",
        ])
        logger.warning(
            "admission_render_job_failed external_id=%s contract_id=%s job_id=%s attempts=%s max_attempts=%s next_status=%s error=%s",
            contract.external_id,
            contract.pk,
            job.pk,
            job.attempts,
            job.max_attempts,
            job.status,
            error_message,
        )

    @classmethod
    def requeue_stale_processing_jobs(cls):
        stale_before = timezone.now() - cls.stale_processing_after
        updated = AdmissionRenderJob.objects.filter(
            status=AdmissionRenderJob.Status.PROCESSING,
            locked_at__lt=stale_before,
        ).update(
            status=AdmissionRenderJob.Status.QUEUED,
            locked_at=None,
            next_attempt_at=timezone.now(),
            updated_at=timezone.now(),
        )
        if updated:
            logger.warning("admission_render_stale_jobs_requeued count=%s", updated)
