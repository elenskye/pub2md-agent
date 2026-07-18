"""Single source of truth for the two-axis style model (v3 Phase 1).

Base styles (tone, layout, translation conventions) are derived from the
prompt files on disk: adding one means dropping in
src/prompts/<name>_style.md. Domains (which terminology glossaries load)
are derived from the seed glossary files: adding one means dropping in
data/glossary_<domain>.json. The CLI choices, the web UI's selectors and
the request validation all read from here, so no interface code changes
are needed for either axis.

Any base style × domain combination is allowed; DEFAULT_DOMAINS only
provides the preselected guidance in the interfaces.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Preselected domains per base style — guidance, not a restriction.
DEFAULT_DOMAINS = {
    "economist": ["econ"],
    "academy": ["cs"],
}


def available_base_styles() -> list[str]:
    return sorted(p.stem.removesuffix("_style") for p in PROMPTS_DIR.glob("*_style.md"))


def available_domains() -> list[str]:
    return sorted(
        p.stem.removeprefix("glossary_")
        for p in DATA_DIR.glob("glossary_*.json")
        if not p.stem.endswith("_rejected")
    )


def default_domains(base_style: str) -> list[str]:
    """Preselected domains for a base style; falls back to the first
    available domain so a fresh style name still yields a valid job."""
    defaults = DEFAULT_DOMAINS.get(base_style, [])
    known = available_domains()
    picked = [d for d in defaults if d in known]
    return picked or known[:1]
