"""Architect validate-and-retry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.bible_architect import (
    build_architect_payload,
    generate_bible_with_retry,
    lock_bible_lead_names,
    seed_central_mystery_from_ledger,
)


class BibleArchitectTests(unittest.TestCase):
    def test_architect_uses_and_enforces_structured_lead_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            concept = {
                "title": "T",
                "pov": {"character": "Calder Reed", "mode": "first_person"},
                "characters": [
                    {
                        "name": "Calder Reed",
                        "role": "protagonist / dark-romance lead",
                    },
                    {"name": "Lena Hart", "role": "dark-romance heroine"},
                ],
            }
            (ws / "concept.yaml").write_text(yaml.dump(concept), encoding="utf-8")
            (ws / "direction.yaml").write_text(
                "target_language: en\nnarrative_profile: dark_romance\n",
                encoding="utf-8",
            )

            payload = build_architect_payload(ws, cfg={"spice_level": 1})
            self.assertEqual(
                payload["locked_lead_names"],
                {"female": "Lena Hart", "male": "Calder Reed"},
            )

            bible = {
                "leads": {
                    "female": {"name": "Calder Reed", "voice": "Lena voice"},
                    "male": {"name": "Calder Ash", "voice": "Calder voice"},
                }
            }
            self.assertTrue(lock_bible_lead_names(bible, payload["locked_lead_names"]))
            self.assertEqual(bible["leads"]["female"]["name"], "Lena Hart")
            self.assertEqual(bible["leads"]["male"]["name"], "Calder Reed")
            self.assertEqual(bible["leads"]["male"]["voice"], "Calder voice")

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

    def test_scrub_premature_leak_lock(self) -> None:
        from factory.engine.lib.bible_architect import scrub_premature_leak_lock
        from factory.engine.lib.bible_schema import validate_bible

        concept = {
            "author_directive": (
                "THE LEAK: one of the three network members betrays Nadia "
                "(decide which at plan time; keep consistent once chosen)."
            )
        }
        bible = {
            "supporting_cast": [
                {
                    "name": "Wren Delgado",
                    "relation_to": "Nadia Cole",
                    "relation_type": "hacker",
                    "alive": True,
                    "secret": "Pulls digital trails; is the leak who betrays Nadia.",
                }
            ],
            "series_arc": [
                {
                    "book": 1,
                    "thesis": "Nadia's network fractures when Wren Delgado betrays her.",
                    "ending_hook": "hook",
                }
            ],
            "central_mystery": {"question": "q", "answer": "a", "reveal_chapter": 10},
        }
        notes = scrub_premature_leak_lock(bible, concept)
        self.assertTrue(notes)
        self.assertNotIn("leak who betrays", bible["supporting_cast"][0]["secret"].lower())
        self.assertNotIn("Wren Delgado betrays", bible["series_arc"][0]["thesis"])
        # Full schema not required here — only deferred-leak rules.
        leak_errs = [
            e
            for e in validate_bible(
                {
                    "meta": {"series_id": "t", "genre": "thriller", "target_language": "en"},
                    "title": "T",
                    "sub_niche": "thriller",
                    "spice_level": 1,
                    "planned_books": 1,
                    "hook_central": "h",
                    "tropes": ["t"],
                    "leads": {
                        "female": {
                            "name": "Nadia Cole",
                            "age": 30,
                            "voice": "v",
                            "tics": ["t"],
                            "boundary": "b",
                        },
                        "male": {
                            "name": "Victor Rhodes",
                            "age": 40,
                            "voice": "v",
                            "tics": ["t"],
                            "boundary": "b",
                        },
                    },
                    "supporting_cast": bible["supporting_cast"],
                    "central_mystery": bible["central_mystery"],
                    "bloodline": {
                        "description": "unrelated",
                        "hard_rules": ["no blood"],
                        "lead_relation": "hunter and hunted (non-romantic)",
                    },
                    "world_rules": ["grounded"],
                    "series_arc": bible["series_arc"],
                },
                concept=concept,
            )
            if "leak" in e or "betrayer" in e or "romance_forbidden" in e
        ]
        self.assertEqual(leak_errs, [])

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
                side_effect=lambda b, concept=None: (
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
