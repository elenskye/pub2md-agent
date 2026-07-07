"""JSON API for translation jobs.

POST /api/jobs            — upload a PDF + style, start a background job
GET  /api/jobs/<id>       — status / progress / result summary
GET  /api/jobs/<id>/download — zip of the generated markdown files
GET  /api/styles          — available style presets (single source of truth)

CSRF: the create endpoint is exempt for now; Phase 3 puts the whole API
behind session auth and Phase 4's UI sends the CSRF token properly.
"""

import io
import zipfile

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import api_login_required
from src.styles import available_styles

from . import tasks
from .models import Job


@require_GET
@api_login_required
def styles(request):
    return JsonResponse({"styles": available_styles()})


def _month_spend_usd() -> float:
    now = timezone.now()
    month_jobs = Job.objects.filter(created_at__year=now.year, created_at__month=now.month)
    return sum(j.cost_usd for j in month_jobs)


@csrf_exempt
@require_POST
@api_login_required
def create_job(request):
    upload = request.FILES.get("pdf")
    style = request.POST.get("style", "economist")

    if upload is None:
        return JsonResponse({"error": "missing file field 'pdf'"}, status=400)
    if not upload.name.lower().endswith(".pdf"):
        return JsonResponse({"error": "only .pdf files are accepted"}, status=400)
    if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        return JsonResponse(
            {"error": f"file exceeds the {settings.MAX_UPLOAD_MB} MB limit"}, status=400
        )
    if style not in available_styles():
        return JsonResponse({"error": f"unknown style '{style}'"}, status=400)
    if _month_spend_usd() >= settings.MONTHLY_BUDGET_USD:
        return JsonResponse(
            {"error": "monthly budget exhausted; try again next month"}, status=429
        )

    job = Job.objects.create(style=style, original_filename=upload.name)
    job.dir.mkdir(parents=True, exist_ok=True)
    with open(job.input_path, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)

    tasks.submit(job.id)
    return JsonResponse(job.as_dict(), status=201)


@require_GET
@api_login_required
def job_detail(request, job_id):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "job not found"}, status=404)
    return JsonResponse(job.as_dict())


@require_GET
@api_login_required
def job_download(request, job_id):
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "job not found"}, status=404)
    if job.status != Job.Status.DONE:
        return JsonResponse({"error": f"job is {job.status}, not done"}, status=409)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for md in sorted(job.output_dir.glob("*.md")):
            zf.write(md, arcname=md.name)
    buffer.seek(0)
    stem = job.original_filename.rsplit(".", 1)[0]
    return FileResponse(buffer, as_attachment=True, filename=f"{stem}-bilingual.zip")
