from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "original_filename", "style", "status", "cost_usd", "created_at")
    list_filter = ("status", "style")
    readonly_fields = [f.name for f in Job._meta.fields]
