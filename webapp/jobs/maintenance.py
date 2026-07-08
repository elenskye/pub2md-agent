"""Housekeeping for job rows and their on-disk artifacts.

Runs opportunistically on every job creation (cheap queries) so the service
stays self-cleaning without cron:
- stale sweep: a job stuck in queued/running longer than
  PUB2MD_JOB_STALE_MINUTES (worker died, deploy restarted) is marked failed
  so the UI never shows an eternal spinner;
- retention: terminal jobs older than PUB2MD_JOB_RETENTION_DAYS are deleted,
  rows and files both — uploaded PDFs and generated markdown do not
  accumulate on the server (the owner's burn-after-reading policy).
"""

import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Job


def delete_job(job: Job) -> None:
    shutil.rmtree(job.dir, ignore_errors=True)
    job.delete()


def sweep() -> dict:
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=settings.JOB_STALE_MINUTES)
    stale = Job.objects.filter(
        status__in=[Job.Status.QUEUED, Job.Status.RUNNING], created_at__lt=stale_cutoff
    )
    n_stale = 0
    for job in stale:
        job.status = Job.Status.FAILED
        job.error = f"marked stale after {settings.JOB_STALE_MINUTES} min (worker lost or restarted)"
        job.finished_at = now
        job.save(update_fields=["status", "error", "finished_at"])
        n_stale += 1

    retention_cutoff = now - timedelta(days=settings.JOB_RETENTION_DAYS)
    expired = Job.objects.filter(
        status__in=[Job.Status.DONE, Job.Status.FAILED], created_at__lt=retention_cutoff
    )
    n_expired = 0
    for job in expired:
        delete_job(job)
        n_expired += 1

    # Orphan directories: job folders whose DB row is gone (dev resets,
    # manual row deletion). Files must never outlive their job.
    jobs_root = Path(settings.JOBS_ROOT)
    n_orphans = 0
    if jobs_root.is_dir():
        known = {str(pk) for pk in Job.objects.values_list("id", flat=True)}
        for entry in jobs_root.iterdir():
            if entry.is_dir() and entry.name not in known:
                shutil.rmtree(entry, ignore_errors=True)
                n_orphans += 1
    return {"stale": n_stale, "expired": n_expired, "orphans": n_orphans}


def clear_history() -> int:
    """Delete all terminal jobs (rows + files). Queued/running jobs are kept —
    deleting them would orphan the worker thread mid-run."""
    n = 0
    for job in Job.objects.filter(status__in=[Job.Status.DONE, Job.Status.FAILED]):
        delete_job(job)
        n += 1
    return n
