from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0006_alter_admissioncontract_applicant_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissioncontract",
            name="public_url",
            field=models.TextField(blank=True),
        ),
    ]
