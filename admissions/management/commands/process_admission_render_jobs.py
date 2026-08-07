import time
import logging

from django.core.management.base import BaseCommand

from admissions.services.render_queue_service import AdmissionRenderQueueService


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Render queued admission contracts in the background."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process available jobs once and exit.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Maximum number of jobs to process per cycle.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=2.0,
            help="Seconds to wait between polling cycles.",
        )

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        sleep_seconds = max(0.2, options["sleep"])
        logger.info(
            "admission_render_worker_started once=%s limit=%s sleep=%s",
            options["once"],
            limit,
            sleep_seconds,
        )

        while True:
            processed = AdmissionRenderQueueService.process_pending(limit=limit)

            if processed:
                self.stdout.write(f"Processed {processed} admission render job(s).")

            if options["once"]:
                logger.info("admission_render_worker_finished_once processed=%s", processed)
                break

            time.sleep(sleep_seconds)
