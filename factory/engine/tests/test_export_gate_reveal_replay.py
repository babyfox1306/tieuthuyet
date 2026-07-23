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
    def test_same_phrase_two_chapters_warns(self) -> None:
        triples = [
            (1, {}, 'She exhaled. "The truth was out." Marsh nodded.'),
            (7, {}, 'Later she said it again: the truth was out, and louder.'),
        ]
        checks = check_eg18_reveal_replayed(
            triples,
            workspace_id=None,
            cfg={"completion_phrases": ["the truth was out"]},
        )
        warns = _warn_hits(checks)
        self.assertTrue(warns, f"expected EG-18 WARN, got {checks}")
        self.assertEqual({c.get("chapter") for c in warns}, {1, 7})

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
