"""JSON API for translation jobs.

POST /api/jobs            — upload a PDF + style, start a background job
GET  /api/jobs/<id>       — status / progress / result summary
GET  /api/jobs/<id>/download — zip of the generated markdown files
GET  /api/styles          — available style presets (single source of truth)
GET  /api/jobs?limit=N    — recent jobs (history)
GET  /api/jobs/<id>/files/<name> — one generated markdown file (preview)

CSRF is enforced; the UI echoes the csrftoken cookie via X-CSRFToken.
"""

import io
import re
import zipfile

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import api_login_required
from src.styles import available_styles

from . import maintenance, tasks
from .models import Job


@require_GET
@api_login_required
def styles(request):
    return JsonResponse({"styles": available_styles()})


def _month_spend_usd() -> float:
    now = timezone.now()
    month_jobs = Job.objects.filter(created_at__year=now.year, created_at__month=now.month)
    return sum(j.cost_usd for j in month_jobs)


@require_http_methods(["GET", "POST"])
@api_login_required
def jobs_collection(request):
    if request.method == "GET":
        limit = min(int(request.GET.get("limit", "10")), 50)
        return JsonResponse({"jobs": [j.as_dict() for j in Job.objects.all()[:limit]]})
    return _create_job(request)


def _create_job(request):
    maintenance.sweep()  # opportunistic housekeeping, cheap on two-user scale
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


@require_http_methods(["POST"])
@api_login_required
def clear_history(request):
    """Delete all finished/failed jobs — database rows and files together."""
    return JsonResponse({"cleared": maintenance.clear_history()})


_MD_NAME_RE = re.compile(r"^[\w\-一-鿿（）()]+\.md$")


@require_GET
@api_login_required
def job_file(request, job_id, name):
    """Raw markdown of one generated article, for in-browser preview."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "job not found"}, status=404)
    if not _MD_NAME_RE.match(name):
        return JsonResponse({"error": "bad filename"}, status=400)
    path = job.output_dir / name
    if not path.is_file():
        return JsonResponse({"error": "file not found"}, status=404)
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/markdown; charset=utf-8")
