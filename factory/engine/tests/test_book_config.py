"""Tests for per-book chapter count config."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.book_config import (
    DEFAULT_CHAPTERS,
    get_total_chapters,
    set_total_chapters,
    sync_book_arc_total_chapters,
)


class BookConfigTests(unittest.TestCase):
    def test_set_and_get_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "test-ws"
            ws = root / "factory" / "workspaces" / ws_id
            (ws / "books" / "01").mkdir(parents=True)
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"book": 1, "total_chapters": 50}, allow_unicode=True),
                encoding="utf-8",
            )
            catalog = root / "catalog" / ws_id / "books" / "01-test"
            (catalog / "chapters").mkdir(parents=True)
            (catalog / "book.yaml").write_text(
                yaml.dump({"book": 1, "slug": "01-test", "total_chapters": 50}, allow_unicode=True),
                encoding="utf-8",
            )

            def fake_workspace_dir(name: str | None = None) -> Path:
                return ws

            def fake_catalog_series_dir(workspace_id: str | None = None) -> Path:
                return root / "catalog" / (workspace_id or ws_id)

            cfg = {
                "active_book": 1,
                "book_slugs": {"1": "01-test"},
                "book_slug": "01-test",
            }

            with patch("factory.engine.lib.operator_sync.workspace_dir", fake_workspace_dir), patch(
                "factory.engine.lib.book_config.workspace_dir", fake_workspace_dir
            ), patch(
                "factory.engine.lib.operator_sync.book_catalog_dir",
                lambda _wid, slug: root / "catalog" / ws_id / "books" / slug,
            ), patch("factory.engine.lib.operator_sync.load_config", lambda: cfg), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug",
                lambda _wid, book, cfg=None: "01-test",
            ):
                result = set_total_chapters(ws_id, 1, 20)
                self.assertTrue(result["ok"])
                self.assertEqual(result["total_chapters"], 20)
                self.assertEqual(get_total_chapters(ws_id, 1), 20)

                plan = json.loads((ws / "books" / "01" / "master_plan.json").read_text(encoding="utf-8"))
                self.assertEqual(plan["total_chapters"], 20)

    def test_sync_book_arc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            arc_path = nd / "book_arc.json"
            arc_path.write_text(
                json.dumps({"book_number": 1, "total_chapters": 50}, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertTrue(sync_book_arc_total_chapters(ws, 1, 10))
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
            self.assertEqual(arc["total_chapters"], 10)
            self.assertFalse(sync_book_arc_total_chapters(ws, 1, 10))

    def test_clamp_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "clamp-ws"
            ws = root / "factory" / "workspaces" / ws_id
            (ws / "books" / "01").mkdir(parents=True)
            (ws / "direction.yaml").write_text("book: 1\ntotal_chapters: 50\n", encoding="utf-8")

            with patch("factory.engine.lib.operator_sync.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.lib.book_config.workspace_dir", lambda _n=None: ws
            ), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug",
                lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no catalog")),
            ):
                r = set_total_chapters(ws_id, 1, 2)
                self.assertEqual(r["total_chapters"], 3)
                r2 = set_total_chapters(ws_id, 1, 999)
                self.assertEqual(r2["total_chapters"], 200)

    def test_default_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "empty-ws"
            ws.mkdir()
            (ws / "direction.yaml").write_text("book: 1\n", encoding="utf-8")
            with patch("factory.engine.lib.operator_sync.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.lib.book_config.workspace_dir", lambda _n=None: ws
            ), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug",
                lambda *_a, **_k: (_ for _ in ()).throw(ValueError()),
            ):
                self.assertEqual(get_total_chapters("empty-ws", 1), DEFAULT_CHAPTERS)

    def test_direction_beats_concept_and_stale_plan(self) -> None:
        """UI canonical (direction) wins over concept notes and empty master_plan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "concept-ws"
            ws = root / "factory" / "workspaces" / ws_id
            (ws / "books" / "01").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"book": 1, "total_chapters": 10}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "concept_status": "ready",
                        "chapter_count": 30,
                        "notes": "30 chapters, English gothic horror",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "books" / "01" / "master_plan.json").write_text(
                json.dumps({"book": 1, "total_chapters": 30, "chapter_plans": []}),
                encoding="utf-8",
            )

            with patch("factory.engine.lib.operator_sync.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.lib.book_config.workspace_dir", lambda _n=None: ws
            ), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug",
                lambda *_a, **_k: (_ for _ in ()).throw(ValueError()),
            ):
                self.assertEqual(get_total_chapters(ws_id, 1), 10)

    def test_ui_save_writes_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "sync-ws"
            ws = root / "factory" / "workspaces" / ws_id
            (ws / "books" / "01").mkdir(parents=True)
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"book": 1, "total_chapters": 30, "spice_level": 1}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "manifest.yaml").write_text("id: sync-ws\ntotal_chapters: 30\n", encoding="utf-8")
            (ws / "concept.yaml").write_text(
                yaml.dump({"notes": "30 chapters", "chapter_count": 30}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "books" / "01" / "master_plan.json").write_text(
                json.dumps({"book": 1, "total_chapters": 30, "chapter_plans": []}),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative" / "book_arc.json").write_text(
                json.dumps({"book_number": 1, "total_chapters": 30, "act_structure": [{"chapters": [1, 30]}]}),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative" / "knowledge_matrix.json").write_text(
                json.dumps(
                    {
                        "milestones": [1, 10, 25, 36, 50],
                        "characters": {"A": {"ch50": "late"}},
                    }
                ),
                encoding="utf-8",
            )
            catalog = root / "catalog" / ws_id / "books" / "01-test"
            catalog.mkdir(parents=True)
            (catalog / "book.yaml").write_text(
                yaml.dump({"book": 1, "slug": "01-test", "total_chapters": 30}, allow_unicode=True),
                encoding="utf-8",
            )

            def fake_ws(name: str | None = None) -> Path:
                return ws

            def fake_cat(_wid: str, slug: str) -> Path:
                return root / "catalog" / ws_id / "books" / slug

            cfg = {"active_book": 1}

            with patch("factory.engine.lib.operator_sync.workspace_dir", fake_ws), patch(
                "factory.engine.lib.book_config.workspace_dir", fake_ws
            ), patch("factory.engine.lib.operator_sync.book_catalog_dir", fake_cat), patch(
                "factory.engine.lib.operator_sync.load_config", lambda: cfg
            ), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug", lambda *_a, **_k: "01-test"
            ):
                result = set_total_chapters(ws_id, 1, 10)
                self.assertEqual(result["total_chapters"], 10)
                self.assertEqual(get_total_chapters(ws_id, 1), 10)

                concept = yaml.safe_load((ws / "concept.yaml").read_text(encoding="utf-8"))
                self.assertEqual(concept["chapter_count"], 10)
                self.assertIn("10 chapters", concept["notes"])

                direction = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
                self.assertEqual(direction["total_chapters"], 10)

                manifest = yaml.safe_load((ws / "manifest.yaml").read_text(encoding="utf-8"))
                self.assertEqual(manifest["total_chapters"], 10)

                plan = json.loads((ws / "books" / "01" / "master_plan.json").read_text(encoding="utf-8"))
                self.assertEqual(plan["total_chapters"], 10)

                arc = json.loads((ws / "bible" / "narrative" / "book_arc.json").read_text(encoding="utf-8"))
                self.assertEqual(arc["total_chapters"], 10)
                self.assertLessEqual(max(arc["act_structure"][-1]["chapters"]), 10)

                km = json.loads(
                    (ws / "bible" / "narrative" / "knowledge_matrix.json").read_text(encoding="utf-8")
                )
                self.assertTrue(all(m <= 10 for m in km["milestones"]))
                self.assertNotIn("ch50", km["characters"]["A"])

                cat = yaml.safe_load((catalog / "book.yaml").read_text(encoding="utf-8"))
                self.assertEqual(cat["total_chapters"], 10)

    def test_rescale_never_rewrites_chapter_prose(self) -> None:
        """countless in pipeline/catalog bodies survives 12→10 chapter rescale."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "prose-ws"
            ws = root / "factory" / "workspaces" / ws_id
            (ws / "books" / "01" / "pipeline" / "ready").mkdir(parents=True)
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"book": 1, "total_chapters": 12, "spice_level": 1}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "manifest.yaml").write_text("id: prose-ws\ntotal_chapters: 12\n", encoding="utf-8")
            (ws / "concept.yaml").write_text(
                yaml.dump({"notes": "12 chapters", "chapter_count": 12}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "books" / "01" / "master_plan.json").write_text(
                json.dumps({"book": 1, "total_chapters": 12, "chapter_plans": []}),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative" / "book_arc.json").write_text(
                json.dumps(
                    {"book_number": 1, "total_chapters": 12, "act_structure": [{"chapters": [1, 12]}]}
                ),
                encoding="utf-8",
            )
            prose = (
                "Clara had spent all of countless hours avoiding.\n"
                "Clara had noticed the avoidance in countless fragments of panic.\n"
            )
            pipe_path = ws / "books" / "01" / "pipeline" / "ready" / "ch_004.txt"
            pipe_path.write_text(prose, encoding="utf-8")
            catalog = root / "catalog" / ws_id / "books" / "01-test"
            (catalog / "chapters").mkdir(parents=True)
            (catalog / "book.yaml").write_text(
                yaml.dump({"book": 1, "slug": "01-test", "total_chapters": 12}, allow_unicode=True),
                encoding="utf-8",
            )
            cat_ch = catalog / "chapters" / "04-charcoal.md"
            cat_ch.write_text(prose, encoding="utf-8")

            def fake_ws(name: str | None = None) -> Path:
                return ws

            def fake_cat(_wid: str, slug: str) -> Path:
                return root / "catalog" / ws_id / "books" / slug

            cfg = {"active_book": 1}
            with patch("factory.engine.lib.operator_sync.workspace_dir", fake_ws), patch(
                "factory.engine.lib.book_config.workspace_dir", fake_ws
            ), patch("factory.engine.lib.operator_sync.book_catalog_dir", fake_cat), patch(
                "factory.engine.lib.operator_sync.load_config", lambda: cfg
            ), patch(
                "factory.engine.lib.operator_sync.resolve_book_slug", lambda *_a, **_k: "01-test"
            ):
                result = set_total_chapters(ws_id, 1, 10)
                self.assertEqual(result["total_chapters"], 10)
                self.assertEqual(pipe_path.read_text(encoding="utf-8"), prose)
                self.assertEqual(cat_ch.read_text(encoding="utf-8"), prose)
                self.assertNotIn("chapterless", pipe_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
