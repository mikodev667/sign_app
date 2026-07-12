from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signing", "0004_signature_and_signed_document_immutability"),
    ]

    operations = [
        migrations.AddField(
            model_name="signer",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]
