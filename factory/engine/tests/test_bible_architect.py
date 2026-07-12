"""Architect validate-and-retry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.bible_architect import (
    generate_bible_with_retry,
    seed_central_mystery_from_ledger,
)


class BibleArchitectTests(unittest.TestCase):
    def test_seed_central_mystery_from_ledger(self) -> None:
        bible: dict = {"title": "X"}
        ledger = {
            "main_mystery": "What happened?",
            "truth": "She pushed him.",
            "canonical_reveal_chapter": 9,
        }
        self.assertTrue(seed_central_mystery_from_ledger(bible, ledger))
        self.assertEqual(bible["central_mystery"]["question"], "What happened?")
        self.assertEqual(bible["central_mystery"]["reveal_chapter"], 9)
        self.assertFalse(seed_central_mystery_from_ledger(bible, ledger))

    def test_retry_then_pass(self) -> None:
        incomplete = {
            "meta": {"series_id": "t", "genre": "g", "target_language": "en"},
            "title": "T",
            "sub_niche": "gothic",
            "spice_level": 1,
            "planned_books": 2,
            "hook_central": "hook",
            "tropes": ["a"],
            "leads": {
                "female": {
                    "name": "Elena",
                    "age": 28,
                    "voice": "quiet",
                    "tics": ["key"],
                    "boundary": "avoids mirrors",
                },
                "male": {
                    "name": "Isaac",
                    "age": 35,
                    "voice": "soft",
                    "tics": ["collar"],
                    "boundary": "facts only",
                },
            },
            "supporting_cast": [
                {
                    "name": "Diane",
                    "relation_to": "Elena",
                    "relation_type": "mother",
                    "alive": True,
                }
            ],
            "bloodline": {
                "description": "no blood between leads",
                "hard_rules": ["no blood"],
                "lead_relation": "stranger",
            },
            "world_rules": ["dread"],
            "series_arc": [{"book": 1, "thesis": "truth", "ending_hook": "shadow"}],
            "content_rules": ["no gore"],
        }
        complete = {
            **incomplete,
            "central_mystery": {
                "question": "What did she do?",
                "answer": "She pushed Tomas.",
                "reveal_chapter": 9,
            },
        }

        calls = {"n": 0}

        def fake_call(role, user, **kwargs):
            calls["n"] += 1
            payload = complete if calls["n"] > 1 else incomplete
            return json.dumps(payload), {"usage": {}}

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "concept.yaml").write_text(
                yaml.dump({"title": "T", "concept_status": "ready"}),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                "book: 1\ntarget_language: en\nnarrative_profile: gothic_psychological_horror\n",
                encoding="utf-8",
            )
            with patch(
                "factory.engine.lib.bible_architect.call_9router",
                side_effect=fake_call,
            ), patch(
                "factory.engine.lib.bible_architect.validate_bible",
                side_effect=lambda b: (
                    []
                    if b.get("central_mystery")
                    else ["missing:central_mystery"]
                ),
            ):
                result = generate_bible_with_retry(ws, max_attempts=3)
            self.assertTrue(result["ok"])
            self.assertEqual(result["attempts"], 2)
            self.assertEqual(calls["n"], 2)
            saved = json.loads((ws / "bible" / "series.json").read_text(encoding="utf-8"))
            self.assertIn("central_mystery", saved)


if __name__ == "__main__":
    unittest.main()
