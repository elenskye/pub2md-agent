from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_two_axis_style"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="percent",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
