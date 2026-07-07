"""Write one bilingual Markdown file per article into outputs/."""

import re
from pathlib import Path

from src.agent.state import ArticleResult, ArticleState

DEFAULT_OUTPUT_DIR = "outputs"


def _slugify(title: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^A-Za-z0-9一-鿿]+", "-", title).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def output_writer(state: ArticleState) -> dict:
    out_dir = Path(state.get("output_dir") or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    article = state["article"]

    # Index prefix keeps names unique within a run (branches run in parallel)
    # and makes re-runs overwrite deterministically instead of piling up -2/-3.
    path = out_dir / f"{article['index']:02d}-{_slugify(article['title'])}.md"
    path.write_text(state["bilingual_md"], encoding="utf-8")
    pairs = state["translated_paragraphs"]
    result = ArticleResult(
        title=article["title"],
        output_path=str(path),
        n_paragraphs=len(pairs),
        n_failed=sum(1 for p in pairs if p["failed"]),
        mode=state.get("output_mode", "bilingual"),
        pairs=pairs,
    )
    return {"results": [result]}
