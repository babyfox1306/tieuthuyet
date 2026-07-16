"""EG-18 reveal_replayed — completion-phrase replay across chapters."""

from __future__ import annotations

import unittest
from pathlib import Path

from factory.engine.lib.export_gate import (
    check_eg18_reveal_replayed,
    find_completion_phrase_hits,
    load_config,
)

ROOT = Path(__file__).resolve().parents[3]
HFT_CHAPTERS = (
    ROOT
    / "catalog"
    / "his-final-target"
    / "books"
    / "01-his-final-target"
    / "chapters"
)


def _load_catalog_chapter(path: Path) -> tuple[int, dict, str]:
    import yaml

    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        meta = yaml.safe_load(parts[1]) or {}
        body = parts[2] if len(parts) > 2 else ""
    else:
        meta, body = {}, text
    ch = int(meta.get("chapter") or 0)
    return ch, meta, body


def _warn_hits(checks: list[dict]) -> list[dict]:
    return [
        c
        for c in checks
        if c.get("id") == "EG-18" and not c.get("passed") and c.get("severity") == "warn"
    ]


class EG18RevealReplayTests(unittest.TestCase):
    def test_hft_ch13_16_17_warn(self) -> None:
        if not HFT_CHAPTERS.is_dir():
            self.skipTest("his-final-target catalog missing")
        wanted = {13, 16, 17}
        triples = []
        for path in sorted(HFT_CHAPTERS.glob("*.md")):
            ch, meta, body = _load_catalog_chapter(path)
            if ch in wanted:
                triples.append((ch, meta, body))
        self.assertEqual(sorted(t[0] for t in triples), [13, 16, 17])
        checks = check_eg18_reveal_replayed(
            triples, workspace_id="his-final-target", cfg=load_config()
        )
        warns = _warn_hits(checks)
        self.assertTrue(warns, f"expected EG-18 WARN, got {checks}")
        hit_chs = {c.get("chapter") for c in warns}
        # ch14 also hits «all of it» — still a completion-phrase chapter
        self.assertTrue(wanted.issubset(hit_chs), hit_chs)
        self.assertGreaterEqual(len(hit_chs), 3, hit_chs)

    def test_hft_ch1_to_8_no_warn(self) -> None:
        if not HFT_CHAPTERS.is_dir():
            self.skipTest("his-final-target catalog missing")
        triples = []
        for path in sorted(HFT_CHAPTERS.glob("*.md")):
            ch, meta, body = _load_catalog_chapter(path)
            if 1 <= ch <= 8:
                triples.append((ch, meta, body))
        self.assertGreaterEqual(len(triples), 5)
        checks = check_eg18_reveal_replayed(
            triples, workspace_id="his-final-target", cfg=load_config()
        )
        self.assertFalse(_warn_hits(checks), checks)

    def test_phrase_finder(self) -> None:
        body = 'She exhaled. "The truth was out." Silence.'
        hits = find_completion_phrase_hits(body, ["the truth was out"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], "the truth was out")


if __name__ == "__main__":
    unittest.main()
