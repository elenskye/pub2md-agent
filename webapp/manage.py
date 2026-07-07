#!/usr/bin/env python
"""Django management entry point for the pub2md web app."""

import os
import sys
from pathlib import Path

# The Django project lives in webapp/, the Agent lives in <repo>/src — make
# the repo root importable so `from src.agent.graph import ...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
