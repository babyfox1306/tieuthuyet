"""Tests for per-workspace book slug resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.paths import resolve_book_slug


class ResolveBookSlugTests(unittest.TestCase):
    def test_uses_direction_slug_for_active_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "the-blue-hour"
            ws = root / "factory" / "workspaces" / ws_id
            ws.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": ws_id,
                        "book": 1,
                        "book_slug": "01-the-blue-hour",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            def fake_workspace_dir(name: str | None = None) -> Path:
                return ws

            def fake_catalog_series_dir(workspace_id: str | None = None) -> Path:
                return root / "catalog" / (workspace_id or ws_id)

            cfg = {
                "active_book": 1,
                "book_slugs": {"1": "01-the-glass-meridian"},
                "book_slug": "01-the-glass-meridian",
            }

            with patch("factory.engine.paths.workspace_dir", fake_workspace_dir), patch(
                "factory.engine.paths.catalog_series_dir", fake_catalog_series_dir
            ), patch("factory.engine.paths.load_config", lambda: cfg):
                slug = resolve_book_slug(ws_id, 1)
            self.assertEqual(slug, "01-the-blue-hour")

    def test_scans_catalog_for_non_active_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "glass-meridian"
            ws = root / "factory" / "workspaces" / ws_id
            ws.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": ws_id,
                        "book": 2,
                        "book_slug": "02-the-altered-name",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            cat = root / "catalog" / ws_id / "books" / "01-the-glass-meridian"
            cat.mkdir(parents=True)

            with patch("factory.engine.paths.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.paths.catalog_series_dir",
                lambda wid=None: root / "catalog" / (wid or ws_id),
            ), patch("factory.engine.paths.load_config", lambda: {"active_book": 2}):
                slug = resolve_book_slug(ws_id, 1)
            self.assertEqual(slug, "01-the-glass-meridian")

    def test_fallback_slug_from_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_id = "new-series"
            ws = root / "factory" / "workspaces" / ws_id
            ws.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"id": ws_id, "book": 1}, allow_unicode=True),
                encoding="utf-8",
            )

            with patch("factory.engine.paths.workspace_dir", lambda _n=None: ws), patch(
                "factory.engine.paths.catalog_series_dir",
                lambda wid=None: root / "catalog" / (wid or ws_id),
            ), patch("factory.engine.paths.load_config", lambda: {"active_book": 1}):
                slug = resolve_book_slug(ws_id, 1)
            self.assertEqual(slug, "01-new-series")


if __name__ == "__main__":
    unittest.main()
