"""Fine-grained run progress shared between pipeline nodes and the webapp.

The parent graph only reports node completions, which makes a one-article
academic paper's progress bar jump from 35% straight to done. Nodes that
do the long batched LLM work (translator, body_gatekeeper) register their
batches on a ProgressTracker passed through the LangGraph config
(configurable["progress_tracker"]) and tick them off as they finish; the
webapp polls the tracker while the run streams and maps its fraction onto
the 35–95 band. The CLI passes no tracker and nothing changes.

Work units live in named POOLS ("gatekeeper", "translate") that the
consumer weights separately: with a single shared pool, the gatekeeper's
one early batch completes first and saturates the fraction before the
translator has even registered its batches (observed: the bar sat at 95%
for the whole translation). Totals accumulate as parallel article
branches register, so a pool's fraction can momentarily dip — consumers
must keep the displayed percent monotonic.
"""

import threading


class ProgressTracker:
    """Thread-safe per-pool counters of pending/finished LLM work units."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total: dict[str, int] = {}
        self._done: dict[str, int] = {}

    def add_total(self, pool: str, n: int) -> None:
        with self._lock:
            self._total[pool] = self._total.get(pool, 0) + n

    def add_done(self, pool: str, n: int = 1) -> None:
        with self._lock:
            self._done[pool] = self._done.get(pool, 0) + n

    def started(self) -> bool:
        with self._lock:
            return bool(self._total)

    def fraction(self, pool: str) -> float:
        with self._lock:
            total = self._total.get(pool, 0)
            if total == 0:
                return 0.0
            return min(self._done.get(pool, 0) / total, 1.0)


def tracker_from(config) -> ProgressTracker | None:
    """Extract the tracker from a LangGraph RunnableConfig, if any."""
    if not config:
        return None
    return config.get("configurable", {}).get("progress_tracker")
