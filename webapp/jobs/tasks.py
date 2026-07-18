"""Background execution of translation jobs.

A single-worker ThreadPoolExecutor keeps the service one process with zero
extra infrastructure (no Redis/Celery — right-sized for two trusted users):
jobs run strictly one at a time, which also serializes glossary writes and
caps the spend rate. Job state lives in the database, so the HTTP layer
only ever reads rows.

Progress comes from streaming the LangGraph run (stream_mode="values"):
each intermediate state snapshot tells us which pipeline stage the run has
reached without touching Agent internals.
"""

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

from django.utils import timezone

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pub2md-job")


def submit(job_id) -> None:
    _EXECUTOR.submit(_run_safely, job_id)


def _stage_of(state: dict) -> str:
    """Human-readable stage derived from which state fields exist so far."""
    results = state.get("results")
    articles = state.get("articles")
    if results is not None and articles:
        if len(results) >= len(articles):
            return f"finished {len(results)} article(s)"
        return f"translating: {len(results)}/{len(articles)} article(s) done"
    if articles:
        return f"segmented {len(articles)} article(s), translating"
    if state.get("cleaned_text"):
        return "cleaning layout & transcribing formulas"
    if state.get("raw_blocks"):
        return "parsing PDF layout"
    return "starting"


def _run_safely(job_id) -> None:
    from .models import Job

    job = Job.objects.get(id=job_id)
    job.status = Job.Status.RUNNING
    job.started_at = timezone.now()
    job.progress = "starting"
    job.save(update_fields=["status", "started_at", "progress"])
    try:
        _run(job)
    except Exception as exc:  # noqa: BLE001 — job must never crash the worker
        logger.exception("job %s failed", job_id)
        job.status = Job.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        logger.debug(traceback.format_exc())


def _run(job) -> None:
    import pymupdf
    from django.conf import settings as dj_settings

    from src.agent.graph import build_graph
    from src.config import load_settings

    from .models import Job

    # Cheap structural guard before spending any tokens.
    with pymupdf.open(job.input_path) as doc:
        if len(doc) > dj_settings.MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has {len(doc)} pages, above the {dj_settings.MAX_PDF_PAGES}-page limit"
            )

    agent_settings = load_settings()
    job.output_dir.mkdir(parents=True, exist_ok=True)

    graph = build_graph()
    state: dict = {}
    for snapshot in graph.stream(
        {
            "pdf_path": str(job.input_path),
            "base_style": job.base_style,
            "domains": job.domains,
            "output_dir": str(job.output_dir),
        },
        config={"recursion_limit": 100},
        stream_mode="values",
    ):
        state = snapshot
        stage = _stage_of(state)
        if stage != job.progress:
            job.progress = stage
            job.save(update_fields=["progress"])

    usage = state.get("token_usage", [])
    tokens_in = sum(u["input_tokens"] for u in usage)
    tokens_out = sum(u["output_tokens"] for u in usage)
    job.cost_usd = (
        tokens_in / 1e6 * agent_settings.price_input_per_m
        + tokens_out / 1e6 * agent_settings.price_output_per_m
    )
    job.result = {
        "articles": [
            {k: r[k] for k in ("title", "n_paragraphs", "n_failed", "mode")}
            | {"filename": r["output_path"].rsplit("/", 1)[-1]}
            for r in state.get("results", [])
        ],
        "new_terms": state.get("new_terms", []),
        "errors": state.get("errors", []),
        "llm_calls": len(usage),
        "tokens": {"input": tokens_in, "output": tokens_out},
    }
    job.status = Job.Status.DONE
    job.progress = f"finished {len(job.result['articles'])} article(s)"
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "progress", "result", "cost_usd", "finished_at"])
