"""Tests for EPUBCheck QC integration."""

from __future__ import annotations

import unittest
from pathlib import Path

from factory.engine.lib.epub_qc import parse_epubcheck_output, resolve_epubcheck_jar


class ParseEpubcheckTests(unittest.TestCase):
    def test_pass_output(self):
        text = """
Validating using EPUB version 3.3 rules.
No errors or warnings detected.
Messages: 0 fatals / 0 errors / 0 warnings / 0 infos

EPUBCheck completed
"""
        out = parse_epubcheck_output(text)
        self.assertTrue(out["passed"])
        self.assertEqual(out["counts"]["errors"], 0)
        self.assertEqual(out["epub_version"], "3.3")

    def test_error_lines(self):
        text = """
ERROR(RSC-005): Missing resource
WARNING(OPF-014): ...
Messages: 0 fatals / 1 errors / 1 warnings / 0 infos
"""
        out = parse_epubcheck_output(text)
        self.assertFalse(out["passed"])
        self.assertEqual(out["counts"]["errors"], 1)
        self.assertEqual(len(out["messages"]), 2)
        self.assertEqual(out["messages"][0]["code"], "RSC-005")


class EpubcheckIntegrationTests(unittest.TestCase):
    def test_resolve_jar_from_config(self):
        jar = resolve_epubcheck_jar({"epubcheck_jar": "F:/phanmem/epubcheck-5.3.0/epubcheck.jar"})
        if Path("F:/phanmem/epubcheck-5.3.0/epubcheck.jar").is_file():
            self.assertIsNotNone(jar)


if __name__ == "__main__":
    unittest.main()
