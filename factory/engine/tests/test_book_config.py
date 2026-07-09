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

            with patch("factory.engine.lib.book_config.workspace_dir", fake_workspace_dir), patch(
                "factory.engine.lib.book_config.book_catalog_dir",
                lambda _wid, slug: root / "catalog" / ws_id / "books" / slug,
            ), patch("factory.engine.lib.book_config.load_config", lambda: cfg), patch(
                "factory.engine.lib.book_config.resolve_book_slug",
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

            with patch("factory.engine.lib.book_config.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.lib.book_config.load_config",
                lambda: {"book_slugs": {"1": "01-x"}, "active_book": 1},
            ), patch(
                "factory.engine.lib.book_config.resolve_book_slug",
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
            with patch("factory.engine.lib.book_config.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.lib.book_config.resolve_book_slug",
                lambda *_a, **_k: (_ for _ in ()).throw(ValueError()),
            ):
                self.assertEqual(get_total_chapters("empty-ws", 1), DEFAULT_CHAPTERS)


if __name__ == "__main__":
    unittest.main()
