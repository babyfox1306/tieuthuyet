"""current_chapter: one writer (state_updater), approve must not bump it."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.engine.lib.export_gate import check_eg15_state_timeline
from factory.engine.lib.state_updater import (
    ensure_timeline_chapter_marker,
    last_timeline_chapter,
    load_state,
    record_promoted_chapter,
    save_state,
    state_chapter_divergence,
    update_state_after_pass,
)


def _ws_with_state(td: str, *, chapter: int = 4, timeline=None) -> Path:
    root = Path(td)
    ws = root / "workspaces" / "demo"
    book_dir = ws / "books" / "01"
    book_dir.mkdir(parents=True)
    (ws / "direction.yaml").write_text(
        "id: demo\ntarget_language: en\npen_name: Test Author\n",
        encoding="utf-8",
    )
    state = {
        "current_book": 1,
        "current_chapter": chapter,
        "timeline": timeline
        if timeline is not None
        else [f"Ch{i}: event" for i in range(1, chapter + 1)],
        "character_status": {},
        "open_threads": [],
        "facts_established": [],
        "spice_progression": "",
        "phrases_used": [],
        "promoted_chapters": [],
    }
    (book_dir / "state.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    return ws


class TimelineParseTests(unittest.TestCase):
    def test_last_timeline_chapter(self):
        self.assertEqual(last_timeline_chapter({"timeline": ["Ch4: foo", "Ch12 bar"]}), 12)
        self.assertEqual(last_timeline_chapter({"timeline": ["Chapter 3 — x"]}), 3)
        self.assertEqual(last_timeline_chapter({"timeline": []}), 0)

    def test_divergence_when_more_than_one_ahead(self):
        d = state_chapter_divergence(
            {"current_chapter": 12, "timeline": ["Ch4: moss"]}
        )
        self.assertTrue(d["divergent"])
        self.assertEqual(d["ahead_by"], 8)

    def test_no_divergence_when_one_ahead(self):
        # current=5, timeline=4 → ahead by 1 → OK (in flight)
        d = state_chapter_divergence(
            {"current_chapter": 5, "timeline": ["Ch4: done"]}
        )
        self.assertFalse(d["divergent"])

    def test_no_divergence_aligned(self):
        d = state_chapter_divergence(
            {"current_chapter": 4, "timeline": ["Ch4: done"]}
        )
        self.assertFalse(d["divergent"])

    def test_unlabeled_nonempty_timeline_not_false_positive(self):
        """Real state_updater output omits ChN: — must not report timeline ch0."""
        d = state_chapter_divergence(
            {
                "current_chapter": 3,
                "timeline": [
                    "Sloane wakes on the rooftop",
                    "Lucian removes his mask",
                    "Seven lines on the magazine",
                ],
            }
        )
        self.assertFalse(d["divergent"])
        self.assertEqual(d["timeline_chapter"], 3)

    def test_empty_timeline_with_leading_counter_is_divergent(self):
        d = state_chapter_divergence({"current_chapter": 3, "timeline": []})
        self.assertTrue(d["divergent"])
        self.assertEqual(d["timeline_chapter"], 0)

    def test_ensure_timeline_chapter_marker_prefixes_last_unlabeled(self):
        out = ensure_timeline_chapter_marker(
            ["Sloane wakes", "Lucian speaks"], 3
        )
        self.assertEqual(out[0], "Sloane wakes")
        self.assertTrue(out[1].startswith("Ch3:"))
        self.assertIn("Lucian speaks", out[1])


class ApproveDoesNotBumpTests(unittest.TestCase):
    def test_record_promoted_leaves_current_chapter(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _ws_with_state(td, chapter=4)
            out = record_promoted_chapter(ws, 1, 12)
            self.assertEqual(out["current_chapter"], 4)
            self.assertIn(12, out["promoted_chapters"])
            reloaded = load_state(ws, 1)
            self.assertEqual(reloaded["current_chapter"], 4)
            self.assertEqual(reloaded["promoted_chapters"], [12])

    def test_chapter_approve_does_not_bump_counter(self):
        """Path B: approve → catalog only; state.current_chapter unchanged."""
        from factory.ui import factory_workflow as fw

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspaces" / "demo"
            book_dir = ws / "books" / "01"
            ready = book_dir / "pipeline" / "ready"
            ready.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                "id: demo\ntarget_language: en\n", encoding="utf-8"
            )
            save_state(
                ws,
                1,
                {
                    "current_book": 1,
                    "current_chapter": 4,
                    "timeline": ["Ch4: frozen"],
                    "promoted_chapters": [],
                },
            )
            prose = (
                "---\nchapter: 12\ntitle: Far Ahead\nbook: 1\n---\n\n"
                + ("word " * 400)
            )
            (ready / "ch_012.txt").write_text(prose, encoding="utf-8")

            with mock.patch.object(fw, "workspace_dir", return_value=ws), mock.patch(
                "factory.ui.factory_workflow.promote_chapter",
                return_value=(Path("/fake/ch12.md"), []),
            ), mock.patch.object(
                fw,
                "chapter_get",
                return_value={"chapter": 12, "status": "catalog", "title": "Far Ahead"},
            ), mock.patch.object(fw, "_catalog_chapter_path", return_value=None):
                result = fw.chapter_approve("demo", 12, book=1)

            self.assertTrue(result.get("ok"))
            st = load_state(ws, 1)
            self.assertEqual(
                st["current_chapter"],
                4,
                "approve must not bump current_chapter",
            )
            self.assertIn(12, st.get("promoted_chapters") or [])


class UpdaterFailDoesNotAdvanceTests(unittest.TestCase):
    def test_json_fail_leaves_state_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _ws_with_state(td, chapter=4)
            with mock.patch(
                "factory.engine.lib.state_updater.call_9router",
                return_value=("NOT JSON {{{", {}),
            ), mock.patch(
                "factory.engine.lib.state_updater.parse_json_response",
                side_effect=json.JSONDecodeError("nope", "doc", 0),
            ), mock.patch(
                "factory.engine.lib.state_updater.load_direction",
                return_value={"target_language": "en"},
            ):
                out = update_state_after_pass(ws, 5, "chapter text " * 50, book=1)

            self.assertEqual(out["current_chapter"], 4)
            self.assertEqual(load_state(ws, 1)["current_chapter"], 4)
            # Must not have appended fallback timeline lie
            self.assertEqual(len(load_state(ws, 1)["timeline"]), 4)

    def test_success_advances_with_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _ws_with_state(td, chapter=4)
            llm_state = {
                "current_book": 1,
                "current_chapter": 99,  # ignored — writer forces chapter_num
                "timeline": ["Ch1: a", "Ch2: b", "Ch3: c", "Ch4: d", "Ch5: new"],
                "facts_established": ["feather stays"],
                "character_status": {},
                "open_threads": [],
                "spice_progression": "",
                "phrases_used": [],
            }
            with mock.patch(
                "factory.engine.lib.state_updater.call_9router",
                return_value=(json.dumps(llm_state), {}),
            ), mock.patch(
                "factory.engine.lib.state_updater.parse_json_response",
                return_value=llm_state,
            ), mock.patch(
                "factory.engine.lib.state_updater.load_direction",
                return_value={"target_language": "en"},
            ), mock.patch(
                "factory.engine.lib.canon_registry.validate_story_state_cast",
                return_value=[],
            ):
                out = update_state_after_pass(ws, 5, "chapter text " * 50, book=1)

            self.assertEqual(out["current_chapter"], 5)
            self.assertEqual(last_timeline_chapter(out), 5)


class Eg15ExportBlockTests(unittest.TestCase):
    def test_eg15_fails_when_divergent(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _ws_with_state(
                td,
                chapter=12,
                timeline=["Ch4: only"],
            )
            with mock.patch(
                "factory.engine.paths.workspace_dir", return_value=ws
            ):
                check = check_eg15_state_timeline("demo", "01-the-barrow-stone")
            self.assertEqual(check["id"], "EG-15")
            self.assertFalse(check["passed"])
            self.assertIn("current_chapter=12", check["detail"])

    def test_eg15_passes_when_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _ws_with_state(td, chapter=4)
            with mock.patch(
                "factory.engine.paths.workspace_dir", return_value=ws
            ):
                check = check_eg15_state_timeline("demo", "01-demo")
            self.assertTrue(check["passed"])


if __name__ == "__main__":
    unittest.main()
