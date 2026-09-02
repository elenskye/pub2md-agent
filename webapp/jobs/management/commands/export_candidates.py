"""Export the glossary terms this deployment grew, for an offline audit.

    python manage.py export_candidates [--domain cs] [--output batch.json]

Server-side half of the closed loop (v3 Phase 5): runtime terms are stored
with status=candidate, this dumps them as a JSON batch, and the owner merges
it into his local store with

    python -m scripts.audit_glossary --import-batch batch.json

audits it, and ships the regenerated seed JSON back to that installation.
The same batch is downloadable from GET /api/glossary/candidates behind the
login, so the owner never has to SSH in just to collect terms.
"""

import json

from django.core.management.base import BaseCommand

from src.styles import available_domains
from src.tools.glossary_store import candidate_batch


class Command(BaseCommand):
    help = "Export candidate glossary terms as a JSON batch for offline audit"

    def add_arguments(self, parser):
        parser.add_argument("--domain", choices=available_domains(), default=None)
        parser.add_argument("--output", default=None, help="File to write (default: stdout)")

    def handle(self, *args, **options):
        batch = candidate_batch([options["domain"]] if options["domain"] else None)
        payload = json.dumps(batch, ensure_ascii=False, indent=2) + "\n"
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as fh:
                fh.write(payload)
            self.stdout.write(
                self.style.SUCCESS(
                    f"exported {len(batch['terms'])} candidate(s) → {options['output']}"
                )
            )
        else:
            self.stdout.write(payload)
