"""API-contract tests for the jobs service. The background executor is
mocked out — pipeline correctness is covered by the Agent's own test suite;
here we test the HTTP layer's validation, guards and serialization."""

import io
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

# Keep test job files out of the real var/webapp/jobs directory.
_TMP_JOBS = tempfile.mkdtemp(prefix="pub2md-test-jobs-")

from .models import Job

PDF_BYTES = b"%PDF-1.4 fake"


def _upload(name="a.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(JOBS_ROOT=_TMP_JOBS)
class AuthedTestCase(TestCase):
    """All jobs endpoints sit behind the login wall (Phase 3)."""

    def setUp(self):
        User.objects.create_user(username="guest1", password="pw-123456")
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})


class StylesApiTests(AuthedTestCase):
    def test_two_axis_model_derived_from_files(self):
        resp = self.client.get("/api/styles")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["base_styles"], ["academy", "economist", "general"])
        self.assertEqual(body["domains"], ["cs", "econ", "pm"])
        self.assertEqual(
            body["defaults"],
            {"academy": ["cs"], "economist": ["econ"], "general": []},
        )


@patch("jobs.views.tasks.submit")
class CreateJobTests(AuthedTestCase):
    def test_creates_job_and_submits(self, submit):
        resp = self.client.post(
            "/api/jobs",
            {"pdf": _upload(), "base_style": "academy", "domains": ["cs", "pm"]},
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["base_style"], "academy")
        self.assertEqual(body["domains"], ["cs", "pm"])
        job = Job.objects.get(id=body["id"])
        self.assertTrue(job.input_path.exists())
        submit.assert_called_once_with(job.id)

    def test_no_domain_selected_means_no_glossary(self, submit):
        """The UI preselects the style's usual domains, so an empty selection
        is a deliberate "translate without a glossary" — not a mistake to
        paper over with defaults."""
        resp = self.client.post("/api/jobs", {"pdf": _upload(), "base_style": "economist"})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["domains"], [])

    def test_refine_flag_stored_and_defaults_off(self, submit):
        resp = self.client.post(
            "/api/jobs",
            {"pdf": _upload(), "base_style": "economist", "refine": "true"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["refine"])
        resp = self.client.post("/api/jobs", {"pdf": _upload(), "base_style": "economist"})
        self.assertFalse(resp.json()["refine"])

    def test_missing_file_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"base_style": "economist"})
        self.assertEqual(resp.status_code, 400)
        submit.assert_not_called()

    def test_non_pdf_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload(name="a.docx")})
        self.assertEqual(resp.status_code, 400)

    def test_markdown_upload_takes_the_direct_path(self, submit):
        """A .md upload is accepted and stored as input.md — tasks.py routes
        on that suffix, so the PDF pipeline never sees it."""
        resp = self.client.post(
            "/api/jobs",
            {"pdf": _upload(name="README.md", content=b"# Title\n"), "base_style": "academy"},
        )
        self.assertEqual(resp.status_code, 201)
        job = Job.objects.get(id=resp.json()["id"])
        self.assertTrue(job.is_markdown)
        self.assertEqual(job.input_path.name, "input.md")
        self.assertTrue(job.input_path.exists())

    def test_unknown_base_style_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload(), "base_style": "poetry"})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_domain_rejected(self, submit):
        resp = self.client.post(
            "/api/jobs",
            {"pdf": _upload(), "base_style": "economist", "domains": ["econ", "astrology"]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("astrology", resp.json()["error"])
        submit.assert_not_called()

    @override_settings(MAX_UPLOAD_MB=0)
    def test_oversize_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload()})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("MB limit", resp.json()["error"])

    @override_settings(MONTHLY_BUDGET_USD=1.0)
    def test_budget_guard(self, submit):
        Job.objects.create(base_style="economist", domains=["econ"], original_filename="x.pdf", cost_usd=1.2)
        resp = self.client.post("/api/jobs", {"pdf": _upload()})
        self.assertEqual(resp.status_code, 429)
        submit.assert_not_called()


class JobDetailTests(AuthedTestCase):
    def test_unknown_job_404(self):
        resp = self.client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_detail_roundtrip(self):
        job = Job.objects.create(base_style="academy", domains=["cs"], original_filename="p.pdf")
        resp = self.client.get(f"/api/jobs/{job.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["base_style"], "academy")
        self.assertEqual(resp.json()["domains"], ["cs"])


class DownloadTests(AuthedTestCase):
    def test_download_before_done_409(self):
        job = Job.objects.create(base_style="economist", domains=["econ"], original_filename="p.pdf")
        resp = self.client.get(f"/api/jobs/{job.id}/download")
        self.assertEqual(resp.status_code, 409)

    def test_download_zips_outputs(self):
        job = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="p.pdf", status=Job.Status.DONE
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)
        (job.output_dir / "00-test.md").write_text("# hi", encoding="utf-8")
        resp = self.client.get(f"/api/jobs/{job.id}/download")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("bilingual.zip", resp["Content-Disposition"])


class JobsListTests(AuthedTestCase):
    def test_recent_jobs_listed(self):
        Job.objects.create(base_style="economist", domains=["econ"], original_filename="a.pdf")
        Job.objects.create(base_style="academy", domains=["cs"], original_filename="b.pdf")
        resp = self.client.get("/api/jobs?limit=1")
        self.assertEqual(resp.status_code, 200)
        jobs = resp.json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["original_filename"], "b.pdf")  # newest first


class JobFileTests(AuthedTestCase):
    def _job_with_file(self):
        job = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="p.pdf", status=Job.Status.DONE
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)
        (job.output_dir / "00-hello.md").write_text("# 标题\n\n$$x^2$$\n", encoding="utf-8")
        return job

    def test_serves_markdown(self):
        job = self._job_with_file()
        resp = self.client.get(f"/api/jobs/{job.id}/files/00-hello.md")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("$$x^2$$", resp.content.decode())

    def test_rejects_traversal_names(self):
        job = self._job_with_file()
        resp = self.client.get(f"/api/jobs/{job.id}/files/..%2F..%2Fsecret.md")
        self.assertIn(resp.status_code, (400, 404))

    def test_missing_file_404(self):
        job = self._job_with_file()
        resp = self.client.get(f"/api/jobs/{job.id}/files/99-none.md")
        self.assertEqual(resp.status_code, 404)


class CsrfEnforcedTests(TestCase):
    def test_post_without_token_rejected(self):
        from django.test import Client

        User.objects.create_user(username="guest1", password="pw-123456")
        strict = Client(enforce_csrf_checks=True)
        resp = strict.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.assertEqual(resp.status_code, 403)

    def test_post_with_token_accepted(self):
        from django.test import Client

        User.objects.create_user(username="guest1", password="pw-123456")
        strict = Client(enforce_csrf_checks=True)
        strict.get("/")  # index plants the csrftoken cookie
        token = strict.cookies["csrftoken"].value
        resp = strict.post(
            "/api/login",
            {"username": "guest1", "password": "pw-123456"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(resp.status_code, 200)


class ClearHistoryTests(AuthedTestCase):
    def test_clears_terminal_jobs_and_files_keeps_running(self):
        done = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="a.pdf", status=Job.Status.DONE
        )
        done.output_dir.mkdir(parents=True, exist_ok=True)
        (done.output_dir / "00-a.md").write_text("x", encoding="utf-8")
        running = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="b.pdf", status=Job.Status.RUNNING
        )

        resp = self.client.post("/api/jobs/clear")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["cleared"], 1)
        self.assertFalse(Job.objects.filter(id=done.id).exists())
        self.assertFalse(done.dir.exists())
        self.assertTrue(Job.objects.filter(id=running.id).exists())

    def test_requires_auth(self):
        from django.test import Client

        resp = Client().post("/api/jobs/clear")
        self.assertEqual(resp.status_code, 401)


class SweepTests(AuthedTestCase):
    def _age(self, job, **delta):
        from datetime import timedelta

        from django.utils import timezone

        Job.objects.filter(id=job.id).update(created_at=timezone.now() - timedelta(**delta))

    def test_stale_running_job_marked_failed(self):
        from . import maintenance

        job = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="x.pdf", status=Job.Status.RUNNING
        )
        self._age(job, minutes=90)
        result = maintenance.sweep()
        job.refresh_from_db()
        self.assertEqual(result["stale"], 1)
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertIn("stale", job.error)

    def test_fresh_running_job_untouched(self):
        from . import maintenance

        job = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="x.pdf", status=Job.Status.RUNNING
        )
        maintenance.sweep()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.RUNNING)

    def test_expired_terminal_job_deleted_with_files(self):
        from . import maintenance

        job = Job.objects.create(
            base_style="economist", domains=["econ"], original_filename="x.pdf", status=Job.Status.DONE
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)
        self._age(job, days=30)
        result = maintenance.sweep()
        self.assertEqual(result["expired"], 1)
        self.assertFalse(Job.objects.filter(id=job.id).exists())
        self.assertFalse(job.dir.exists())


class StageOfTests(TestCase):
    def test_progress_labels(self):
        from .tasks import _stage_of

        self.assertEqual(_stage_of({}), "starting")
        self.assertEqual(_stage_of({"raw_blocks": [1]}), "parsing PDF layout")
        self.assertEqual(
            _stage_of({"raw_blocks": [1], "cleaned_text": [1]}),
            "cleaning layout & transcribing formulas",
        )
        self.assertIn("translating", _stage_of({"cleaned_text": [1], "articles": [1, 2]}))
        self.assertEqual(
            _stage_of({"articles": [1, 2], "results": [1]}),
            "translating: 1/2 article(s) done",
        )
        self.assertEqual(
            _stage_of({"articles": [1, 2], "results": [1, 2]}), "finished 2 article(s)"
        )

    def test_percent_marks(self):
        from .tasks import _percent_of

        self.assertEqual(_percent_of({}), 2)
        self.assertEqual(_percent_of({"raw_blocks": [1]}), 10)
        self.assertEqual(_percent_of({"raw_blocks": [1], "cleaned_text": [1]}), 25)
        self.assertEqual(_percent_of({"articles": [1, 2]}), 35)
        self.assertEqual(_percent_of({"articles": [1, 2], "results": [1]}), 65)
        # Completion caps at 95 — only the final save reports 100.
        self.assertEqual(_percent_of({"articles": [1, 2], "results": [1, 2]}), 95)


_BATCH = {
    "exported_at": "2026-07-25",
    "terms": [
        {
            "en": "ablation study",
            "zh": "消融实验",
            "category": "ml",
            "source": "web_search",
            "added_date": "2026-07-25",
            "domain": "cs",
            "status": "candidate",
        }
    ],
}


class GlossaryCandidateExportTests(AuthedTestCase):
    """v3 Phase 5: the owner collects runtime-grown terms for an offline
    audit — from the browser, or over SSH with the same payload."""

    @patch("jobs.views.candidate_batch", return_value=_BATCH)
    def test_downloads_batch_as_attachment(self, batch):
        resp = self.client.get("/api/glossary/candidates?domain=cs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment;", resp["Content-Disposition"])
        self.assertIn("glossary-candidates-cs-", resp["Content-Disposition"])
        self.assertEqual(json.loads(resp.content)["terms"][0]["en"], "ablation study")
        batch.assert_called_once_with(["cs"])

    @patch("jobs.views.candidate_batch", return_value=_BATCH)
    def test_all_domains_when_unfiltered(self, batch):
        self.assertEqual(self.client.get("/api/glossary/candidates").status_code, 200)
        batch.assert_called_once_with(None)

    def test_rejects_unknown_domain(self):
        resp = self.client.get("/api/glossary/candidates?domain=nope")
        self.assertEqual(resp.status_code, 400)

    def test_requires_login(self):
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/glossary/candidates").status_code, 401)

    @patch("jobs.management.commands.export_candidates.candidate_batch", return_value=_BATCH)
    def test_management_command_writes_the_same_payload(self, batch):
        out = io.StringIO()
        with tempfile.NamedTemporaryFile("r", suffix=".json") as fh:
            call_command("export_candidates", "--domain", "cs", "--output", fh.name, stdout=out)
            written = json.load(open(fh.name, encoding="utf-8"))
        self.assertEqual(written["terms"][0]["en"], "ablation study")
        self.assertIn("exported 1 candidate", out.getvalue())
