"""Pieces shared by the two translation paths (PDF articles and .md files).

Pure helpers only — batching, glossary constraint blocks and reply parsing.
The nodes keep their own orchestration (retries, concurrency, progress), so
this module has no LLM calls and no state coupling.
"""

from pathlib import Path

from src.tools.llm_json import loads_with_repair, strip_fences

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

BATCH_MAX_SEGMENTS = 12
BATCH_MAX_CHARS = 4000


def load_style_prompt(style: str) -> str:
    return (_PROMPTS_DIR / f"{style}_style.md").read_text(encoding="utf-8")


def batches(items: list[str], indices: list[int]) -> list[list[int]]:
    """Split the given segment indices into batches bounded by count/chars."""
    out: list[list[int]] = [[]]
    chars = 0
    for i in indices:
        text = items[i]
        if out[-1] and (len(out[-1]) >= BATCH_MAX_SEGMENTS or chars + len(text) > BATCH_MAX_CHARS):
            out.append([])
            chars = 0
        out[-1].append(i)
        chars += len(text)
    return [b for b in out if b]


def glossary_hits(glossary: dict, text: str, limit: int = 40) -> list[dict]:
    """Glossary terms that actually occur in this document (cost control: the
    glossary grows across runs, the prompt must not grow with it)."""
    lower = text.lower()
    return [t for key, t in sorted(glossary.items()) if key in lower][:limit]


def glossary_constraints(hits: list[dict]) -> str:
    """Constraint block appended to the style system prompt."""
    if not hits:
        return ""
    lines = "\n".join(f"- {t['en']} => {t['zh']}" for t in hits)
    return (
        "\n\nGlossary — use these exact translations for these terms, "
        "without exception:\n" + lines
    )


def parse_reply(content: str, expected: list[int]) -> dict[int, str]:
    """Parse a numbered JSON reply, insisting every requested segment is
    present — that echo is what guarantees source/translation alignment."""
    raw = loads_with_repair(strip_fences(content))
    out = {int(k): str(v).strip() for k, v in raw.items()}
    missing = [i for i in expected if i + 1 not in out or not out[i + 1]]
    if missing:
        raise ValueError(f"segments missing from reply: {[i + 1 for i in missing]}")
    return out
