"""Tests for PR-3 canon QC catch-net (machine_qc + canon_guard promote block)."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.canon_guard import run_canon_guard
from factory.engine.lib.canon_registry import (
    CanonRegistry,
    CharacterCanon,
)
from factory.engine.lib.catalog import promote_chapter
from factory.engine.lib.machine_qc import machine_pass, machine_qc
from factory.engine.paths import promoted_marker

ROOT = Path(__file__).resolve().parents[3]
CH7_FIXTURE = ROOT / "factory" / "workspaces" / "the-second-shadow" / "books" / "01" / "pipeline" / "ready" / "ch_007.txt"
WS_ID = "qc-promote-test"
BOOK_SLUG = "01-qc-test"

CANON_YAML = """\
characters:
  female_lead:
    canonical: Mara Vale
    allowed_aliases: []
  male_lead:
    canonical: Elias Crane
    allowed_aliases: []
pov_mode: third_person_limited
"""


def _registry_elias() -> CanonRegistry:
    return CanonRegistry(
        workspace_id=WS_ID,
        book=1,
        book_slug=BOOK_SLUG,
        chapter_count=10,
        target_language="en",
        pov_mode="third_person_limited",
        spice_max=1,
        characters={
            "female_lead": CharacterCanon(role="female_lead", canonical="Mara Vale"),
            "male_lead": CharacterCanon(
                role="male_lead",
                canonical="Elias Crane",
                forbidden_aliases=["Jude", "Jude Croft", "Asher", "Asher Croft"],
            ),
        },
    )


def _workspace_patches(ws: Path, catalog_root: Path):
    def _workspace_dir(name: str | None = None) -> Path:
        assert name == WS_ID, f"unexpected workspace {name!r}"
        return ws

    def _book_catalog_dir(workspace_id: str, book_slug: str) -> Path:
        return catalog_root / workspace_id / "books" / book_slug

    return (
        patch("factory.engine.paths.workspace_dir", _workspace_dir),
        patch("factory.engine.lib.catalog.workspace_dir", _workspace_dir),
        patch("factory.engine.lib.machine_qc.workspace_dir", _workspace_dir),
        patch("factory.engine.lib.canon_guard.workspace_dir", _workspace_dir),
        patch("factory.engine.lib.catalog.CATALOG", catalog_root),
        patch("factory.engine.lib.catalog.book_catalog_dir", _book_catalog_dir),
        patch("factory.engine.paths.book_catalog_dir", _book_catalog_dir),
    )


def _write_promote_workspace(root: Path, *, prose: str, slug: str = BOOK_SLUG) -> tuple[Path, Path]:
    ws = root / WS_ID
    ws.mkdir()
    catalog_root = root / "catalog"
    (ws / "canon_registry.yaml").write_text(CANON_YAML, encoding="utf-8")
    (ws / "direction.yaml").write_text(
        yaml.dump(
            {
                "id": WS_ID,
                "book": 1,
                "book_slug": slug,
                "total_chapters": 10,
                "target_language": "en",
                "spice_default": 1,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (ws / "manifest.yaml").write_text(
        yaml.dump({"id": WS_ID, "title": "QC Test"}),
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
    narr = ws / "bible" / "narrative"
    narr.mkdir(parents=True)
    (narr / "book_arc.json").write_text(
        json.dumps({"lead_internal_arc": {"Mara Vale": {}, "Jude": {}}}),
        encoding="utf-8",
    )
    book_dir = ws / "books" / "01"
    ready = book_dir / "pipeline" / "ready"
    ready.mkdir(parents=True)
    (ready / "ch_001.txt").write_text(prose, encoding="utf-8")
    (book_dir / "master_plan.json").write_text(
        json.dumps(
            {
                "book": 1,
                "total_chapters": 10,
                "chapter_plans": [
                    {
                        "chapter": 1,
                        "title": "Test",
                        "slug": "test",
                        "one_line_summary": "Test",
                        "beat_summary": "Test",
                        "must_happen": ["a", "b", "c"],
                        "must_not": ["x", "y"],
                        "opens_with": "Hook",
                        "cliffhanger": "End",
                        "signature_detail_hint": "detail",
                        "spice": 1,
                        "chapter_task": "Write chapter 1 (1600-1900 words).",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cat_book = catalog_root / WS_ID / "books" / slug
    cat_book.mkdir(parents=True, exist_ok=True)
    (cat_book / "book.yaml").write_text(
        yaml.dump({"book": 1, "slug": slug, "total_chapters": 10, "title": "QC Test"}),
        encoding="utf-8",
    )
    return ws, catalog_root


def _long_clean_third_person() -> str:
    """Third-person prose with canonical names, padded over min word count."""
    base = (
        "# Chapter 1: The Arrival\n\n"
        "Mara Vale stood on the porch and watched Elias Crane approach the gate. "
        "The wind carried dust across the cracked boards. She did not speak. "
        "Elias stopped at the steps and met her eyes with steady patience. "
    )
    return base + ("The house waited in silence while the road stayed empty. " * 280)


class TestMachineQcCanonNet(unittest.TestCase):
    def test_ch7_fixture_flags_pov_violation(self) -> None:
        if not CH7_FIXTURE.exists():
            self.skipTest("ch7 fixture missing")
        text = CH7_FIXTURE.read_text(encoding="utf-8")
        from factory.engine.lib.canon_prose_qc import canon_prose_issues

        issues = canon_prose_issues(text, _registry_elias())
        self.assertIn("pov_violation", issues)
        self.assertGreaterEqual(issues["pov_violation"]["count"], 3)

    def test_jude_flags_name_drift(self) -> None:
        reg = _registry_elias()
        from factory.engine.lib.canon_prose_qc import canon_prose_issues

        issues = canon_prose_issues("Jude walked beside Mara Vale in the garden.", reg)
        self.assertIn("name_drift", issues)
        self.assertEqual(issues["name_drift"][0]["found"], "Jude")
        self.assertEqual(issues["name_drift"][0]["canonical"], "Elias Crane")

    def test_machine_qc_needs_fix_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prose = "# Chapter 1\n\nJude held Mara Vale's hand.\n" + ("word " * 1600)
            ws, catalog_root = _write_promote_workspace(Path(tmp), prose=prose)
            with ExitStack() as stack:
                for p in _workspace_patches(ws, catalog_root):
                    stack.enter_context(p)
                issues = machine_qc(
                    (ws / "books" / "01" / "pipeline" / "ready" / "ch_001.txt").read_text(),
                    min_words=1500,
                    workspace_id=WS_ID,
                    book=1,
                )
            self.assertFalse(machine_pass(issues))
            self.assertIn("name_drift", issues)

    def test_spice_markers_not_flagged_by_keyword(self) -> None:
        """Keyword spice scan removed — ambient 'groaned' must not fail machine QC."""
        reg = _registry_elias()
        from factory.engine.lib.canon_prose_qc import canon_prose_issues

        ambient = "The floorboards groaned under her weight as she entered."
        intimate = "They moved together, thrusting harder until she moaned against his shoulder."
        for text in (ambient, intimate):
            issues = canon_prose_issues(text, reg)
            self.assertNotIn("spice_violation", issues)

    def test_clean_third_person_passes(self) -> None:
        reg = _registry_elias()
        from factory.engine.lib.canon_prose_qc import canon_prose_issues

        text = _long_clean_third_person()
        issues = canon_prose_issues(text, reg)
        self.assertNotIn("name_drift", issues)
        self.assertNotIn("pov_violation", issues)
        self.assertNotIn("spice_violation", issues)


class TestCanonGuardPromoteBlock(unittest.TestCase):
    def test_canon_guard_fail_blocks_promote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prose = (
                "# Chapter 1: Drift\n\n"
                "Jude met Mara Vale at the door.\n"
                + ("The night was cold and the wind would not rest. " * 280)
            )
            ws, catalog_root = _write_promote_workspace(Path(tmp), prose=prose)
            with ExitStack() as stack:
                for p in _workspace_patches(ws, catalog_root):
                    stack.enter_context(p)
                report = run_canon_guard(WS_ID, prose, chapter=1, book=1)
                self.assertFalse(report["passed"])

                out, reasons = promote_chapter(WS_ID, 1, 1, book_slug=BOOK_SLUG)
            self.assertIsNone(out)
            self.assertTrue(reasons)
            self.assertFalse(promoted_marker(ws, 1, 1).exists())
            cat_ch = catalog_root / WS_ID / "books" / BOOK_SLUG / "chapters"
            self.assertEqual(list(cat_ch.glob("*.md")), [])

    def test_clean_chapter_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prose = _long_clean_third_person()
            ws, catalog_root = _write_promote_workspace(Path(tmp), prose=prose)
            with ExitStack() as stack:
                for p in _workspace_patches(ws, catalog_root):
                    stack.enter_context(p)
                report = run_canon_guard(WS_ID, prose, chapter=1, book=1)
                self.assertTrue(report["passed"])

                out, reasons = promote_chapter(WS_ID, 1, 1, book_slug=BOOK_SLUG)
            self.assertIsNotNone(out)
            self.assertEqual(reasons, [])
            self.assertTrue(promoted_marker(ws, 1, 1).exists())


class TestCanonGuardRegistry(unittest.TestCase):
    def test_run_canon_guard_with_inline_registry(self) -> None:
        reg = _registry_elias()
        report = run_canon_guard(
            "unused",
            "Asher stood in the doorway while Mara watched.",
            chapter=3,
            registry=reg,
        )
        self.assertFalse(report["passed"])
        failed_ids = [c["id"] for c in report["checks"] if not c["passed"]]
        self.assertIn("CG-01", failed_ids)


if __name__ == "__main__":
    unittest.main()
