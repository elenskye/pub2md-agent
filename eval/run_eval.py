"""Agent-vs-baseline evaluation runner (spec section 7).

Baseline: raw extracted PDF text (no column reflow, no noise stripping, no
segmentation, no glossary) handed to the LLM in one shot with a generic
"translate this" prompt. The baseline gets one output file per PDF no matter
how many articles it contains — that IS one of its failure modes.

Usage (batch-friendly, no time pressure — spec 4.1.5):
    python -m eval.run_eval [--skip-baseline] [--skip-judge] [--only <substr>]

Results land in eval/results/: per-item markdown for the baseline plus a
summary.json with every metric; agent outputs stay in outputs/.
"""

import argparse
import json
import time
from pathlib import Path

import pymupdf

from src.agent.graph import build_graph
from src.config import get_chat_model, load_settings
from src.tools.glossary_store import load_merged_glossary
from eval.metrics import (
    adherence_rate,
    consistency_rate,
    judge_pairs,
    paragraph_boundary_f1,
    term_occurrences,
)

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"

# Baseline input cap: bounds cost and keeps the comparison honest — beyond
# this the single-shot output would truncate at max_tokens anyway.
_BASELINE_INPUT_CHARS = 12000

_BASELINE_PROMPT = (
    "Translate the following text into Simplified Chinese:\n\n{text}"
)


def _usage_cost(usage: list[dict], settings) -> float:
    tin = sum(u["input_tokens"] for u in usage)
    tout = sum(u["output_tokens"] for u in usage)
    return tin / 1e6 * settings.price_input_per_m + tout / 1e6 * settings.price_output_per_m


def _run_agent(pdf_path: str, base_style: str, domains: list[str], settings) -> dict:
    graph = build_graph()
    t0 = time.time()
    final = graph.invoke(
        {"pdf_path": pdf_path, "base_style": base_style, "domains": domains},
        config={"recursion_limit": 100},
    )
    results = final.get("results", [])
    all_pairs = [p for r in results for p in r["pairs"]]
    return {
        "articles": len(results),
        "failed_paragraphs": sum(r["n_failed"] for r in results),
        "pairs": all_pairs,
        "en_paragraphs": [p["en"] for p in all_pairs if p.get("en")],
        "errors": final.get("errors", []),
        "cost_usd": round(_usage_cost(final.get("token_usage", []), settings), 4),
        "seconds": round(time.time() - t0, 1),
    }


def _run_baseline(pdf_path: str, out_path: Path, settings) -> dict:
    doc = pymupdf.open(pdf_path)
    raw = "\n".join(page.get_text() for page in doc)
    doc.close()
    raw = raw[:_BASELINE_INPUT_CHARS]
    llm = get_chat_model(max_tokens=8192)
    t0 = time.time()
    resp = llm.invoke(_BASELINE_PROMPT.format(text=raw))
    out_path.write_text(resp.content, encoding="utf-8")
    u = resp.usage_metadata or {}
    usage = [
        {
            "node": "baseline",
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
        }
    ]
    return {
        "articles": 1,  # single-shot always produces one blob
        "source_text": raw,
        "translation": resp.content,
        "truncated": resp.response_metadata.get("finish_reason") == "length",
        "cost_usd": round(_usage_cost(usage, settings), 4),
        "seconds": round(time.time() - t0, 1),
    }


def _baseline_occurrences(source: str, translation: str, glossary: dict) -> list[dict]:
    """Doc-level adherence: the baseline output has no paragraph alignment,
    so a term counts as adherent if its glossary rendering appears anywhere."""
    pair = [{"en": source, "zh": translation, "failed": False}]
    return term_occurrences(pair, glossary)


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--only", default="", help="substring filter on PDF name")
    args = parser.parse_args()

    settings = load_settings()
    manifest = json.loads((EVAL_DIR / "manifest.json").read_text(encoding="utf-8"))
    items = [i for i in manifest["items"] if args.only in i["pdf"]]
    RESULTS_DIR.mkdir(exist_ok=True)

    summary: list[dict] = []
    agent_occurrences: list[dict] = []
    baseline_occurrences: list[dict] = []

    for item in items:
        pdf_path = str(EVAL_DIR / item["pdf"])
        stem = Path(pdf_path).stem
        glossary = load_merged_glossary(item["domains"])
        print(
            f"\n=== {stem} (style={item['base_style']} × {'+'.join(item['domains'])}, "
            f"expect {item['expected_articles']} articles)"
        )

        record: dict = {
            "pdf": item["pdf"],
            "base_style": item["base_style"],
            "domains": item["domains"],
        }

        agent = _run_agent(pdf_path, item["base_style"], item["domains"], settings)
        occ = term_occurrences(agent["pairs"], glossary)
        agent_occurrences.extend(occ)
        adh, n_occ = adherence_rate(occ)
        record["agent"] = {
            "split_ok": agent["articles"] == item["expected_articles"],
            "articles": agent["articles"],
            "failed_paragraphs": agent["failed_paragraphs"],
            "glossary_adherence": round(adh, 3),
            "term_occurrences": n_occ,
            "paragraph_boundary_f1": paragraph_boundary_f1(agent["en_paragraphs"], pdf_path),
            "cost_usd": agent["cost_usd"],
            "seconds": agent["seconds"],
        }
        if not args.skip_judge:
            record["agent"]["judge"] = judge_pairs(agent["pairs"])
        print(f"  agent: {record['agent']}")

        if not args.skip_baseline:
            out_path = RESULTS_DIR / f"baseline-{stem}.md"
            base = _run_baseline(pdf_path, out_path, settings)
            occ_b = _baseline_occurrences(base["source_text"], base["translation"], glossary)
            baseline_occurrences.extend(occ_b)
            adh_b, n_b = adherence_rate(occ_b)
            record["baseline"] = {
                "split_ok": base["articles"] == item["expected_articles"],
                "articles": base["articles"],
                "truncated": base["truncated"],
                "glossary_adherence": round(adh_b, 3),
                "term_occurrences": n_b,
                "cost_usd": base["cost_usd"],
                "seconds": base["seconds"],
            }
            if not args.skip_judge:
                record["baseline"]["judge"] = judge_pairs(
                    [{"en": base["source_text"][:1500], "zh": base["translation"][:1500]}],
                    max_samples=1,
                )
            print(f"  baseline: {record['baseline']}")

        summary.append(record)

    corpus = {
        "agent_terminology_consistency": dict(
            zip(("rate", "terms"), consistency_rate(agent_occurrences))
        ),
        "baseline_terminology_consistency": dict(
            zip(("rate", "terms"), consistency_rate(baseline_occurrences))
        ),
    }
    out = {"items": summary, "corpus": corpus}
    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("\n=== corpus-level ===")
    print(json.dumps(corpus, indent=2))
    print(f"\nFull summary: {RESULTS_DIR / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
