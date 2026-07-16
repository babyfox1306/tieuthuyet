"""Machine QC issue classification — format_fix vs content_fail."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.machine_qc import (
    classify_machine_issues,
    expects_low_dialogue,
    find_missing_dialogue_quote_hits,
    format_machine_reasons,
    has_content_fail,
    is_format_only_issues,
    issues_to_needs_fix,
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
    def test_markdown_advisory_not_format_only(self):
        issues = {
            "markdown_advisory": [{"id": 0, "kind": "italic", "match": "*click*"}],
            "word_count": 1500,
            "target_language": "en",
        }
        cls = classify_machine_issues(issues)
        self.assertFalse(cls["format_only"])
        self.assertFalse(cls["has_format"])
        self.assertFalse(has_content_fail(issues))
        self.assertNotIn("markdown", issues_to_needs_fix(issues))

    def test_quotes_advisory_not_format(self):
        issues = {"quotes_advisory": [{"line": 1, "snippet": "he said"}], "word_count": 1500}
        self.assertFalse(is_format_only_issues(issues))
        self.assertFalse(classify_machine_issues(issues)["has_format"])
        self.assertEqual(issues_to_needs_fix(issues), [])

    def test_pov_is_content(self):
        issues = {
            "pov_violation": {"count": 12, "threshold": 3},
            "word_count": 1500,
        }
        cls = classify_machine_issues(issues)
        self.assertTrue(cls["has_content"])
        self.assertFalse(cls["format_only"])
        self.assertTrue(has_content_fail(issues))

    def test_legacy_missing_quotes_key_not_format(self):
        """Stale key must not re-enter format_fix after advisory downgrade."""
        issues = {
            "missing_quotes": True,
            "name_drift": [{"found": "Bob", "canonical": "Robert"}],
            "word_count": 1500,
        }
        cls = classify_machine_issues(issues)
        self.assertFalse(cls["has_format"])
        self.assertTrue(cls["has_content"])
        self.assertNotIn("missing_quotes:dialogue", issues_to_needs_fix(issues))

    def test_markdown_advisory_does_not_block_machine_pass(self):
        text = "# Chapter 1: X\n\nThe *click* echoed.\n\n" + ("word\n" * 200)
        issues = machine_qc(text, min_words=100)
        self.assertIn("markdown_advisory", issues)
        self.assertNotIn("markdown", issues)
        self.assertTrue(machine_pass(issues))
        reasons = format_machine_reasons(issues)
        self.assertTrue(any("markdown advisory" in r for r in reasons))
        self.assertEqual(issues_to_needs_fix(issues), [])


class DialogueQuoteHeuristicTests(unittest.TestCase):
    def _isolation_plan(self) -> dict:
        return {
            "chapter": 3,
            "must_happen": [
                "[ISOLATION] Clara finds an old note and realizes there is no living witness.",
                "Clara maps contamination with catalogue numbers only.",
            ],
            "spice_note": "No romance; tension from isolation and grief.",
            "chapter_task": "Solo POV catalogue notes; near-zero dialogue except mandated opener.",
            "opens_with": '"Stay where I put you," Clara snapped, and drove the paperweight down.',
        }

    def _isolation_chapter_prose(self) -> str:
        opener = (
            '"Stay where I put you," Clara snapped, and drove the paperweight down '
            "before the ledger crawled another inch."
        )
        para = (
            "Clara numbered the plates by habit. The corridor stayed empty. "
            "She wrote contamination notes in the catalogue and did not speak again. "
            "Black veins threaded the glass while she worked alone with blotting paper "
            "and weights, recording each surface as if order could hold the room still."
        )
        return "# Chapter 3: The Ashless Room\n\n" + opener + "\n\n" + "\n\n".join([para] * 40)

    def test_isolation_single_quote_chapter_passes(self):
        plan = self._isolation_plan()
        text = self._isolation_chapter_prose()
        self.assertTrue(expects_low_dialogue(plan=plan))
        hits = find_missing_dialogue_quote_hits(text, plan=plan)
        self.assertEqual(hits, [])
        issues = machine_qc(text, min_words=100, plan=plan)
        self.assertNotIn("quotes_advisory", issues)
        self.assertNotIn("missing_quotes", issues)
        self.assertEqual(issues_to_needs_fix(issues), [])
        self.assertTrue(machine_pass(issues))

    def test_sparse_quotes_alone_do_not_fail(self):
        # One properly quoted line, rest narration — no isolation signal, no dangling tags.
        narration = (
            "The house settled. She catalogued the silence and walked the empty hall. "
            "No other voice replied to her. Dust held the light."
        )
        text = "# Chapter 1: Quiet\n\n" + '"Goodnight," she said.\n\n' + "\n\n".join([narration] * 50)
        hits = find_missing_dialogue_quote_hits(text)
        self.assertEqual(hits, [])
        issues = machine_qc(text, min_words=100)
        self.assertNotIn("quotes_advisory", issues)
        self.assertNotIn("missing_quotes", issues)
        self.assertTrue(machine_pass(issues))

    def test_tag_verb_hits_are_advisory_only(self):
        text = (
            "# Chapter 1: Crowd\n\n"
            "Leave now, he said.\n"
            "Why should I, she asked.\n"
            "Because it is over, he whispered.\n"
            "You never listen, she muttered.\n"
            + ("They argued in the corridor without marks." + "\n") * 80
        )
        hits = find_missing_dialogue_quote_hits(text)
        self.assertTrue(hits)
        issues = machine_qc(text, min_words=100)
        self.assertIn("quotes_advisory", issues)
        self.assertNotIn("missing_quotes", issues)
        self.assertTrue(machine_pass(issues))
        self.assertNotIn("missing_quotes:dialogue", issues_to_needs_fix(issues))
        self.assertEqual(issues_to_needs_fix(issues), [])
        self.assertTrue(any("quotes advisory" in w for w in (issues.get("warnings") or [])))

    def test_negated_dialogue_tags_are_not_unquoted_dialogue(self):
        cases = (
            "Arthur said nothing. His silence was the only confirmation she would ever get.",
            "She spoke no more.",
            "He said no more about the ledger.",
            "Clara answered nothing.",
            "They never spoke after that night.",
            "She did not speak.",
            "He said little.",
            "Marget said not a word.",
        )
        padding = "\n\n".join(["The house held its quiet still."] * 40)
        for line in cases:
            with self.subTest(line=line):
                text = f"# Chapter 12\n\n{line}\n\n{padding}"
                hits = find_missing_dialogue_quote_hits(text)
                self.assertEqual(hits, [], f"unexpected hits for: {line!r}")
                issues = machine_qc(text, min_words=100, target_lang="en")
                self.assertNotIn("missing_quotes", issues)
                self.assertNotIn("quotes_advisory", issues)
                self.assertNotIn("missing_quotes:dialogue", issues_to_needs_fix(issues))

    def test_curly_quoted_dialogue_not_missing_quotes(self):
        """Typographic quotes must count as dialogue marks after normalize."""
        text = (
            "# Chapter 1\n\n"
            "\u201cLeave now,\u201d he said.\n"
            "\u201cWhy should I?\u201d she asked.\n"
            "\u201cBecause it is over,\u201d he whispered.\n"
            + ("They stood in the corridor with the lamps low. " * 80)
        )
        hits = find_missing_dialogue_quote_hits(text)
        self.assertEqual(hits, [], hits)
        issues = machine_qc(text, min_words=100, target_lang="en")
        self.assertNotIn("missing_quotes", issues)
        self.assertNotIn("quotes_advisory", issues)

    def test_isolation_suppresses_even_sparse_noise(self):
        plan = self._isolation_plan()
        text = (
            "# Chapter 3\n\n"
            '"Stay," Clara said.\n\n'
            + ("She wrote alone. Catalogue notes only. " * 100)
        )
        self.assertEqual(
            find_missing_dialogue_quote_hits(text, plan=plan),
            [],
        )


class DraftNoFormatRetryTests(unittest.TestCase):
    def test_quotes_advisory_alone_does_not_force_format_retry(self):
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"n": 0}

        def fake_router(role, payload, **kwargs):
            calls["n"] += 1
            # Tag-verb heuristic may advisory-hit; must not format_fix / rewrite
            body = (
                "# Chapter 1: Test\n\n"
                "Clara said the corridor was empty and cold.\n\n"
                + ("word\n" * 400)
            )
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
        self.assertNotIn("missing_quotes", issues)
        self.assertFalse(is_format_only_issues(issues))
        self.assertTrue(machine_pass(issues))
        self.assertEqual(issues_to_needs_fix(issues), [])

    def test_markdown_alone_does_not_force_format_retry(self):
        text = (
            "# Chapter 1: Test\n\n"
            "The *click* echoed in the hall.\n\n"
            + ("word\n" * 400)
        )
        issues = machine_qc(text, min_words=100)
        self.assertIn("markdown_advisory", issues)
        self.assertNotIn("markdown", issues)
        self.assertFalse(is_format_only_issues(issues))
        self.assertTrue(machine_pass(issues))
        self.assertEqual(issues_to_needs_fix(issues), [])
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
