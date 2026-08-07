from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0005_alter_admissionvicerectorprofile_phone"),
    ]

    operations = [
        migrations.AlterField(
            model_name="admissioncontract",
            name="applicant_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
