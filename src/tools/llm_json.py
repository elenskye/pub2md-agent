"""Parsing for almost-JSON emitted by LLMs.

DeepSeek produces malformed JSON even in JSON mode: a value ending with a
Chinese closing quote (”) deterministically loses its ASCII closing quote,
and long replies can truncate mid-string. Retrying the model does not help —
the defect is reproducible byte-for-byte — so the fix lives in the parser.
"""

import json


def strip_fences(content: str) -> str:
    return (
        content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    )


def loads_with_repair(text: str) -> dict:
    """Try the raw text, then the known tail repairs. The targeted repair
    (re-quoting before a final brace) must run before the blind suffix
    appends: `text + '"}'` also parses the missing-quote case but swallows
    the stray brace into the translation."""
    candidates = [text]
    stripped = text.rstrip()
    if stripped.endswith("}"):
        # Missing close-quote right before the final brace.
        candidates.append(stripped[:-1].rstrip() + '"}')
    candidates += [text + '"}', text + "}"]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            # strict=False tolerates literal newlines inside JSON strings.
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise last_error
