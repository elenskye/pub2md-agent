"""v3 Phase 1: split the monolithic style into base_style × domains.

Historical rows are mapped to the pairing they effectively ran with:
economist → economist × [econ], academy → academy × [cs]. The reverse
mapping just drops the domains, which loses nothing the old schema held.
"""

from django.db import migrations, models

_LEGACY_DOMAINS = {"economist": ["econ"], "academy": ["cs"]}


def _fill_domains(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    for job in Job.objects.all():
        job.domains = _LEGACY_DOMAINS.get(job.base_style, [])
        job.save(update_fields=["domains"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(model_name="job", old_name="style", new_name="base_style"),
        migrations.AddField(
            model_name="job",
            name="domains",
            field=models.JSONField(default=list),
        ),
        migrations.RunPython(_fill_domains, migrations.RunPython.noop),
    ]
