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
    build_canon_registry,
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
                                "title": "Arrival",
                                "slug": "arrival",
                                "one_line_summary": "Mara meets Elias.",
                                "beat_summary": "Elias Crane helps Mara Vale settle in.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": "Keys in hand.",
                                "cliffhanger": "A shadow moves.",
                                "signature_detail_hint": "cracked floorboard",
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
