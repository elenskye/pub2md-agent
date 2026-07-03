"""Command-line entry point.

Usage:
    python -m src.cli <pdf_path> [--style economist]
"""

import argparse
import sys

from src.agent.graph import build_graph
from src.config import load_settings
from src.tools.pdf_layout_parser import PDFExtractionError


def _print_summary(final: dict, settings) -> None:
    results = final.get("results", [])
    print(f"\n=== pub2md-agent run summary ===")
    print(f"Articles written: {len(results)}")
    for r in sorted(results, key=lambda r: r["output_path"]):
        failed = f"  ({r['n_failed']} paragraph(s) FAILED)" if r["n_failed"] else ""
        print(f"  - {r['output_path']}  [{r['n_paragraphs']} paragraphs]{failed}")

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
        choices=["economist", "academy"],
        help="Translation style preset",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.api_key:
        print("error: DEEPSEEK_API_KEY is not set (see .env.example)", file=sys.stderr)
        return 1

    graph = build_graph()
    try:
        final = graph.invoke(
            {"pdf_path": args.pdf_path, "style": args.style},
            config={"recursion_limit": 100},
        )
    except PDFExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_summary(final, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
