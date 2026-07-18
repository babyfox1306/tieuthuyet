"""Tests for prose_sanitize — engine residue vs advisory markdown."""

from __future__ import annotations

import unittest

from factory.engine.lib.machine_qc import machine_pass, machine_qc
from factory.engine.lib.prose_sanitize import find_markdown_artifacts, prose_is_clean, sanitize_prose


class SanitizeTests(unittest.TestCase):
    def test_leaves_bold_for_operator(self):
        raw = '**"You think I\'m afraid of a name?"** he asked.'
        self.assertEqual(sanitize_prose(raw), raw)
        self.assertTrue(find_markdown_artifacts(raw))

    def test_leaves_italic_for_operator(self):
        raw = "The *click-click-click* echoed."
        self.assertEqual(sanitize_prose(raw), raw)

    def test_strip_cliffhanger_marker(self):
        raw = "End scene.\n\n**Cliffhanger:** Door opens."
        clean = sanitize_prose(raw)
        self.assertNotIn("Cliffhanger", clean)
        self.assertIn("Door opens", clean)

    def test_idempotent_clean_text(self):
        raw = "She closed the door."
        self.assertEqual(sanitize_prose(raw), raw)

    def test_detect_bold(self):
        samples = find_markdown_artifacts('**"Hello"**')
        self.assertTrue(samples)


class MachineQcMarkdownAdvisoryTests(unittest.TestCase):
    def test_markdown_is_advisory_not_blocking(self):
        text = "# Chapter 1: X\n\nThe letter said *burn this*.\n\n" + ("word\n" * 200)
        issues = machine_qc(text, min_words=100)
        self.assertNotIn("markdown", issues)
        self.assertIn("markdown_advisory", issues)
        self.assertTrue(machine_pass(issues))


if __name__ == "__main__":
    unittest.main()
