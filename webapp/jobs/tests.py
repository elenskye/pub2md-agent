"""API-contract tests for the jobs service. The background executor is
mocked out — pipeline correctness is covered by the Agent's own test suite;
here we test the HTTP layer's validation, guards and serialization."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Job

PDF_BYTES = b"%PDF-1.4 fake"


def _upload(name="a.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class AuthedTestCase(TestCase):
    """All jobs endpoints sit behind the login wall (Phase 3)."""

    def setUp(self):
        User.objects.create_user(username="guest1", password="pw-123456")
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})


class StylesApiTests(AuthedTestCase):
    def test_styles_derived_from_prompt_files(self):
        resp = self.client.get("/api/styles")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["styles"], ["academy", "economist"])


@patch("jobs.views.tasks.submit")
class CreateJobTests(AuthedTestCase):
    def test_creates_job_and_submits(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload(), "style": "economist"})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        job = Job.objects.get(id=body["id"])
        self.assertTrue(job.input_path.exists())
        submit.assert_called_once_with(job.id)

    def test_missing_file_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"style": "economist"})
        self.assertEqual(resp.status_code, 400)
        submit.assert_not_called()

    def test_non_pdf_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload(name="a.docx")})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_style_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload(), "style": "poetry"})
        self.assertEqual(resp.status_code, 400)

    @override_settings(MAX_UPLOAD_MB=0)
    def test_oversize_rejected(self, submit):
        resp = self.client.post("/api/jobs", {"pdf": _upload()})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("MB limit", resp.json()["error"])

    @override_settings(MONTHLY_BUDGET_USD=1.0)
    def test_budget_guard(self, submit):
        Job.objects.create(style="economist", original_filename="x.pdf", cost_usd=1.2)
        resp = self.client.post("/api/jobs", {"pdf": _upload()})
        self.assertEqual(resp.status_code, 429)
        submit.assert_not_called()


class JobDetailTests(AuthedTestCase):
    def test_unknown_job_404(self):
        resp = self.client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_detail_roundtrip(self):
        job = Job.objects.create(style="academy", original_filename="p.pdf")
        resp = self.client.get(f"/api/jobs/{job.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["style"], "academy")


class DownloadTests(AuthedTestCase):
    def test_download_before_done_409(self):
        job = Job.objects.create(style="economist", original_filename="p.pdf")
        resp = self.client.get(f"/api/jobs/{job.id}/download")
        self.assertEqual(resp.status_code, 409)

    def test_download_zips_outputs(self):
        job = Job.objects.create(
            style="economist", original_filename="p.pdf", status=Job.Status.DONE
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)
        (job.output_dir / "00-test.md").write_text("# hi", encoding="utf-8")
        resp = self.client.get(f"/api/jobs/{job.id}/download")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("bilingual.zip", resp["Content-Disposition"])


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
