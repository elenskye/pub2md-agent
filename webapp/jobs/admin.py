from django.contrib import admin

from .maintenance import delete_job
from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """Read-only inspection plus deletion; deleting via admin also removes
    the job's files on disk (same path as the Clear-history button)."""

    list_display = ("id", "original_filename", "base_style", "status", "cost_usd", "created_at")
    list_filter = ("status", "base_style")
    readonly_fields = [f.name for f in Job._meta.fields]

    def delete_model(self, request, obj):
        delete_job(obj)

    def delete_queryset(self, request, queryset):
        for job in queryset:
            delete_job(job)
