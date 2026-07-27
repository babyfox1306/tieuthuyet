"""P0 plan locks: romance hard-off, pre-resolved leak, semantic seal."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.narrative_compiler import (
    compile_chapter_narrative,
    seal_chapter_semantics,
    semantic_present,
)
from factory.engine.lib.romance_policy import (
    ROMANCE_SECTION_END,
    ROMANCE_SECTION_START,
    enforce_romance_off,
    romance_violations,
    scrub_plan_romance,
    strip_romance_section,
)

LEDGER = {
    "clues": [
        {
            "id": "C001",
            "description": "Nadia's thumb-tap tic is noticed by a listener in a podcast comment.",
            "plant_chapter": 1,
            "payoff_chapter": 34,
        },
        {
            "id": "C007",
            "description": "A photograph of Julian Croft's yacht shows a recently replaced fuel line.",
            "plant_chapter": 18,
            "payoff_chapter": 34,
        },
    ],
    "major_reveals": [
        {
            "id": "MR05",
            "description": "Full origin reveal: Nadia's first kill, Julian Croft, in a staged boating accident.",
            "chapter": 34,
            "required_clues": ["C001", "C007"],
        }
    ],
    "red_herrings": [],
}
MATRIX: dict = {"milestones": [1], "characters": {}}
THREADS: dict = {"threads": []}


def _compiled(chapter: int) -> dict:
    return compile_chapter_narrative(LEDGER, MATRIX, THREADS, chapter)


class RomanceHardOffTests(unittest.TestCase):
    def test_strip_section_replaces_opt_in_block(self) -> None:
        role = (
            "head\n"
            f"{ROMANCE_SECTION_START}\n"
            "## ROMANCE (OPT-IN)\n- micro-beat bắt buộc\n"
            f"{ROMANCE_SECTION_END}\n"
            "tail\n"
        )
        out = strip_romance_section(role)
        self.assertNotIn("OPT-IN", out)
        self.assertNotIn("micro-beat bắt buộc", out)
        self.assertIn("TẮT CỨNG", out)
        self.assertIn("head", out)
        self.assertIn("tail", out)

    def test_strip_section_appends_when_markers_missing(self) -> None:
        out = strip_romance_section("no markers here")
        self.assertIn("TẮT CỨNG", out)

    def test_scrub_drops_romance_beats_and_sentences(self) -> None:
        plan = {
            "chapter": 29,
            "must_happen": [
                "Nadia analyses the flash drive.",
                "[ROMANCE] She feels the dark intimacy of the trap.",
            ],
            "chapter_task": (
                "Write 1800 words. Show the worm prep. "
                "The romance micro-beat is the attraction she cannot admit."
            ),
            "spice_note": "No explicit content. The romance micro-beat is dark intimacy.",
            "emotional_beat": "Fear laced with attraction.",
        }
        scrubbed, notes = scrub_plan_romance(plan)
        self.assertEqual(len(scrubbed["must_happen"]), 1)
        self.assertNotIn("romance", scrubbed["chapter_task"].lower())
        self.assertIn("Show the worm prep", scrubbed["chapter_task"])
        self.assertEqual(
            scrubbed["spice_note"], "Spice 0 — tension is plot-driven only."
        )
        self.assertNotIn("attraction", scrubbed["emotional_beat"].lower())
        self.assertTrue(notes)
        self.assertEqual(romance_violations(scrubbed), [])

    def test_must_not_prohibitions_are_not_violations(self) -> None:
        plan = {
            "chapter": 1,
            "must_happen": ["Plot beat."],
            "must_not": [
                "Must not include any romantic or attraction beats.",
                "No love interest framing for Rhodes.",
            ],
        }
        scrubbed, _ = scrub_plan_romance(plan)
        self.assertEqual(len(scrubbed["must_not"]), 2)
        self.assertEqual(romance_violations(scrubbed), [])

    def test_fully_romantic_field_falls_back_clean(self) -> None:
        plan = {
            "chapter": 7,
            "must_happen": ["Plot beat."],
            "carries_to_next": "The attraction neither will name",
            "opens_with": "A charged look of desire for him",
        }
        scrubbed, _ = scrub_plan_romance(plan)
        self.assertEqual(romance_violations(scrubbed), [])
        self.assertTrue(scrubbed["carries_to_next"])
        self.assertTrue(scrubbed["opens_with"])

    def test_enforce_flags_material_repair_for_regen(self) -> None:
        plans = [
            {
                "chapter": 5,
                "must_happen": [
                    "Plot beat only.",
                    "[ROMANCE] A charged glance across the table.",
                ],
                "beat_summary": "Nadia builds the trap. Their attraction flares.",
            }
        ]
        cleaned, notes, violations = enforce_romance_off(plans)
        # Marker-only beat keeps its action, loses the romance framing.
        self.assertEqual(len(cleaned[0]["must_happen"]), 2)
        self.assertNotIn("[ROMANCE]", " ".join(cleaned[0]["must_happen"]))
        self.assertTrue(any(v.startswith("material:") for v in violations))
        self.assertTrue(any(n.startswith("light:") for n in notes))
        self.assertEqual(romance_violations(cleaned[0]), [])

    def test_clean_plan_needs_no_regen(self) -> None:
        plans = [
            {
                "chapter": 6,
                "must_happen": ["Nadia wipes the drive."],
                "beat_summary": "Cold procedural pressure.",
                "must_not": ["No romantic framing."],
            }
        ]
        _, notes, violations = enforce_romance_off(plans)
        self.assertEqual(notes, [])
        self.assertEqual(violations, [])


class SemanticSealTests(unittest.TestCase):
    def test_mismatched_scheduled_clue_is_replaced_by_canonical(self) -> None:
        plan = {
            "chapter": 1,
            "must_happen": [
                "Nadia plants clue C001: an offhand detail about Elise's last possession.",
                "The watcher texts her.",
            ],
        }
        sealed, notes = seal_chapter_semantics(_compiled(1), plan)
        joined = " ".join(sealed["must_happen"]).lower()
        self.assertIn("thumb-tap", joined)
        self.assertNotIn("last possession", joined)
        self.assertTrue(any("replaced_mismatched_beat" in n for n in notes))

    def test_matching_clue_line_is_kept_as_written(self) -> None:
        plan = {
            "chapter": 1,
            "must_happen": [
                "[CLUE C001] A listener notices Nadia's thumb-tap tic in a podcast comment.",
            ],
        }
        sealed, notes = seal_chapter_semantics(_compiled(1), plan)
        self.assertIn("thumb-tap", sealed["must_happen"][0])
        self.assertFalse([n for n in notes if "replaced" in n])

    def test_unscheduled_id_token_is_stripped_but_prose_kept(self) -> None:
        plan = {
            "chapter": 12,
            "must_happen": ["C007 is paid off: Nadia meets the scarred watcher."],
            "beat_summary": "She links MR05 to the gala photograph.",
        }
        sealed, notes = seal_chapter_semantics(_compiled(12), plan)
        line = sealed["must_happen"][0]
        self.assertNotIn("C007", line)
        self.assertIn("scarred watcher", line)
        self.assertNotIn("MR05", sealed["beat_summary"])
        self.assertTrue(any("stripped_unscheduled_id" in n for n in notes))

    def test_wrong_reveal_semantic_is_replaced(self) -> None:
        plan = {
            "chapter": 34,
            "must_happen": [
                "MR05 is revealed: Rhodes has had a copy of Nadia's playbook all along.",
            ],
        }
        sealed, _ = seal_chapter_semantics(_compiled(34), plan)
        joined = " ".join(sealed["must_happen"]).lower()
        self.assertIn("julian croft", joined)
        self.assertIn("boating", joined)
        self.assertNotIn("playbook", joined)

    def test_semantic_present_rejects_id_only_match(self) -> None:
        content = "Nadia's thumb-tap tic is noticed by a listener in a podcast comment."
        self.assertFalse(semantic_present("C001 is planted somehow.", content))
        self.assertTrue(
            semantic_present("A listener notices her thumb-tap tic on the podcast.", content)
        )


class PlanChoicesTests(unittest.TestCase):
    def _workspace(self, tmp: str) -> Path:
        ws = Path(tmp) / "leak-ws"
        (ws / "bible" / "narrative").mkdir(parents=True)
        (ws / "concept.yaml").write_text(
            yaml.dump(
                {
                    "title": "T",
                    "author_directive": "THE LEAK: one of the three betrays her (decide which at plan time).",
                    "characters": [
                        {"name": "Sasha Okafor", "role": "network lawyer"},
                        {"name": "Priya Anand", "role": "network coroner"},
                        {"name": "Wren Delgado", "role": "network hacker"},
                    ],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (ws / "direction.yaml").write_text(
            "book: 1\ntarget_language: en\nnarrative_status: approved\n"
            "narrative_profile: thriller\n",
            encoding="utf-8",
        )
        nd = ws / "bible" / "narrative"
        ledger = {
            "clues": [
                {
                    "id": "C009",
                    "description": "Wren Delgado's access logs show a 3 AM download.",
                    "plant_chapter": 26,
                    "payoff_chapter": 28,
                }
            ],
            "major_reveals": [
                {
                    "id": "MR04",
                    "description": "The network betrayal: one of the three leaks to Rhodes.",
                    "chapter": 28,
                    "required_clues": ["C009"],
                }
            ],
        }
        (nd / "mystery_ledger.json").write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        (nd / "knowledge_matrix.json").write_text(
            json.dumps({"milestones": [1], "characters": {}}), encoding="utf-8"
        )
        (nd / "threads.json").write_text(json.dumps({"threads": []}), encoding="utf-8")
        return ws

    def test_resolves_single_leak_and_persists(self) -> None:
        from factory.engine.lib.plan_choices import (
            plan_choices_path,
            resolve_plan_choices,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            choices = resolve_plan_choices(ws)
            leak = choices["network_leak"]
            self.assertEqual(leak["value"], "Wren Delgado")
            self.assertEqual(leak["cardinality"], 1)
            self.assertCountEqual(
                leak["not_chosen"], ["Sasha Okafor", "Priya Anand"]
            )
            self.assertTrue(plan_choices_path(ws).exists())

            # Idempotent: a second call keeps the first decision.
            again = resolve_plan_choices(ws)
            self.assertEqual(again["network_leak"]["value"], "Wren Delgado")

    def test_operator_override_wins(self) -> None:
        from factory.engine.lib.plan_choices import resolve_plan_choices

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            resolve_plan_choices(ws)
            out = resolve_plan_choices(ws, overrides={"network_leak": "Priya Anand"})
            self.assertEqual(out["network_leak"]["value"], "Priya Anand")
            self.assertEqual(out["network_leak"]["resolved_by"], "operator")
            self.assertIn("Wren Delgado", out["network_leak"]["not_chosen"])

    def test_payload_choice_is_resolved_with_non_leaks(self) -> None:
        from factory.engine.lib.narrative_compiler import compile_act_constraints
        from factory.engine.lib.plan_choices import resolve_plan_choices

        with tempfile.TemporaryDirectory() as tmp:
            ws = self._workspace(tmp)
            resolve_plan_choices(ws)
            act = compile_act_constraints(ws, 26, 28)
            choice = act["global_choices"][0]
            self.assertEqual(choice["status"], "resolved")
            self.assertEqual(choice["value"], "Wren Delgado")
            self.assertCountEqual(
                choice["non_leaks"], ["Sasha Okafor", "Priya Anand"]
            )
            self.assertIn("second leak", choice["constraint"].lower())


class PlanChunkWiringTests(unittest.TestCase):
    """End-to-end wiring of the three P0 locks around one Outliner call."""

    SOURCE = Path("factory/workspaces/the-cold-case-girl")

    def setUp(self) -> None:
        if not (self.SOURCE / "books" / "01" / "master_plan.json").exists():
            self.skipTest("cold-case workspace missing")

    def _dirty_chunk(self) -> str:
        plans = []
        for ch in (1, 2, 3):
            plans.append(
                {
                    "chapter": ch,
                    "title": f"Chapter {ch}",
                    "slug": f"ch-{ch}",
                    "one_line_summary": "Nadia works the case.",
                    "beat_summary": "She works the case. Their attraction flickers.",
                    "must_happen": [
                        "C001 is planted: a boat watcher photographs the marina.",
                        "MR05 is teased: Rhodes keeps a playbook of her methods.",
                        "[ROMANCE] A charged silence between Nadia and Rhodes.",
                    ],
                    "must_not": ["No early reveal.", "No romantic subplot."],
                    "opens_with": "'You missed one,' he says.",
                    "cliffhanger": "The drive is already copied.",
                    "signature_detail_hint": "A cracked marina bollard.",
                    "emotional_beat": "Cold rage.",
                    "spice": 0,
                    "spice_note": "No explicit content; the romance micro-beat is dark intimacy.",
                    "chapter_task": "Write 1600-1900 words.",
                    "carries_to_next": "The watcher follows her home.",
                }
            )
        return json.dumps({"act": [1, 3], "chapter_plans": plans})

    def test_chunk_is_stripped_sealed_and_regenerated(self) -> None:
        import shutil
        from unittest.mock import patch

        from factory.engine.lib import master_plan as mp

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "cold-case"
            shutil.copytree(self.SOURCE, ws)
            calls: list[dict] = []

            def fake_router(role, payload, **kwargs):
                calls.append({"system": kwargs.get("system_override") or "", "payload": payload})
                return self._dirty_chunk(), {"model": "fake"}

            with patch.object(mp, "call_9router", side_effect=fake_router):
                plans, _ = mp._fetch_act_plans_guarded(ws, 1, 1, 3, "act1")

            # Romance section never reaches the model; hard-off block replaces it.
            self.assertTrue(calls)
            self.assertNotIn("OPT-IN", calls[0]["system"])
            self.assertIn("TẮT CỨNG", calls[0]["system"])
            # Leak arrives pre-resolved, with the other two marked non-leaks.
            payload = json.loads(calls[0]["payload"])
            choice = payload["plan_choices"][0]
            self.assertEqual(choice["status"], "resolved")
            self.assertTrue(choice["non_leaks"])
            self.assertNotIn(choice["value"], choice["non_leaks"])
            # Romance survived scrub-worthy content → chunk was re-generated.
            self.assertGreaterEqual(len(calls), 2)
            self.assertIn("regen_notes", json.loads(calls[1]["payload"]))

            blob = json.dumps(plans, ensure_ascii=False).lower()
            self.assertNotIn("[romance]", blob)
            self.assertNotIn("dark intimacy", blob)
            # Semantic seal: ledger meaning wins over the model's invention.
            ch1 = next(p for p in plans if p["chapter"] == 1)
            mh1 = " ".join(ch1["must_happen"]).lower()
            self.assertIn("thumb-tap", mh1)
            self.assertNotIn("boat watcher", mh1)
            # MR05 is not scheduled in ch1-3 → the ID must not ride on that prose.
            self.assertNotIn("mr05", blob)


if __name__ == "__main__":
    unittest.main()
