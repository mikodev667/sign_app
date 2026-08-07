from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from admissions.models import AdmissionApiClient


class Command(BaseCommand):
    help = "Create an admissions API client and print its raw Bearer token once."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Human-readable client name.")
        parser.add_argument(
            "--days",
            type=int,
            default=0,
            help="Token lifetime in days. Omit or pass 0 for no expiration.",
        )

    def handle(self, *args, **options):
        raw_token = AdmissionApiClient.generate_raw_token()
        expires_at = None

        if options["days"] and options["days"] > 0:
            expires_at = timezone.now() + timedelta(days=options["days"])

        client = AdmissionApiClient.objects.create(
            name=options["name"],
            token_hash=AdmissionApiClient.hash_token(raw_token),
            expires_at=expires_at,
            is_active=True,
        )

        self.stdout.write(self.style.SUCCESS(f"Created admissions API client #{client.pk}: {client.name}"))
        self.stdout.write("")
        self.stdout.write("Send this token to the university once:")
        self.stdout.write(raw_token)
        self.stdout.write("")
        self.stdout.write("Authorization header:")
        self.stdout.write(f"Authorization: Bearer {raw_token}")
