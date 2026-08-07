from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0007_admissioncontract_public_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissioncontract",
            name="protected_access_token_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="admissioncontract",
            name="protected_url",
            field=models.TextField(blank=True),
        ),
    ]
