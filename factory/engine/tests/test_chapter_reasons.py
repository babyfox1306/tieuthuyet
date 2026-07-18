"""Tests for human-readable chapter block reasons."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.chapter_reasons import chapter_block_info, format_status_with_reason
from factory.engine.lib.machine_qc import format_machine_reasons
from factory.engine.lib.qc_eval import format_qc_reasons


class FormatReasonsTests(unittest.TestCase):
    def test_machine_short(self):
        reasons = format_machine_reasons({"word_count": 900, "short": 900, "target_language": "en"})
        self.assertEqual(
            reasons,
            [
                "[length_fail — 900 từ < min; đã expand/rewrite; KHÔNG cho qua ready — không phải lỗi dấu *]",
                "quá ngắn (900 từ)",
            ],
        )

    def test_machine_foreign(self):
        reasons = format_machine_reasons({"foreign_chars": ["中", "文"], "word_count": 2000})
        self.assertTrue(any(r.startswith("ký tự ngoại ngữ:") for r in reasons))
        self.assertTrue(any("format_fix" in r for r in reasons))

    def test_qc_continuity_with_details(self):
        qc = {
            "verdict": "FAIL",
            "continuity_conflict": {"flag": True, "details": "jumped to archives without transition"},
            "fail_reasons": ["continuity_conflict", "verdict_fail"],
        }
        reasons = format_qc_reasons(qc)
        self.assertEqual(len(reasons), 1)
        self.assertIn("đứt mạch", reasons[0])
        self.assertIn("archives", reasons[0])

    def test_qc_extra_fail_reason(self):
        qc = {"verdict": "FAIL", "fail_reasons": ["verdict_fail", "signature_detail_missing"]}
        reasons = format_qc_reasons(qc)
        self.assertIn("signature_detail_missing", reasons)

    def test_status_label(self):
        self.assertEqual(
            format_status_with_reason("needs_fix", "quá ngắn (900 từ)"),
            "needs_fix — quá ngắn (900 từ)",
        )
        self.assertEqual(format_status_with_reason("ready", ""), "ready")


class ChapterBlockInfoTests(unittest.TestCase):
    def test_loads_needs_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            issues_dir = ws / "books" / "01" / "pipeline" / "needs_fix"
            issues_dir.mkdir(parents=True)
            (issues_dir / "ch_022_issues.json").write_text(
                json.dumps({"word_count": 1347, "short": 1347}),
                encoding="utf-8",
            )
            info = chapter_block_info(ws, 1, "needs_fix", 22)
            self.assertEqual(
                info["reasons"],
                [
                    "[length_fail — 1347 từ < min; đã expand/rewrite; KHÔNG cho qua ready — không phải lỗi dấu *]",
                    "quá ngắn (1347 từ)",
                ],
            )
            self.assertIn("quá ngắn", info["reason_summary"])

    def test_loads_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            qc_dir = ws / "books" / "01" / "pipeline" / "needs_review"
            qc_dir.mkdir(parents=True)
            (qc_dir / "ch_024_qc.json").write_text(
                json.dumps(
                    {
                        "verdict": "FAIL",
                        "continuity_conflict": {"flag": True, "details": "no transition"},
                        "fail_reasons": ["continuity_conflict"],
                    }
                ),
                encoding="utf-8",
            )
            info = chapter_block_info(ws, 1, "needs_review", 24)
            self.assertTrue(any("đứt mạch" in r for r in info["reasons"]))


if __name__ == "__main__":
    unittest.main()
