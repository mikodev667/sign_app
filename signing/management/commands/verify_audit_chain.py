from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _

from signing.services.audit_chain_service import (
    AuditChainService,
    AuditChainVerificationError,
)


class Command(BaseCommand):
    help = "Verify SigningAuditLog hash chains."

    def add_arguments(self, parser):
        parser.add_argument(
            "--document-id",
            type=int,
            help="Verify one document instead of all documents.",
        )

    def handle(self, *args, **options):
        try:
            if options["document_id"]:
                results = [
                    AuditChainService.verify_document(
                        document_id=options["document_id"],
                    )
                ]
            else:
                results = AuditChainService.verify_all()
        except AuditChainVerificationError as exc:
            raise CommandError(str(exc)) from exc

        if not results:
            self.stdout.write(self.style.WARNING(_("No audit log entries found.")))
            return

        for result in results:
            self.stdout.write(
                self.style.SUCCESS(
                    "document={document_id} checked={checked} head_hash={head_hash}".format(
                        **result
                    )
                )
            )
