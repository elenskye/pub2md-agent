"""Report cross-domain glossary conflicts for this run (no LLM involved).

Runs once in the parent graph before the article fan-out: when the user
selects several domains and they disagree on a term's translation, the
merge silently follows the selection order — this node makes that choice
visible in the run summary so cross-domain runs are never surprising.
"""

from src.agent.state import PipelineState
from src.tools.glossary_store import merge_with_conflicts


def glossary_conflict_auditor(state: PipelineState) -> dict:
    _, conflicts = merge_with_conflicts(state["domains"])
    return {"glossary_conflicts": conflicts}
