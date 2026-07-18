"""Tests for advisory markdown-leak detect + operator-chosen fix."""

from __future__ import annotations

import unittest

from factory.engine.lib.prose_sanitize import (
    apply_markdown_leak_fix,
    find_markdown_artifacts,
    find_markdown_leaks,
    sanitize_prose,
)


class FindMarkdownLeaksTests(unittest.TestCase):
    def test_skips_pipeline_chapter_title(self):
        text = (
            "# Chapter 6: The Notebook\n\n"
            "She thought *I should have burned it* and kept walking.\n"
        )
        leaks = find_markdown_leaks(text)
        self.assertEqual(len(leaks), 1)
        self.assertEqual(leaks[0]["kind"], "italic")
        self.assertEqual(leaks[0]["inner"], "I should have burned it")
        self.assertIn("should have burned", leaks[0]["context"])

    def test_detects_bold_code_heading(self):
        text = "He said **no** and typed `root`.\n\n## Secret\n\nDone.\n"
        kinds = {h["kind"] for h in find_markdown_leaks(text)}
        self.assertEqual(kinds, {"bold", "code", "heading"})

    def test_context_window(self):
        mid = "*" + ("x" * 10) + "*"
        text = ("A" * 80) + mid + ("B" * 80)
        leaks = find_markdown_leaks(text)
        self.assertEqual(len(leaks), 1)
        self.assertLessEqual(len(leaks[0]["context"]), 60 + len(mid) + 60)


class ApplyMarkdownLeakFixTests(unittest.TestCase):
    def test_quotes_choice(self):
        text = "She thought *I should have burned it* then.\n"
        out, log = apply_markdown_leak_fix(text, mode="quotes", apply_all=True)
        self.assertEqual(out, 'She thought "I should have burned it" then.\n')
        self.assertEqual(log[0]["after"], '"I should have burned it"')

    def test_strip_choice(self):
        text = "She thought *I should have burned it* then.\n"
        out, log = apply_markdown_leak_fix(text, mode="strip", apply_all=True)
        self.assertEqual(out, "She thought I should have burned it then.\n")
        self.assertEqual(log[0]["mode"], "strip")

    def test_single_hit_id(self):
        text = "A *one* and *two*.\n"
        leaks = find_markdown_leaks(text)
        self.assertEqual(len(leaks), 2)
        out, log = apply_markdown_leak_fix(
            text, mode="strip", hit_ids=[leaks[0]["id"]]
        )
        self.assertEqual(out, "A one and *two*.\n")
        self.assertEqual(len(log), 1)

    def test_refuses_unknown_mode(self):
        with self.assertRaises(ValueError):
            apply_markdown_leak_fix("*x*", mode="guess", apply_all=True)  # type: ignore[arg-type]


class SanitizeNoAutoEmphasisTests(unittest.TestCase):
    def test_sanitize_leaves_italics(self):
        raw = "She whispered *stay* at the door."
        self.assertEqual(sanitize_prose(raw), raw)

    def test_sanitize_still_strips_engine_tokens(self):
        raw = "End.\n\n**Cliffhanger:** boom\nT001 leftovers."
        clean = sanitize_prose(raw)
        self.assertNotIn("Cliffhanger", clean)
        self.assertNotIn("T001", clean)

    def test_artifacts_still_detectable(self):
        self.assertTrue(find_markdown_artifacts("*stay*"))


if __name__ == "__main__":
    unittest.main()
