import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.state_updater import (
    record_approved_chapter,
    state_chapter_divergence,
)


class StateApprovalAlignmentTests(unittest.TestCase):
    def test_lightweight_approval_records_labeled_timeline_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            state = record_approved_chapter(ws, 15, book=1)

            self.assertEqual(state["current_chapter"], 15)
            self.assertEqual(
                state["timeline"],
                ["Ch15: approved via UI (state summary deferred)"],
            )
            self.assertFalse(state_chapter_divergence(state)["divergent"])

    def test_repeated_approval_does_not_duplicate_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            record_approved_chapter(ws, 3, book=1)
            state = record_approved_chapter(ws, 3, book=1)

            self.assertEqual(len(state["timeline"]), 1)


if __name__ == "__main__":
    unittest.main()
