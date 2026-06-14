from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0004_documenttemplate_overlay_schema"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="documenttemplate",
            name="overlay_schema",
        ),
    ]
