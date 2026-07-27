"""Tests for canon registry and approve-plan hard gate."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.canon_registry import (
    CanonRegistryError,
    CharacterCanon,
    _norm_name,
    build_canon_registry,
    find_recurring_invented_plan_characters,
    scrub_recurring_invented_plan_characters,
    validate_plan_against_canon_registry,
)
from factory.engine.lib.master_plan import approve_plan

ROOT = Path(__file__).resolve().parents[3]
SECOND_SHADOW = ROOT / "factory" / "workspaces" / "the-second-shadow"

CANON_REGISTRY_YAML = """\
characters:
  female_lead:
    canonical: Mara Vale
    allowed_aliases: []
  male_lead:
    canonical: Elias Crane
    allowed_aliases: []
pov_mode: third_person_limited
"""


class CanonNameNormalizationTests(unittest.TestCase):
    def test_narrative_snake_key_matches_display_name(self) -> None:
        canon = CharacterCanon(
            role="male_lead",
            canonical="Victor Rhodes",
            allowed_aliases=["Victor", "Rhodes"],
        )
        self.assertEqual(_norm_name("victor_rhodes"), "victor rhodes")
        self.assertTrue(canon.is_allowed("victor_rhodes"))
        canon.register_forbidden("victor_rhodes")
        self.assertEqual(canon.forbidden_aliases, [])

    def test_plan_cast_parser_ignores_show_and_scrubs_undeclared_detective(self) -> None:
        allowed = {"Nadia Cole", "Victor Rhodes"}
        plans = [
            {
                "chapter": 1,
                "chapter_task": (
                    "Show Nadia Cole calling Detective Marcus Webb. "
                    "Show Victor Rhodes watching."
                ),
                "must_happen": ["Marcus Webb opens the file."],
            },
            {
                "chapter": 2,
                "chapter_task": "Detective Marcus Webb questions Nadia Cole.",
                "must_happen": ["Marcus Webb leaves."],
            },
        ]
        warnings = find_recurring_invented_plan_characters(plans, allowed)
        self.assertEqual([w["name"] for w in warnings], ["Marcus Webb"])
        scrubbed, notes = scrub_recurring_invented_plan_characters(plans, allowed)
        blob = json.dumps(scrubbed)
        self.assertNotIn("Marcus Webb", blob)
        self.assertIn("the unnamed detective", blob)
        self.assertIn("Nadia Cole", blob)
        self.assertIn("Victor Rhodes", blob)
        self.assertEqual(notes, ["Marcus Webb->the unnamed detective"])

    def test_plan_cast_scrub_does_not_replace_prohibitions_or_leading_verbs(self) -> None:
        allowed = {"Lena Hart", "Grant Hart"}
        plans = [
            {
                "chapter": 1,
                "must_not": [
                    "Do NOT reveal the victim's identity.",
                    "Do not show Grant entering Lena Hart's apartment.",
                ],
                "must_happen": ["Shows Grant removing the envelope."],
            },
            {
                "chapter": 2,
                "must_not": [
                    "Do NOT include a suspect confession.",
                    "Do not reveal the witness.",
                ],
                "must_happen": ["Shows Grant using his master credential."],
            },
        ]

        warnings = find_recurring_invented_plan_characters(plans, allowed)
        self.assertEqual(warnings, [])
        scrubbed, notes = scrub_recurring_invented_plan_characters(plans, allowed)
        self.assertEqual(scrubbed, plans)
        self.assertEqual(notes, [])


def _copy_second_shadow_fixture(dst: Path) -> None:
    """Copy minimal Second Shadow assets into an isolated temp workspace."""
    dst.mkdir(parents=True)
    (dst / "bible").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SECOND_SHADOW / "direction.yaml", dst / "direction.yaml")
    shutil.copy2(SECOND_SHADOW / "bible" / "series.json", dst / "bible" / "series.json")
    shutil.copytree(SECOND_SHADOW / "bible" / "narrative", dst / "bible" / "narrative")
    book_dir = dst / "books" / "01"
    book_dir.mkdir(parents=True)
    shutil.copy2(SECOND_SHADOW / "books" / "01" / "master_plan.json", book_dir / "master_plan.json")
    (dst / "canon_registry.yaml").write_text(CANON_REGISTRY_YAML, encoding="utf-8")


class CanonRegistrySecondShadowTests(unittest.TestCase):
    def test_build_registry_collects_forbidden_male_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            _copy_second_shadow_fixture(ws)
            registry = build_canon_registry(ws, book=1)
            male = registry.characters["male_lead"]
            forbidden_lower = {_norm(x) for x in male.forbidden_aliases}
            self.assertEqual(male.canonical, "Elias Crane")
            self.assertIn("asher croft", forbidden_lower)
            self.assertTrue(
                any("jude" in x for x in forbidden_lower),
                f"expected Jude variant in forbidden, got {male.forbidden_aliases}",
            )
            self.assertEqual(registry.source_male_lead_names.get("series.json"), "Elias Crane")
            self.assertEqual(registry.source_male_lead_names.get("narrative/*.json"), "Asher Croft")

    def test_validate_second_shadow_name_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            _copy_second_shadow_fixture(ws)
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            codes = {c["code"] for c in conflicts}
            self.assertIn("male_lead_cross_source_mismatch", codes)
            self.assertIn("male_lead_source_mismatch", codes)
            self.assertIn("forbidden_lead_name_in_plan", codes)

            by_source = {c["source"]: c for c in conflicts if c["code"] == "male_lead_source_mismatch"}
            self.assertEqual(by_source["narrative/*.json"]["value"], "Asher Croft")
            self.assertEqual(by_source["narrative/*.json"]["expected"], "Elias Crane")
            self.assertIn("master_plan.json", by_source)
            self.assertEqual(by_source["master_plan.json"]["expected"], "Elias Crane")
            # series.json matches canonical — should not be a source_mismatch row.
            self.assertNotIn("series.json", by_source)

    def test_approve_plan_blocked_second_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            _copy_second_shadow_fixture(ws)
            direction = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            direction["plan_status"] = "draft"
            (ws / "direction.yaml").write_text(
                yaml.dump(direction, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            with self.assertRaises(CanonRegistryError) as ctx:
                approve_plan(ws, book=1)
            codes = {c["code"] for c in ctx.exception.conflicts}
            self.assertIn("male_lead_source_mismatch", codes)
            self.assertIn("forbidden_lead_name_in_plan", codes)
            after = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertNotEqual(after.get("plan_status"), "approved")

    def test_spice_exceeds_max_fails_not_clamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            _copy_second_shadow_fixture(ws)
            direction = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            direction["spice_default"] = 1
            direction["spice_level"] = 1
            direction["spice_explicit_chapters"] = []
            (ws / "direction.yaml").write_text(
                yaml.dump(direction, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            plan_path = ws / "books" / "01" / "master_plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            for ch_plan in plan["chapter_plans"]:
                ch_plan["spice"] = 1
            plan["chapter_plans"][0]["spice"] = 3
            plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

            # Align sources so only spice fails (clean male names in plan text for ch1).
            ch1 = plan["chapter_plans"][0]
            blob = json.dumps(ch1)
            if "Jude" in blob or "Asher" in blob:
                self.skipTest("fixture ch1 still contains forbidden names — spice isolation only")

            conflicts = validate_plan_against_canon_registry(ws, book=1)
            spice_hits = [c for c in conflicts if c["code"] == "spice_exceeds_max"]
            self.assertTrue(spice_hits, f"expected spice_exceeds_max, got {conflicts}")
            hit = spice_hits[0]
            self.assertEqual(hit["value"], 3)
            self.assertEqual(hit["expected"], 1)
            self.assertIn("ch1", hit["source"])

    def test_spice_only_conflict_minimal_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "spice-test"
            ws.mkdir()
            (ws / "canon_registry.yaml").write_text(
                """\
characters:
  female_lead:
    canonical: Mara Vale
  male_lead:
    canonical: Elias Crane
""",
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": "spice-test",
                        "book": 1,
                        "book_slug": "01-spice-test",
                        "total_chapters": 1,
                        "target_language": "en",
                        "spice_default": 1,
                        "spice_level": 1,
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "leads": {
                            "female": {"name": "Mara Vale"},
                            "male": {"name": "Elias Crane"},
                        },
                        "supporting_cast": [],
                    }
                ),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative").mkdir()
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)
            (book_dir / "master_plan.json").write_text(
                json.dumps(
                    {
                        "book": 1,
                        "total_chapters": 1,
                        "chapter_plans": [
                            {
                                "chapter": 1,
                                "title": "Clean",
                                "slug": "clean",
                                "one_line_summary": "Mara meets Elias at the house.",
                                "beat_summary": "Elias Crane arrives to help Mara Vale.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": "The door opens.",
                                "cliffhanger": "A sound.",
                                "signature_detail_hint": "dust motes",
                                "spice": 3,
                                "chapter_task": "Write chapter 1 (1600-1900 words).",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            spice = [c for c in conflicts if c["code"] == "spice_exceeds_max"]
            self.assertEqual(len(spice), 1)
            self.assertEqual(spice[0]["value"], 3)
            self.assertEqual(spice[0]["expected"], 1)

    def test_missing_spice_max_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "no-spice-ceiling"
            ws.mkdir()
            (ws / "canon_registry.yaml").write_text(CANON_REGISTRY_YAML, encoding="utf-8")
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": "no-spice-ceiling",
                        "book": 1,
                        "spice_default": 1,
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CanonRegistryError) as ctx:
                build_canon_registry(ws, book=1)
            codes = {c["code"] for c in ctx.exception.conflicts}
            self.assertIn("missing_spice_max", codes)

    def test_spice_default_is_not_book_ceiling(self) -> None:
        """spice_default=1 + spice_level=3 must allow explicit chapters at spice 3."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "explicit-spice"
            ws.mkdir()
            (ws / "canon_registry.yaml").write_text(CANON_REGISTRY_YAML, encoding="utf-8")
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": "explicit-spice",
                        "book": 1,
                        "book_slug": "01-explicit-spice",
                        "total_chapters": 14,
                        "target_language": "en",
                        "spice_default": 1,
                        "spice_level": 3,
                        "spice_steamy_chapters": [6],
                        "spice_explicit_chapters": [9, 14],
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "leads": {
                            "female": {"name": "Mara Vale"},
                            "male": {"name": "Elias Crane"},
                        },
                        "supporting_cast": [],
                    }
                ),
                encoding="utf-8",
            )
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)
            (book_dir / "master_plan.json").write_text(
                json.dumps(
                    {
                        "book": 1,
                        "total_chapters": 14,
                        "chapter_plans": [
                            {
                                "chapter": ch,
                                "title": f"Ch {ch}",
                                "slug": f"ch-{ch}",
                                "one_line_summary": "Mara and Elias move the plot.",
                                "beat_summary": "Elias Crane supports Mara Vale.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": "The night held.",
                                "cliffhanger": "Something shifted.",
                                "signature_detail_hint": "cold metal",
                                "spice": spice,
                                "chapter_task": "Write chapter (1600-1900 words).",
                            }
                            for ch, spice in ((6, 2), (9, 3), (14, 3))
                        ],
                    }
                ),
                encoding="utf-8",
            )
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            spice_hits = [c for c in conflicts if c["code"] == "spice_exceeds_max"]
            self.assertEqual(spice_hits, [], spice_hits)

    def test_approve_plan_passes_clean_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "clean-test"
            ws.mkdir()
            (ws / "canon_registry.yaml").write_text(CANON_REGISTRY_YAML, encoding="utf-8")
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": "clean-test",
                        "book": 1,
                        "book_slug": "01-clean-test",
                        "total_chapters": 1,
                        "target_language": "en",
                        "spice_default": 1,
                        "spice_level": 1,
                        "plan_status": "draft",
                        "pov_mode": "third_person_limited",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "leads": {
                            "female": {"name": "Mara Vale"},
                            "male": {"name": "Elias Crane"},
                        },
                        "supporting_cast": [],
                        "world_rules": [],
                        "central_mystery": {
                            "question": "Who?",
                            "answer": "A long answer that should not appear early.",
                            "reveal_chapter": 10,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative").mkdir()
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)
            (book_dir / "master_plan.json").write_text(
                json.dumps(
                    {
                        "book": 1,
                        "total_chapters": 1,
                        "chapter_plans": [
                            {
                                "chapter": 1,
                                "title": "Arrival",
                                "slug": "arrival",
                                "one_line_summary": "Mara meets Elias.",
                                "beat_summary": "Elias Crane helps Mara Vale settle in.",
                                "must_happen": [
                                    "Mara arrives at the house.",
                                    "Elias greets her at the door.",
                                    "[ROMANCE] Their hands brush when he takes her bag.",
                                ],
                                "must_not": ["x", "y"],
                                "opens_with": "Keys turned in her palm.",
                                "cliffhanger": "A shadow moved behind the glass door.",
                                "signature_detail_hint": "cracked floorboard under the rug",
                                "spice": 1,
                                "chapter_task": "Write chapter 1 (1600-1900 words).",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            approve_plan(ws, book=1)
            direction = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertEqual(direction.get("plan_status"), "approved")

    def test_registry_book_slug_from_direction_not_global_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            _copy_second_shadow_fixture(ws)
            registry = build_canon_registry(ws, book=1)
            self.assertEqual(registry.book_slug, "01-the-second-shadow")


class AbsentMaleLeadCanonTests(unittest.TestCase):
    """Gothic / no-ML books: male_lead=M.I.A. must not treat twin/supporting as male lead."""

    def _write_mia_workspace(
        self,
        ws: Path,
        *,
        plan_blob: str = "Nora finds Della on the tape.",
        include_finn: bool = False,
    ) -> None:
        ws.mkdir(parents=True)
        (ws / "canon_registry.yaml").write_text(
            """\
characters:
  female_lead:
    canonical: Nora Vance
    allowed_aliases: []
  male_lead:
    canonical: M.I.A.
    allowed_aliases: []
pov_mode: third_person_limited
""",
            encoding="utf-8",
        )
        (ws / "direction.yaml").write_text(
            yaml.dump(
                {
                    "id": "mia-test",
                    "book": 1,
                    "book_slug": "01-mia-test",
                    "total_chapters": 1,
                    "target_language": "en",
                    "spice_default": 1,
                    "spice_level": 1,
                    "plan_status": "draft",
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (ws / "bible").mkdir()
        (ws / "bible" / "series.json").write_text(
            json.dumps(
                {
                    "leads": {
                        "female": {"name": "Nora Vance", "age": 29},
                        "male": {"name": "M.I.A.", "age": 18},
                    },
                    "supporting_cast": [
                        {"name": "Della Vance", "relation_to": "Nora Vance"},
                        {"name": "Ruth Vance", "relation_to": "Nora Vance"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        narr = ws / "bible" / "narrative"
        narr.mkdir()
        (narr / "book_arc.json").write_text(
            json.dumps(
                {
                    "lead_internal_arc": [
                        {"character": "Nora Vance", "internal_arc": "recovers memory"},
                        {"character": "Della Vance", "internal_arc": "is remembered"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        summary = plan_blob
        if include_finn:
            summary = plan_blob + " The tape names Finn Clark as her father."
        book_dir = ws / "books" / "01"
        book_dir.mkdir(parents=True)
        (book_dir / "master_plan.json").write_text(
            json.dumps(
                {
                    "book": 1,
                    "total_chapters": 1,
                    "chapter_plans": [
                        {
                            "chapter": 1,
                            "title": "Tape",
                            "slug": "tape",
                            "one_line_summary": summary,
                            "beat_summary": summary,
                            "must_happen": ["a", "b", "c"],
                            "must_not": ["x", "y"],
                            "opens_with": "Salt on the sill.",
                            "cliffhanger": "A second voice.",
                            "signature_detail_hint": "reel hiss",
                            "spice": 1,
                            "chapter_task": "Write chapter 1 (1700-1900 words).",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_mia_does_not_treat_twin_as_male_lead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "mia-clean"
            self._write_mia_workspace(ws)
            registry = build_canon_registry(ws, book=1)
            self.assertEqual(registry.characters["male_lead"].canonical, "M.I.A.")
            self.assertNotIn("narrative/*.json", registry.source_male_lead_names)
            self.assertNotIn("master_plan.json", registry.source_male_lead_names)
            forbidden = {_norm(x) for x in registry.characters["male_lead"].forbidden_aliases}
            self.assertNotIn("della vance", forbidden)
            self.assertNotIn("della", forbidden)
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            codes = {c["code"] for c in conflicts}
            self.assertNotIn("male_lead_cross_source_mismatch", codes)
            self.assertNotIn("forbidden_lead_name_in_plan", codes)

    def test_mia_flags_invented_plan_male_but_not_della(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "mia-finn"
            self._write_mia_workspace(ws, include_finn=True)
            registry = build_canon_registry(ws, book=1)
            self.assertEqual(
                registry.source_male_lead_names.get("master_plan.json"), "Finn Clark"
            )
            forbidden = {_norm(x) for x in registry.characters["male_lead"].forbidden_aliases}
            self.assertIn("finn clark", forbidden)
            self.assertNotIn("della", forbidden)
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            codes = {c["code"] for c in conflicts}
            self.assertIn("male_lead_source_mismatch", codes)
            della_hits = [
                c
                for c in conflicts
                if c["code"] == "forbidden_lead_name_in_plan" and "Della" in str(c["value"])
            ]
            self.assertEqual(della_hits, [])
            finn_hits = [
                c
                for c in conflicts
                if c["code"] == "forbidden_lead_name_in_plan" and "Finn" in str(c["value"])
            ]
            self.assertTrue(finn_hits)

    def test_is_absent_male_lead_helpers(self) -> None:
        from factory.engine.lib.canon_registry import is_absent_male_lead

        self.assertTrue(is_absent_male_lead("M.I.A."))
        self.assertTrue(is_absent_male_lead("N/A"))
        self.assertTrue(is_absent_male_lead("none"))
        self.assertTrue(is_absent_male_lead("Unassigned (no male lead)"))
        self.assertTrue(is_absent_male_lead("Unassigned"))
        self.assertFalse(is_absent_male_lead("Elias Crane"))

    def test_invented_doctor_not_in_allowlist(self) -> None:
        from factory.engine.lib.canon_registry import find_invented_doctors

        allowed = {"Dr. Ovid", "Ovid", "Iris Callahan", "Iris"}
        hits = find_invented_doctors(
            "Beside Iris, Dr. Mateo Reyes reaches for the tray. Later Dr. Ovid calls.",
            allowed,
        )
        self.assertEqual(hits, ["Dr. Mateo Reyes"])

    def test_recurring_invented_person_warns_but_texture_is_silent(self) -> None:
        from factory.engine.lib.canon_registry import (
            find_recurring_invented_plan_characters,
        )

        plans = [
            {
                "chapter": 7,
                "beat_summary": (
                    "Nadia Cole studies the young victim named Elise Marchetti. "
                    "Blackridge Holdings suppressed the report in Mariville."
                ),
            },
            {
                "chapter": 20,
                "beat_summary": (
                    "Victor Rhodes meets counsel at Blackridge Holdings."
                ),
            },
            {
                "chapter": 38,
                "signature_detail_hint": (
                    "Elise Marchetti's photograph remains inside the file."
                ),
            },
        ]
        warnings = find_recurring_invented_plan_characters(
            plans,
            {"Nadia Cole", "Nadia", "Cole", "Victor Rhodes", "Victor", "Rhodes"},
        )
        self.assertEqual([w["name"] for w in warnings], ["Elise Marchetti"])
        self.assertEqual(warnings[0]["chapters"], [7, 38])

    def test_one_chapter_minor_person_is_silent(self) -> None:
        from factory.engine.lib.canon_registry import (
            find_recurring_invented_plan_characters,
        )

        plans = [
            {
                "chapter": 3,
                "beat_summary": "A courier named Mina Hart leaves the envelope.",
            }
        ]
        self.assertEqual(
            find_recurring_invented_plan_characters(plans, set()),
            [],
        )

    def test_allowed_cast_reads_bible_cast_and_structured_concept(self) -> None:
        from factory.engine.lib.canon_registry import collect_allowed_cast_names

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "cast-sources"
            (ws / "bible").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.safe_dump({"book": 1, "total_chapters": 3}),
                encoding="utf-8",
            )
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(
                    {
                        "author_directive": (
                            "LOCKED CAST:\n"
                            "- ORIGIN KILLER (backstory): Julian Croft — fixed."
                        ),
                        "characters": [
                            {"name": "Concept Person", "role": "victim"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "cast": [{"name": "Bible Cast Person"}],
                        "supporting_cast": [{"name": "Supporting Person"}],
                    }
                ),
                encoding="utf-8",
            )
            allowed = collect_allowed_cast_names(ws, 1)
            self.assertIn("Concept Person", allowed)
            self.assertIn("Julian Croft", allowed)
            self.assertIn("Bible Cast Person", allowed)
            self.assertIn("Supporting Person", allowed)

    def test_story_state_rejects_mateo(self) -> None:
        from factory.engine.lib.canon_registry import validate_story_state_cast

        ws = Path(__file__).resolve().parents[2] / "workspaces" / "the-paper-oracle"
        if not ws.exists():
            self.skipTest("the-paper-oracle workspace missing")
        poisoned = {
            "timeline": ["03:12 AM: Dr. Mateo Reyes arrives to assist"],
            "character_status": {
                "Iris Callahan": {
                    "relationship_other": "Subordinate to Dr. Reyes",
                }
            },
        }
        conflicts = validate_story_state_cast(ws, poisoned, book=1)
        codes = {c["code"] for c in conflicts}
        self.assertIn("invented_doctor_in_story_state", codes)

class ReplanClearTests(unittest.TestCase):
    def test_clear_master_plan_for_replan(self) -> None:
        from factory.engine.lib.master_plan import clear_master_plan_for_replan

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "replan-ws"
            ws.mkdir()
            (ws / "direction.yaml").write_text(
                yaml.dump({"id": "replan-ws", "book": 1, "plan_status": "approved"}),
                encoding="utf-8",
            )
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)
            plan_path = book_dir / "master_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "book": 1,
                        "title": "Keep Title",
                        "total_chapters": 10,
                        "chapter_plans": [{"chapter": 1, "title": "Old"}],
                    }
                ),
                encoding="utf-8",
            )
            (book_dir / "plan_raw_001_003.txt").write_text("raw", encoding="utf-8")
            clear_master_plan_for_replan(ws, 1)
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("chapter_plans"), [])
            self.assertEqual(data.get("title"), "Keep Title")
            self.assertFalse((book_dir / "plan_raw_001_003.txt").exists())
            direction = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertEqual(direction.get("plan_status"), "draft")


def _norm(s: str) -> str:
    return s.strip().lower()


@unittest.skipUnless(SECOND_SHADOW.exists(), "the-second-shadow workspace fixture missing")
class CanonRegistryLiveWorkspaceReadOnlyTests(unittest.TestCase):
    """Read-only check against real workspace — does not modify files."""

    def test_live_workspace_would_block_approve(self) -> None:
        ws = SECOND_SHADOW
        if not (ws / "canon_registry.yaml").exists():
            with self.assertRaises(CanonRegistryError):
                validate_plan_against_canon_registry(ws, book=1)
        else:
            conflicts = validate_plan_against_canon_registry(ws, book=1)
            self.assertTrue(conflicts)


if __name__ == "__main__":
    unittest.main()
