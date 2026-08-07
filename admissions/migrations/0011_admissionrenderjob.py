from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0010_allow_controlled_admission_contract_delete"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdmissionRenderJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("processing", "Processing"),
                            ("done", "Done"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=5)),
                (
                    "next_attempt_at",
                    models.DateTimeField(default=django.utils.timezone.now, db_index=True),
                ),
                (
                    "locked_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contract",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="render_job",
                        to="admissions.admissioncontract",
                    ),
                ),
            ],
            options={
                "verbose_name": "Admission render job",
                "verbose_name_plural": "Admission render jobs",
                "ordering": ["next_attempt_at", "created_at"],
            },
        ),
    ]
