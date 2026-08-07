import secrets

from django.db import migrations, models


SIGNED_DOCUMENT_UPDATE_TRIGGER = "documents_document_no_signed_update"


def set_signed_document_update_trigger(schema_editor, *, enabled):
    if schema_editor.connection.vendor != "postgresql":
        return

    action = "ENABLE" if enabled else "DISABLE"

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = %s",
            [SIGNED_DOCUMENT_UPDATE_TRIGGER],
        )

        if cursor.fetchone():
            cursor.execute(
                f"ALTER TABLE documents_document {action} TRIGGER {SIGNED_DOCUMENT_UPDATE_TRIGGER}"
            )


def populate_verification_tokens(apps, schema_editor):
    Document = apps.get_model("documents", "Document")

    used_tokens = set(
        Document.objects
        .exclude(verification_token__isnull=True)
        .exclude(verification_token="")
        .values_list("verification_token", flat=True)
    )

    documents = Document.objects.filter(
        models.Q(verification_token__isnull=True) | models.Q(verification_token="")
    )

    set_signed_document_update_trigger(schema_editor, enabled=False)
    try:
        for document in documents.iterator():
            while True:
                token = secrets.token_urlsafe(24)

                if token not in used_tokens:
                    used_tokens.add(token)
                    break

            Document.objects.filter(pk=document.pk).update(verification_token=token)
    finally:
        set_signed_document_update_trigger(schema_editor, enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0011_document_contract_date_document_contract_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="verification_token",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Public token for document verification page.",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(populate_verification_tokens, migrations.RunPython.noop),
    ]
