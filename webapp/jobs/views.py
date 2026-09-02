"""JSON API for translation jobs.

POST /api/jobs            — upload a PDF + base style + domains, start a job
GET  /api/jobs/<id>       — status / progress / result summary
GET  /api/jobs/<id>/download — zip of the generated markdown files
GET  /api/styles          — base styles, domains and default pairings
                            (single source of truth: src/styles.py)
GET  /api/jobs?limit=N    — recent jobs (history)
GET  /api/jobs/<id>/files/<name> — one generated markdown file (preview)
GET  /api/glossary/candidates    — JSON batch of runtime-grown terms, for
                            the owner's offline audit (v3 Phase 5)

CSRF is enforced; the UI echoes the csrftoken cookie via X-CSRFToken.
"""

import io
import json
import re
import zipfile
from datetime import date

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import api_login_required
from src.styles import available_base_styles, available_domains, default_domains

from src.tools.glossary_store import candidate_batch

from . import maintenance, tasks
from .models import Job


@require_GET
@api_login_required
def styles(request):
    base_styles = available_base_styles()
    return JsonResponse(
        {
            "base_styles": base_styles,
            "domains": available_domains(),
            "defaults": {bs: default_domains(bs) for bs in base_styles},
        }
    )


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
    base_style = request.POST.get("base_style", "economist")
    # Repeated form field; submission order is the glossary precedence order.
    domains = list(dict.fromkeys(request.POST.getlist("domains")))
    refine = request.POST.get("refine", "").lower() in ("1", "true", "on")

    if upload is None:
        return JsonResponse({"error": "missing file field 'pdf'"}, status=400)
    if not upload.name.lower().endswith((".pdf", ".md")):
        return JsonResponse({"error": "only .pdf and .md files are accepted"}, status=400)
    if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        return JsonResponse(
            {"error": f"file exceeds the {settings.MAX_UPLOAD_MB} MB limit"}, status=400
        )
    if base_style not in available_base_styles():
        return JsonResponse({"error": f"unknown base style '{base_style}'"}, status=400)
    unknown = [d for d in domains if d not in available_domains()]
    if unknown:
        return JsonResponse({"error": f"unknown domain(s): {', '.join(unknown)}"}, status=400)
    # No domain is a valid choice: the UI preselects the style's usual
    # pairing, so an empty selection means "translate without a glossary".
    if _month_spend_usd() >= settings.MONTHLY_BUDGET_USD:
        return JsonResponse(
            {"error": "monthly budget exhausted; try again next month"}, status=429
        )

    job = Job.objects.create(
        base_style=base_style, domains=domains, refine=refine, original_filename=upload.name
    )
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


@require_GET
@api_login_required
def glossary_candidates(request):
    """Download the terms this deployment grew but nobody has audited yet.
    Same payload as `manage.py export_candidates`, so the owner can collect a
    batch from the browser, for an installation you cannot audit in place."""
    domain = request.GET.get("domain")
    if domain and domain not in available_domains():
        return JsonResponse({"error": f"unknown domain '{domain}'"}, status=400)
    batch = candidate_batch([domain] if domain else None)
    response = HttpResponse(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
        content_type="application/json; charset=utf-8",
    )
    stem = f"glossary-candidates-{domain or 'all'}-{date.today().isoformat()}"
    response["Content-Disposition"] = f'attachment; filename="{stem}.json"'
    return response
