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
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [],
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
