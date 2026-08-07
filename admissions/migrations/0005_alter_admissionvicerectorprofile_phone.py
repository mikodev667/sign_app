from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0004_admissionmssqlcontractrecord"),
    ]

    operations = [
        migrations.AlterField(
            model_name="admissionvicerectorprofile",
            name="phone",
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
