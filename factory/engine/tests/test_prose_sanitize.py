"""Tests for prose_sanitize — factory markdown policy."""

from __future__ import annotations

import unittest

from factory.engine.lib.machine_qc import machine_pass, machine_qc
from factory.engine.lib.prose_sanitize import (
    apply_markdown_leak_fix,
    find_markdown_artifacts,
    find_markdown_leaks,
    prose_is_clean,
    sanitize_prose,
)


class SanitizeTests(unittest.TestCase):
    def test_strip_bold_dialogue(self):
        raw = '**"You think I\'m afraid of a name?"** he asked.'
        clean = sanitize_prose(raw)
        self.assertNotIn("**", clean)
        self.assertIn("afraid of a name", clean)

    def test_strip_italic_line(self):
        raw = "The *click-click-click* echoed."
        clean = sanitize_prose(raw)
        self.assertEqual(clean, "The click-click-click echoed.")

    def test_strip_cliffhanger_marker(self):
        raw = "End scene.\n\n**Cliffhanger:** Door opens."
        clean = sanitize_prose(raw)
        self.assertNotIn("**", clean)
        self.assertIn("Door opens", clean)

    def test_idempotent_clean_text(self):
        raw = "She closed the door."
        self.assertEqual(sanitize_prose(raw), raw)

    def test_detect_bold(self):
        samples = find_markdown_artifacts('**"Hello"**')
        self.assertTrue(samples)

    def test_clean_after_sanitize(self):
        raw = '**"Hi"**'
        self.assertTrue(prose_is_clean(sanitize_prose(raw)))


class MachineQcMarkdownTests(unittest.TestCase):
    def test_markdown_fails_machine_pass(self):
        text = "# Chapter 1: X\n\n" + '**"Bold dialogue"**' + " " * 1400
        issues = machine_qc(text, min_words=100)
        self.assertIn("markdown_leaks", issues)
        self.assertFalse(machine_pass(issues))


class MarkdownAdvisorTests(unittest.TestCase):
    def test_find_and_quotes_fix(self):
        raw = '# Chapter 1: X\n\nShe said *hello* then left.'
        leaks = find_markdown_leaks(raw)
        self.assertEqual(len(leaks), 1)
        self.assertEqual(leaks[0]["kind"], "italic")
        fixed, log = apply_markdown_leak_fix(raw, mode="quotes", apply_all=True)
        self.assertEqual(len(log), 1)
        self.assertIn('"hello"', fixed)
        self.assertNotIn("*hello*", fixed)
        self.assertFalse(find_markdown_leaks(fixed))

    def test_strip_fix(self):
        raw = 'The **bold** word.'
        fixed, _ = apply_markdown_leak_fix(raw, mode="strip", apply_all=True)
        self.assertEqual(fixed, "The bold word.")


if __name__ == "__main__":
    unittest.main()
