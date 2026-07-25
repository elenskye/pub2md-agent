from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_job_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="refine",
            field=models.BooleanField(default=False),
        ),
    ]
