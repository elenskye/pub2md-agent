"""Command-line entry point.

Usage:
    python -m src.cli <pdf_path> [--style economist]

Observability: every run appends a structured record to logs/ (token usage,
cost, errors, new glossary terms). Full step-by-step traces go to LangSmith
when LANGSMITH_TRACING is set in .env — see .env.example.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from src.agent.graph import build_graph
from src.config import load_settings
from src.styles import available_styles
from src.tools.pdf_layout_parser import PDFExtractionError

LOGS_DIR = Path("logs")


def _write_run_log(args, settings, final: dict, seconds: float) -> Path:
    usage = final.get("token_usage", [])
    tin = sum(u["input_tokens"] for u in usage)
    tout = sum(u["output_tokens"] for u in usage)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pdf": args.pdf_path,
        "style": args.style,
        "provider": settings.provider,
        "model": settings.model,
        "seconds": round(seconds, 1),
        "articles": [
            {k: r[k] for k in ("title", "output_path", "n_paragraphs", "n_failed", "mode")}
            for r in final.get("results", [])
        ],
        "new_terms": final.get("new_terms", []),
        "errors": final.get("errors", []),
        "llm_calls": len(usage),
        "tokens": {"input": tin, "output": tout},
        "est_cost_usd": round(
            tin / 1e6 * settings.price_input_per_m + tout / 1e6 * settings.price_output_per_m, 4
        ),
    }
    LOGS_DIR.mkdir(exist_ok=True)
    path = LOGS_DIR / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _print_summary(final: dict, settings) -> None:
    results = final.get("results", [])
    print(f"\n=== pub2md-agent run summary ===")
    print(f"Articles written: {len(results)}")
    for r in sorted(results, key=lambda r: r["output_path"]):
        failed = f"  ({r['n_failed']} paragraph(s) FAILED)" if r["n_failed"] else ""
        print(f"  - {r['output_path']}  [{r['n_paragraphs']} paragraphs]{failed}")

    new_terms = final.get("new_terms", [])
    if new_terms:
        print(f"\nNew glossary terms this run ({len(new_terms)}):")
        for t in new_terms:
            review = "  ← REVIEW (llm_fallback)" if t["source"] == "llm_fallback" else ""
            print(f"  + {t['en']} => {t['zh']}  [{t['source']}]{review}")

    errors = final.get("errors", [])
    if errors:
        print(f"\nWarnings/errors ({len(errors)}):")
        for e in errors:
            print(f"  ! {e}")

    usage = final.get("token_usage", [])
    tin = sum(u["input_tokens"] for u in usage)
    tout = sum(u["output_tokens"] for u in usage)
    cost = tin / 1e6 * settings.price_input_per_m + tout / 1e6 * settings.price_output_per_m
    print(f"\nLLM calls: {len(usage)} · tokens in/out: {tin}/{tout} · est. cost: ${cost:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="pub2md-agent")
    parser.add_argument("pdf_path", help="Path to the input PDF")
    parser.add_argument(
        "--style",
        default="economist",
        choices=available_styles(),  # derived from src/prompts/*_style.md
        help="Translation style preset",
    )
    args = parser.parse_args()

    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"error: {exc} (see .env.example)", file=sys.stderr)
        return 1

    if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
        print(f"LangSmith tracing ON (project: {os.getenv('LANGSMITH_PROJECT', 'default')})")

    graph = build_graph()
    t0 = time.time()
    try:
        final = graph.invoke(
            {"pdf_path": args.pdf_path, "style": args.style},
            config={"recursion_limit": 100},
        )
    except PDFExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_summary(final, settings)
    log_path = _write_run_log(args, settings, final, time.time() - t0)
    print(f"Run log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
