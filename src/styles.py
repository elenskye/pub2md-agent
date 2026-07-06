"""Single source of truth for the available style presets.

Styles are derived from the prompt files on disk: adding a new style means
dropping in src/prompts/<name>_style.md (plus a seed glossary) — the CLI
choices and, in 2.0, the web UI's style selector and request validation all
read from here, so no interface code changes are needed.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def available_styles() -> list[str]:
    return sorted(p.stem.removesuffix("_style") for p in PROMPTS_DIR.glob("*_style.md"))
