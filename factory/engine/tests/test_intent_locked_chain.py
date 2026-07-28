"""Acceptance tests for sequential locked chain (0 LLM)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from factory.engine.lib.intent_gates import (
    g3_plan_fidelity_errors,
    g4_prompt_errors,
    prompt_projection_digest,
    seal_plans_to_intent,
)
from factory.engine.lib.intent_manifest import (
    approve_intent,
    compile_and_save_intent,
    compile_intent_manifest,
    infer_canonical_reveal_chapter,
    locked_pack_for_outliner,
    must_include_for_chapter,
)
from factory.engine.lib.master_plan import build_outliner_payload
from factory.engine.lib.prompt_builder import (
    _content_boundaries_for_prompt,
    build_chapter_prompt,
)


def _write_ws(root: Path) -> Path:
    ws = root / "ws-test"
    (ws / "books" / "01").mkdir(parents=True)
    (ws / "bible" / "narrative").mkdir(parents=True)
    concept = {
        "concept_status": "ready",
        "target_language": "en",
        "title": "Test Bell",
        "logline": "A test.",
        "author_directive": (
            "POV: third-person limited, locked to Clara every chapter.\n"
            "CAST:\n- Clara Vale: lead\n- Thomas Vale: antagonist\n"
            "Ch1: Clara hears the eighth bell and finds a cracked tablet.\n"
            "Ch2: She maps eight names without knowing Thomas built the system.\n"
            "Ch3: Future confession fragment appears on tape edge.\n"
            "Ch4: Micro-splices prove the confession was edited.\n"
            "Ch5: Mara withholds the west-wall key.\n"
            "Ch6: The wall answers with a hollow knock.\n"
            "Ch7: A witness note only Clara can hear.\n"
            "Ch8: Gabriel gives the key; Clara enters the chamber; finds Elin tape.\n"
            "Ch9: Reconstruct the tape; hear Thomas freeze; stop him destroying it.\n"
            "Ch10: Public confess and supernatural coda; no sequel hook.\n"
        ),
        "surface_plot": "A haunted bell mystery in a coastal town.",
        "true_plot": "Thomas fabricated the ninth bell system as cover.",
        "must_include": ["Cliffhanger every chapter"],
        "must_avoid": ["romance subplot", "explicit sex"],
        "must_include_by_chapter": {"8": ["enter chamber", "Elin tape"]},
        "ending_book1": "Public confession and coda; standalone close.",
        "hook_book2": "No sequel hook.",
    }
    (ws / "concept.yaml").write_text(
        yaml.dump(concept, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (ws / "direction.yaml").write_text(
        yaml.dump(
            {
                "book": 1,
                "total_chapters": 10,
                "target_language": "en",
                "spice_max": 1,
                "spice_default": 1,
                "narrative_profile": "gothic_psychological_horror",
                "intent_status": "draft",
                "plan_status": "draft",
                "bible_status": "draft",
                "narrative_status": "draft",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    # Minimal bible + registry so prompt builder can run
    (ws / "bible" / "series.json").write_text(
        json.dumps(
            {
                "title": "Test Bell",
                "bible_status": "approved",
                "world_rules": ["Thomas built the ninth bell system as a cover legend."],
                "content_rules": [],
                "leads": {
                    "female": {"name": "Clara Vale"},
                    "male": {"name": "Unassigned (no male lead)"},
                },
            }
        ),
        encoding="utf-8",
    )
    (ws / "canon_registry.yaml").write_text(
        yaml.dump(
            {
                "characters": {
                    "female_lead": {
                        "canonical": "Clara Vale",
                        "allowed_aliases": ["Clara", "Clara Vale"],
                        "forbidden_aliases": [],
                    },
                    "male_lead": {
                        "canonical": "Unassigned (no male lead)",
                        "allowed_aliases": [],
                        "forbidden_aliases": [],
                    },
                },
                "pov_mode": "third_person_limited",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return ws


class IntentManifestTests(unittest.TestCase):
    def test_canonical_reveal_is_derived_from_affirmative_chapter_map(self) -> None:
        concept = {
            "chapter_map": {
                14: (
                    "What She Let Him See. Lena shows the complete planner. "
                    "Calder and reader learn she controlled the surveillance."
                ),
                18: "Verified aftermath and legal payoff.",
            }
        }
        self.assertEqual(infer_canonical_reveal_chapter(concept), 14)

    def test_intentional_reader_reveal_never_softens_writer_spoiler(self) -> None:
        from factory.engine.lib.master_plan import _soft_intentional_early_reveal

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "policy"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump({"intentional_early_reveal": True}),
                encoding="utf-8",
            )
            self.assertTrue(
                _soft_intentional_early_reveal(
                    ws, "ch14:canon:mystery_reveal_too_early:before_ch18"
                )
            )
            self.assertFalse(
                _soft_intentional_early_reveal(
                    ws, "prompt:G4:true_plot_spoil_early:ch1"
                )
            )

    def test_intent_seal_restores_missing_chapter_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            compile_and_save_intent(ws, book=1)
            approve_intent(ws, book=1)
            plans = [
                {
                    "chapter": 1,
                    "must_happen": [
                        "Clara drinks tea and studies an unrelated map.",
                        "The rain stops.",
                        "She closes the window.",
                    ],
                }
            ]
            sealed, notes = seal_plans_to_intent(ws, plans, book=1)
            joined = " ".join(sealed[0]["must_happen"])
            self.assertIn("[INTENT LOCK]", joined)
            self.assertIn("eighth bell", joined)
            self.assertEqual(notes, ["ch1:intent_beat_restored"])
            ch1_errors = [
                err
                for err in g3_plan_fidelity_errors(ws, sealed, book=1)
                if err.endswith(":ch1")
            ]
            self.assertEqual(ch1_errors, [])

    def test_compile_from_ch_lines_no_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            with mock.patch("factory.engine.lib.call_9router.call_9router") as mocked:
                man = compile_and_save_intent(ws, book=1)
                mocked.assert_not_called()
            self.assertGreaterEqual(len(man["chapter_map"]), 8)
            self.assertTrue(man["pov"])
            self.assertEqual(man["status"], "draft")
            approve_intent(ws, book=1)
            man2 = compile_intent_manifest(ws, book=1)
            # recompile stays draft until approve; load approved file
            from factory.engine.lib.intent_manifest import load_intent_manifest

            locked = load_intent_manifest(ws, 1)
            self.assertEqual(locked["status"], "approved")
            self.assertIn("8", locked.get("must_include_by_chapter") or {})
            self.assertTrue(must_include_for_chapter(locked, 8))

    def test_i_map_plan_missing_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            approve_intent(ws, book=1)
            plans = [
                {
                    "chapter": 8,
                    "beat_summary": "Opens a steel door only.",
                    "must_happen": ["Open steel door"],
                    "chapter_task": "Door scene",
                }
            ]
            errs = g3_plan_fidelity_errors(ws, plans, book=1)
            self.assertTrue(any("chapter_map_not_covered:ch8" in e for e in errs))

    def test_i_cov_must_include_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            approve_intent(ws, book=1)
            plans = [
                {
                    "chapter": 8,
                    "beat_summary": "Clara enters the chamber and finds the Elin tape with editing gear.",
                    "must_happen": [
                        "Gabriel gives the key",
                        "Clara enters the chamber",
                        "Finds Elin tape",
                    ],
                    "chapter_task": "Chamber entry and tape discovery",
                }
            ]
            # Still may fail other chapters missing — filter ch8 must_include
            errs = [e for e in g3_plan_fidelity_errors(ws, plans, book=1) if "ch8" in e and "must_include" in e]
            self.assertEqual(errs, [])

    def test_i_name_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            approve_intent(ws, book=1)
            plans = [
                {
                    "chapter": 1,
                    "beat_summary": "Female Lead hears bells.",
                    "must_happen": ["Female Lead finds tablet", "a", "b"],
                    "chapter_task": "Female Lead intro",
                }
            ]
            errs = g3_plan_fidelity_errors(ws, plans, book=1)
            self.assertTrue(any("placeholder_lead" in e for e in errs))

    def test_i_prompt_no_full_book_dump(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            approve_intent(ws, book=1)
            avoid, include = _content_boundaries_for_prompt(ws, {}, chapter=1)
            joined = "\n".join(avoid + include)
            # Book-level must_include should not flood ch1 as MUST INCLUDE this chapter
            self.assertNotIn("Cliffhanger every chapter", joined)
            self.assertTrue(any("romance" in b.lower() or "sex" in b.lower() for b in avoid))
            # Must-include beats must not be nested under avoid list items
            self.assertFalse(any("MUST INCLUDE" in b.upper() for b in avoid))
            # If chapter has includes, they are a separate list (not prefixed into avoid)
            for item in include:
                self.assertFalse(item.upper().startswith("MUST INCLUDE"))

    def test_i_token_compile_and_prompt_no_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            with mock.patch("factory.engine.lib.call_9router.call_9router") as mocked:
                approve_intent(ws, book=1)
                plan = {
                    "chapter": 1,
                    "title": "Arrival",
                    "spice": 1,
                    "beat_summary": "Clara hears the eighth bell and finds a cracked tablet.",
                    "opens_with": "Bell",
                    "must_happen": ["Hear eighth bell", "Find cracked tablet", "Leave on doubt"],
                    "must_not": ["Know Thomas built system"],
                    "cliffhanger": "Who rings?",
                    "chapter_task": "Write ch1",
                    "one_line_summary": "Bell and tablet",
                }
                build_chapter_prompt(
                    plan,
                    prior_plans=[],
                    direction=yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8")),
                    chapter=1,
                    series_bible=json.loads((ws / "bible" / "series.json").read_text(encoding="utf-8")),
                    ws=ws,
                )
                mocked.assert_not_called()

    def test_i_reuse_locked_pack_no_raw_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_ws(Path(tmp))
            approve_intent(ws, book=1)
            pack = locked_pack_for_outliner(ws, 1, 1, 3)
            self.assertIn("intent_manifest", pack)
            self.assertNotIn("author_directive", json.dumps(pack))
            body = build_outliner_payload(
                ws,
                1,
                1,
                3,
                "act1",
                bible=json.loads((ws / "bible" / "series.json").read_text(encoding="utf-8")),
                direction=yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8")),
                prior=[],
            )
            self.assertIn("locked_pack", body)
            blob = json.dumps(body)
            self.assertNotIn("concept.yaml", blob)
            self.assertNotIn("author_directive", blob)
            # Locked pack may include true_plot — that is intentional authority, not raw concept dump.
            self.assertIn("intent_manifest", blob)

    def test_i_write_disk_digest(self):
        from factory.engine.lib.intent_gates import (
            assert_prompt_matches_disk,
            is_prompt_hand_locked,
            strip_prompt_hand_lock_banner,
        )

        a = "hello prompt"
        b = "hello prompt"
        c = "hello prompt!"
        self.assertEqual(prompt_projection_digest(a), prompt_projection_digest(b))
        self.assertNotEqual(prompt_projection_digest(a), prompt_projection_digest(c))
        errs = g4_prompt_errors(
            Path("."),
            1,
            1,
            c,
            disk_text=a,
        )
        self.assertTrue(any("disk_mismatch" in e for e in errs))

        locked = "# PROMPT_HAND_LOCK\n\nhello hand edit"
        self.assertTrue(is_prompt_hand_locked(locked))
        self.assertFalse(
            any(
                "disk_mismatch" in e
                for e in g4_prompt_errors(Path("."), 1, 1, c, disk_text=locked)
            )
        )
        assert_prompt_matches_disk(locked, "totally different live", 37)
        self.assertEqual(strip_prompt_hand_lock_banner(locked).strip(), "hello hand edit")

    def test_compile_structured_ninth_bell_shape(self):
        """Rich operator concept: pov dict, characters[], chapter_map.required_beats, surface_mystery."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ninth"
            (ws / "books" / "01").mkdir(parents=True)
            concept = {
                "concept_status": "ready",
                "target_language": "en",
                "title": "The Ninth Bell",
                "format": {"total_chapters": 10},
                "genre": {
                    "primary": "gothic psychological horror",
                    "secondary": ["acoustic mystery"],
                },
                "pov": {"character": "Clara Vale", "mode": "first_person", "tense": "past"},
                "characters": [
                    {"name": "Clara Vale", "role": "POV"},
                    {"name": "Thomas Vale", "role": "antagonist"},
                ],
                "logline": "Clara inherits a tower and a false confession.",
                "surface_mystery": "Bells preserve the dead; ninth confession appears.",
                "true_plot": "Thomas built an acoustic surveillance system and fabricated the confession.",
                "ending_book1": "Thomas confesses; coda You came back.",
                "must_avoid": ["Romance", "Third-person narration"],
                "must_include": ["Nine bells"],
                "reveal_ladder": {
                    "surface_event": {"chapter": 3, "exact_text": "I knew she would fall."}
                },
                "chapter_map": {
                    1: {
                        "title": "Arrival",
                        "required_beats": [
                            "Gabriel meets Clara",
                            "metallic double pulse",
                        ],
                        "must_not_reveal": ["Thomas involvement"],
                        "ending": "Elin addresses Clara.",
                    },
                    3: {
                        "title": "Confession",
                        "required_beats": ["exact confession heard"],
                    },
                    4: {"title": "Pieces", "required_beats": ["micro-splices proven"]},
                    8: {"title": "Chamber", "required_beats": ["enters chamber", "Elin tape"]},
                    10: {
                        "title": "Kept",
                        "required_beats": ["public confession"],
                        "final_line": "You came back.",
                    },
                },
            }
            # Fill remaining chapters so map is dense enough
            for ch in (2, 5, 6, 7, 9):
                concept["chapter_map"][ch] = {
                    "title": f"Ch{ch}",
                    "required_beats": [f"beat for chapter {ch}"],
                }
            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "book": 1,
                        "total_chapters": 10,
                        "target_language": "en",
                        "spice_max": 0,
                        "spice_default": 0,
                        "intent_status": "draft",
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            man = compile_and_save_intent(ws, book=1)
            self.assertEqual(man["pov"], "Clara Vale | first_person | past")
            self.assertEqual(man["cast"], ["Clara Vale", "Thomas Vale"])
            self.assertTrue(man["surface_plot"].startswith("Bells preserve"))
            self.assertIn("gothic psychological horror", man["genre_profile"])
            self.assertEqual(len(man["chapter_map"]), 10)
            ch1 = man["chapter_map"][0]
            self.assertEqual(ch1["title"], "Arrival")
            self.assertIn("metallic double pulse", ch1["must_happen"])
            self.assertIn("Thomas involvement", ch1["must_not_reveal"])
            self.assertIn("metallic double pulse", (man["must_include_by_chapter"].get("1") or []))
            ladder = man["reveal_ladder"]
            self.assertEqual(ladder["surface_event"]["chapter"], 3)
            self.assertNotIn("title", ladder)
            self.assertNotIn("arrival", ladder)
            approve_intent(ws, book=1)


class PrepStepsTests(unittest.TestCase):
    def test_prep_does_not_auto_approve_narrative(self):
        from factory.ui.factory_workflow import _prep_steps

        status = {
            "gates": {
                "concept": {"ok": True, "status": "ready"},
                "intent": {"ok": False, "status": "draft"},
                "narrative": {"ok": False, "status": "draft"},
                "bible": {"ok": False, "status": "draft"},
                "canon": {"ok": False, "status": "missing"},
                "plan": {"ok": False, "status": "draft", "chapters_planned": 0, "total": 10},
            }
        }
        steps = _prep_steps(status, prompts_ready=False)
        self.assertIn("compile-intent", steps)
        self.assertIn("approve-intent", steps)
        self.assertNotIn("approve-narrative", steps)
        self.assertNotIn("approve-bible", steps)
        self.assertNotIn("develop-narrative", steps)

    def test_prep_recompiles_stale_approved_intent(self):
        from factory.ui.factory_workflow import _prep_steps

        status = {
            "gates": {
                "concept": {"ok": True, "status": "ready"},
                "intent": {"ok": False, "status": "approved"},
                "canon": {"ok": True, "status": "ready"},
                "plan": {
                    "ok": False,
                    "status": "draft",
                    "chapters_planned": 0,
                    "total": 18,
                },
            }
        }
        steps = _prep_steps(status, prompts_ready=False)
        self.assertIn("compile-intent", steps)
        self.assertIn("approve-intent", steps)


if __name__ == "__main__":
    unittest.main()
