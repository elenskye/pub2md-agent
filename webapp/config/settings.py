"""Django settings for the pub2md web app (2.0 Phase 2).

Thin-shell principle: this layer wraps and calls the existing Agent
(`src/...`) — it owns HTTP, jobs, auth (Phase 3) and files, never
translation logic. Secrets and knobs come from the same repo-root .env the
CLI uses.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # webapp/
REPO_ROOT = BASE_DIR.parent

# Make the Agent importable and share the CLI's .env.
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target; whitenoise serves it
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# --- production hardening (active when DJANGO_DEBUG=false) --------------
if not DEBUG:
    if SECRET_KEY == "dev-only-insecure-key":
        raise RuntimeError("Set DJANGO_SECRET_KEY in .env before running with DJANGO_DEBUG=false")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    # e.g. DJANGO_CSRF_TRUSTED_ORIGINS=https://pub2md.example.com
    CSRF_TRUSTED_ORIGINS = [
        o for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
    ]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Singapore"
USE_TZ = True

# --- pub2md-specific knobs ---------------------------------------------
# Per-job working data (uploads + generated markdown), outside the repo's
# CLI outputs/ so web jobs never collide with terminal runs.
JOBS_ROOT = Path(os.getenv("PUB2MD_JOBS_ROOT", REPO_ROOT / "var" / "webapp" / "jobs"))
MAX_UPLOAD_MB = int(os.getenv("PUB2MD_MAX_UPLOAD_MB", "25"))
MAX_PDF_PAGES = int(os.getenv("PUB2MD_MAX_PDF_PAGES", "100"))
# Hard monthly spend ceiling across all jobs (the API keys are the owner's).
MONTHLY_BUDGET_USD = float(os.getenv("PUB2MD_MONTHLY_BUDGET_USD", "5.0"))
# Housekeeping: terminal jobs (rows + files) are deleted after this many
# days; queued/running jobs older than this many minutes are marked failed.
JOB_RETENTION_DAYS = int(os.getenv("PUB2MD_JOB_RETENTION_DAYS", "7"))
JOB_STALE_MINUTES = int(os.getenv("PUB2MD_JOB_STALE_MINUTES", "45"))
