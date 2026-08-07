from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0013_document_department_documenttemplate_department"),
    ]

    operations = [
        migrations.AlterField(
            model_name="templatepartyfield",
            name="field_type",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("phone", "Phone"),
                    ("iin_bin", "IIN / BIN"),
                    ("signing_method", "Signing method"),
                    ("email", "Email"),
                    ("date", "Date"),
                    ("number", "Number"),
                    ("money", "Money amount"),
                ],
                default="text",
                max_length=30,
            ),
        ),
    ]
