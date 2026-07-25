"""ProgressTracker semantics + node plumbing (batch-level progress bar)."""

from src.agent.nodes import body_gatekeeper as bg
from src.tools.progress import ProgressTracker, tracker_from


class TestTracker:
    def test_empty_tracker(self):
        t = ProgressTracker()
        assert not t.started()
        assert t.fraction("translate") == 0.0

    def test_pools_are_independent(self):
        t = ProgressTracker()
        t.add_total("gatekeeper", 1)
        t.add_done("gatekeeper")
        t.add_total("translate", 4)
        t.add_done("translate")
        # the finished gatekeeper pool must not saturate the translate pool
        assert t.fraction("gatekeeper") == 1.0
        assert t.fraction("translate") == 0.25
        assert t.started()

    def test_over_completion_capped(self):
        t = ProgressTracker()
        t.add_total("translate", 2)
        t.add_done("translate", 5)
        assert t.fraction("translate") == 1.0

    def test_tracker_from_config(self):
        t = ProgressTracker()
        assert tracker_from({"configurable": {"progress_tracker": t}}) is t
        assert tracker_from({"configurable": {}}) is None
        assert tracker_from(None) is None


class TestGatekeeperPlumbing:
    def test_batches_registered_and_ticked(self, monkeypatch):
        monkeypatch.setattr(bg, "_BATCH", 2)
        monkeypatch.setattr(
            bg,
            "_classify",
            lambda idx, paras: (
                {i: "body" for i in idx},
                {"node": "body_gatekeeper", "input_tokens": 0, "output_tokens": 0},
            ),
        )
        t = ProgressTracker()
        state = {
            "article": {"index": 0, "title": "T", "subtitle": "", "paragraphs": []},
            "english_paragraphs": ["a", "b", "c"],
            "english_headings": [False, False, False],
        }
        bg.body_gatekeeper(state, {"configurable": {"progress_tracker": t}})
        assert t.fraction("gatekeeper") == 1.0  # ceil(3/2)=2 batches, both ticked

    def test_failed_batch_still_ticks(self, monkeypatch):
        def boom(idx, paras):
            raise RuntimeError("down")

        monkeypatch.setattr(bg, "_classify", boom)
        t = ProgressTracker()
        state = {
            "article": {"index": 0, "title": "T", "subtitle": "", "paragraphs": []},
            "english_paragraphs": ["a"],
            "english_headings": [False],
        }
        bg.body_gatekeeper(state, {"configurable": {"progress_tracker": t}})
        assert t.fraction("gatekeeper") == 1.0  # fail-open batches must not stall the bar
