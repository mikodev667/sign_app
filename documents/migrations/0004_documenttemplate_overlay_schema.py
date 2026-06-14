from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_alter_documenttemplate_template_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttemplate",
            name="overlay_schema",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Variable placements over source document pages",
            ),
        ),
    ]
