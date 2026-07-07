import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


class Job(models.Model):
    """One PDF-to-Markdown run, executed in the background."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    style = models.CharField(max_length=32)
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)
    progress = models.CharField(max_length=128, blank=True, default="")
    error = models.TextField(blank=True, default="")
    # Final summary: articles, new_terms, tokens — mirrors the CLI run log.
    result = models.JSONField(null=True, blank=True)
    cost_usd = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-created_at"]

    @property
    def dir(self) -> Path:
        return Path(settings.JOBS_ROOT) / str(self.id)

    @property
    def input_path(self) -> Path:
        return self.dir / "input.pdf"

    @property
    def output_dir(self) -> Path:
        return self.dir / "outputs"

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat(),
            "style": self.style,
            "original_filename": self.original_filename,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "result": self.result,
            "cost_usd": round(self.cost_usd, 4),
        }
