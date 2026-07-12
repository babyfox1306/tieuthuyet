"""Machine QC issue classification — format_fix vs content_fail."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.machine_qc import (
    classify_machine_issues,
    format_machine_reasons,
    has_content_fail,
    is_format_only_issues,
    machine_pass,
    machine_qc,
)


@contextmanager
def tempfile_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "books" / "01" / "pipeline" / "ready").mkdir(parents=True)
        yield ws


class ClassifyMachineIssuesTests(unittest.TestCase):
    def test_markdown_is_format_only(self):
        issues = {
            "markdown": ["*click*"],
            "word_count": 1500,
            "target_language": "en",
        }
        cls = classify_machine_issues(issues)
        self.assertTrue(cls["format_only"])
        self.assertTrue(is_format_only_issues(issues))
        self.assertFalse(has_content_fail(issues))

    def test_missing_quotes_is_format(self):
        issues = {"missing_quotes": True, "word_count": 1500}
        self.assertTrue(is_format_only_issues(issues))

    def test_pov_is_content(self):
        issues = {
            "pov_violation": {"count": 12, "threshold": 3},
            "word_count": 1500,
        }
        cls = classify_machine_issues(issues)
        self.assertTrue(cls["has_content"])
        self.assertFalse(cls["format_only"])
        self.assertTrue(has_content_fail(issues))

    def test_mixed_format_and_content(self):
        issues = {
            "markdown": ["*x*"],
            "name_drift": [{"found": "Bob", "canonical": "Robert"}],
            "word_count": 1500,
        }
        cls = classify_machine_issues(issues)
        self.assertFalse(cls["format_only"])
        self.assertTrue(cls["has_format"])
        self.assertTrue(cls["has_content"])

    def test_format_reasons_include_locations(self):
        text = "# Chapter 1: X\n\nThe *click* echoed.\n\n" + ("word " * 200)
        issues = machine_qc(text, min_words=100)
        self.assertIn("markdown", issues)
        self.assertIn("format_locations", issues)
        reasons = format_machine_reasons(issues)
        self.assertTrue(any("format_fix" in r for r in reasons))
        self.assertTrue(any("markdown" in r for r in reasons))


class DraftNoFormatRetryTests(unittest.TestCase):
    def test_format_only_calls_writer_once(self):
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"n": 0}

        def fake_router(role, payload, **kwargs):
            calls["n"] += 1
            body = "# Chapter 1: Test\n\nThe *click* echoed in the hall.\n\n" + ("word " * 400)
            return body, {}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 2,
            "writer_content_max_retries": 2,
            "banned_phrases": [],
        }
        with tempfile_workspace() as ws:
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.load_state",
                        return_value={"phrases_used": []},
                    ):
                        _chapter, issues = _draft_chapter_prose(
                            ws, 1, 1, cfg, {"target_language": "en"}
                        )
        self.assertEqual(calls["n"], 1)
        self.assertIn("markdown", issues)
        self.assertTrue(is_format_only_issues(issues))
        self.assertFalse(machine_pass(issues))

    def test_content_retries_capped_at_two(self):
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"n": 0}

        def fake_router(role, payload, **kwargs):
            calls["n"] += 1
            body = "# Chapter 1: Test\n\n" + ("I walked. My hands shook. " * 80)
            return body, {}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 0,
            "writer_content_max_retries": 2,
            "banned_phrases": [],
        }

        def fake_qc(text, **kwargs):
            return {
                "word_count": 500,
                "target_language": "en",
                "pov_violation": {"count": 20, "threshold": 3},
                "classification": {
                    "format_fix": {},
                    "content_fail": {"pov_violation": {"count": 20}},
                    "length": {},
                    "format_only": False,
                    "has_format": False,
                    "has_content": True,
                    "has_length": False,
                },
            }

        with tempfile_workspace() as ws:
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.load_state",
                        return_value={"phrases_used": []},
                    ):
                        with patch(
                            "factory.engine.run_factory.machine_qc",
                            side_effect=fake_qc,
                        ):
                            _chapter, issues = _draft_chapter_prose(
                                ws, 1, 1, cfg, {"target_language": "en"}
                            )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(issues.get("retry_meta", {}).get("content_attempts"), 2)
        self.assertEqual(issues.get("retry_meta", {}).get("max_content_retries"), 2)

    def test_auto_mode_content_retries_use_auto_max(self):
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"n": 0}

        def fake_router(role, payload, **kwargs):
            calls["n"] += 1
            body = "# Chapter 1: Test\n\n" + ("I walked. My hands shook. " * 80)
            return body, {}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 0,
            "writer_content_max_retries": 2,
            "writer_auto_max_retries": 10,
            "banned_phrases": [],
        }

        def fake_qc(text, **kwargs):
            return {
                "word_count": 500,
                "target_language": "en",
                "pov_violation": {"count": 20, "threshold": 3},
                "classification": {
                    "format_fix": {},
                    "content_fail": {"pov_violation": {"count": 20}},
                    "length": {},
                    "format_only": False,
                    "has_format": False,
                    "has_content": True,
                    "has_length": False,
                },
            }

        with tempfile_workspace() as ws:
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.load_state",
                        return_value={"phrases_used": []},
                    ):
                        with patch(
                            "factory.engine.run_factory.machine_qc",
                            side_effect=fake_qc,
                        ):
                            _chapter, issues = _draft_chapter_prose(
                                ws, 1, 1, cfg, {"target_language": "en"}, auto=True
                            )
        self.assertEqual(calls["n"], 10)
        self.assertEqual(issues.get("retry_meta", {}).get("content_attempts"), 10)
        self.assertEqual(issues.get("retry_meta", {}).get("max_content_retries"), 10)


if __name__ == "__main__":
    unittest.main()
