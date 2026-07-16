"""EG-16 duplicate_block — intra-chapter verbatim / near-dup detection."""

from __future__ import annotations

import unittest
from pathlib import Path

from factory.engine.lib.export_gate import (
    check_eg16_duplicate_block,
    find_eg16_verbatim_hits,
    prose_body_for_duplicate_check,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parents[3]
HFT_CHAPTERS = (
    ROOT
    / "catalog"
    / "his-final-target"
    / "books"
    / "01-his-final-target"
    / "chapters"
)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _error_hits(checks: list[dict]) -> list[dict]:
    return [
        c
        for c in checks
        if c.get("id") == "EG-16"
        and c.get("severity") == "error"
        and not c.get("passed")
    ]


def _warn_hits(checks: list[dict]) -> list[dict]:
    return [
        c
        for c in checks
        if c.get("id") == "EG-16"
        and c.get("severity") == "warn"
        and not c.get("passed")
    ]


class EG16FixtureTests(unittest.TestCase):
    def test_ch16_reckoning_blocks_on_rook_pa(self) -> None:
        body = _load("16-the-reckoning.md")
        checks = check_eg16_duplicate_block(body, 16)
        errors = _error_hits(checks)
        self.assertTrue(errors, f"expected BLOCK, got {checks}")
        blob = " ".join(
            str(c.get("ngram") or "") + " " + str(c.get("report") or "") for c in errors
        ).lower()
        self.assertIn("sunrise clause", blob)
        self.assertIn("loyalty", blob)

    def test_ch01_passes(self) -> None:
        body = _load("01-the-blood-on-the-scope.md")
        checks = check_eg16_duplicate_block(body, 1)
        self.assertFalse(_error_hits(checks), checks)

    def test_ch09_passes(self) -> None:
        body = _load("09-the-self-beneath-her-skin.md")
        checks = check_eg16_duplicate_block(body, 9)
        self.assertFalse(_error_hits(checks), checks)

    def test_recording_exception_warn_not_block(self) -> None:
        body = _load("eg16_recording_exception.md")
        checks = check_eg16_duplicate_block(body, 99)
        self.assertFalse(_error_hits(checks), checks)
        warns = _warn_hits(checks)
        self.assertTrue(warns, "recording exception must WARN")
        self.assertTrue(
            any("recording" in str(c.get("detail") or "").lower() for c in warns)
            or any("recording" in str(c.get("report") or "").lower() for c in warns),
            warns,
        )

    def test_ngram_boundary_11_pass_12_warn_20_block(self) -> None:
        body = _load("eg16_ngram_boundary.md")
        prose = prose_body_for_duplicate_check(body)
        # 11-word color list: detectable at n=11, not a 12-gram alone
        blocks_11, _ = find_eg16_verbatim_hits(prose, n=11)
        self.assertTrue(
            any(
                h["ngram"]
                == "red orange yellow green blue indigo violet amber coral slate pewter"
                for h in blocks_11
            ),
            blocks_11,
        )
        # Default check: 11-word list must not BLOCK (and should not WARN as 12-gram)
        checks = check_eg16_duplicate_block(body, 98)
        errors = _error_hits(checks)
        warns = _warn_hits(checks)
        # 20-word direction list → BLOCK
        self.assertTrue(errors, "20-word repeat must BLOCK")
        joined_err = " ".join(str(c.get("ngram") or "") for c in errors)
        self.assertIn("north south east west", joined_err)
        self.assertIn("eight", joined_err)
        self.assertNotIn("pewter", joined_err)
        # No false BLOCK on the 11-word pewter list
        self.assertFalse(any("pewter" in str(c.get("ngram") or "") for c in errors))


class EG16HisFinalTargetScan(unittest.TestCase):
    def test_scan_all_seventeen_prints_table(self) -> None:
        if not HFT_CHAPTERS.exists():
            self.skipTest("his-final-target catalog missing")
        rows: list[str] = []
        blocked: list[int] = []
        for path in sorted(HFT_CHAPTERS.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            # chapter number from frontmatter / filename
            ch = int(path.name.split("-", 1)[0])
            checks = check_eg16_duplicate_block(text, ch)
            errs = _error_hits(checks)
            warns = _warn_hits(checks)
            status = "BLOCK" if errs else ("WARN" if warns else "PASS")
            if errs:
                blocked.append(ch)
            detail = ""
            if errs:
                detail = (errs[0].get("ngram") or "")[:60]
            elif warns:
                detail = (warns[0].get("detail") or "")[:60]
            rows.append(f"ch{ch:02d}  {status:5}  {detail}")
        print("\nEG-16 his-final-target scan:")
        print("\n".join(rows))
        self.assertIn(16, blocked, f"ch16 must BLOCK; blocked={blocked}")
        self.assertEqual(blocked, [16], f"only ch16 should BLOCK after min_run=20; got {blocked}")


if __name__ == "__main__":
    unittest.main()
