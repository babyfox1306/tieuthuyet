"""pen_name → dc:creator: resolve, sync, EG-14 gate, fail-loud export."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import yaml

from factory.engine.lib.catalog import export_epub, resolve_pen_name
from factory.engine.lib.export_gate import check_eg14_pen_name
from factory.engine.lib.workspace_metadata import (
    sync_manifest_from_direction,
    write_pen_name,
)


class PenNameResolveTests(unittest.TestCase):
    def test_direction_wins_over_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspaces" / "demo"
            ws.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                "id: demo\npen_name: From Direction\n", encoding="utf-8"
            )
            (ws / "manifest.yaml").write_text(
                "id: demo\npen_name: From Manifest\n", encoding="utf-8"
            )
            with mock.patch("factory.engine.lib.catalog.workspace_dir", return_value=ws):
                with mock.patch(
                    "factory.engine.lib.catalog.catalog_series_dir",
                    return_value=root / "catalog" / "demo",
                ):
                    self.assertEqual(resolve_pen_name("demo"), "From Direction")

    def test_falls_back_to_manifest_when_direction_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspaces" / "demo"
            ws.mkdir(parents=True)
            (ws / "direction.yaml").write_text("id: demo\npen_name: ''\n", encoding="utf-8")
            (ws / "manifest.yaml").write_text(
                "id: demo\npen_name: From Manifest\n", encoding="utf-8"
            )
            with mock.patch("factory.engine.lib.catalog.workspace_dir", return_value=ws):
                with mock.patch(
                    "factory.engine.lib.catalog.catalog_series_dir",
                    return_value=root / "catalog" / "demo",
                ):
                    self.assertEqual(resolve_pen_name("demo"), "From Manifest")


class PenNameSyncTests(unittest.TestCase):
    def test_sync_manifest_copies_pen_name(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "direction.yaml").write_text(
                "id: demo\npen_name: Reynard Frost\ntarget_language: en\n",
                encoding="utf-8",
            )
            (ws / "manifest.yaml").write_text("id: demo\n", encoding="utf-8")
            sync_manifest_from_direction(ws)
            man = yaml.safe_load((ws / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(man.get("pen_name"), "Reynard Frost")

    def test_write_pen_name_keeps_direction_and_manifest_equal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "ws"
            ws.mkdir()
            (ws / "direction.yaml").write_text("id: ws\npen_name: ''\n", encoding="utf-8")
            (ws / "manifest.yaml").write_text("id: ws\n", encoding="utf-8")
            with mock.patch(
                "factory.engine.lib.catalog.catalog_series_dir",
                return_value=root / "catalog" / "ws",
            ):
                with mock.patch(
                    "factory.engine.lib.workspace_metadata.remember_last_pen_name"
                ):
                    write_pen_name(ws, "Reynard Frost", remember=False)
            d = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            m = yaml.safe_load((ws / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(d.get("pen_name"), "Reynard Frost")
            self.assertEqual(m.get("pen_name"), "Reynard Frost")


class EG14PenNameTests(unittest.TestCase):
    def test_empty_pen_name_fails(self):
        with mock.patch(
            "factory.engine.lib.catalog.resolve_pen_name", return_value=""
        ):
            r = check_eg14_pen_name("any")
            self.assertFalse(r["passed"])
            self.assertEqual(r["id"], "EG-14")
            self.assertIn("Pen name is empty", r["detail"])

    def test_set_pen_name_passes(self):
        with mock.patch(
            "factory.engine.lib.catalog.resolve_pen_name", return_value="Reynard Frost"
        ):
            r = check_eg14_pen_name("any")
            self.assertTrue(r["passed"])


class WriteEpubCreatorTests(unittest.TestCase):
    def test_empty_author_raises(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch(
                "factory.engine.lib.catalog.resolve_pen_name", return_value=""
            ):
                with mock.patch(
                    "factory.engine.lib.catalog.load_chapter_items",
                    return_value=[
                        (Path("c.md"), {"chapter": 1, "title": "One"}, "She ran.")
                    ],
                ):
                    with self.assertRaises(ValueError) as ctx:
                        export_epub("demo", "01-demo", out)
                    self.assertIn("Pen name is empty", str(ctx.exception))

    def test_writes_dc_creator(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch(
                "factory.engine.lib.catalog.resolve_pen_name",
                return_value="Reynard Frost",
            ):
                with mock.patch(
                    "factory.engine.lib.catalog.export_language", return_value="en"
                ):
                    with mock.patch(
                        "factory.engine.lib.catalog.book_display_title",
                        return_value="Demo Book",
                    ):
                        with mock.patch(
                            "factory.engine.lib.catalog.ensure_epub_identifier",
                            return_value="urn:uuid:test",
                        ):
                            with mock.patch(
                                "factory.engine.lib.catalog.load_chapter_items",
                                return_value=[
                                    (
                                        Path("c.md"),
                                        {"chapter": 1, "title": "One"},
                                        "She ran home.",
                                    )
                                ],
                            ):
                                with mock.patch(
                                    "factory.engine.lib.catalog.resolve_chapter_display",
                                    return_value=("One", "", "She ran home."),
                                ):
                                    path = export_epub("demo", "01-demo", out)
            with zipfile.ZipFile(path) as zf:
                opf = next(n for n in zf.namelist() if n.endswith(".opf"))
                text = zf.read(opf).decode("utf-8")
            self.assertIn("<dc:creator id=\"creator\">Reynard Frost</dc:creator>", text)


if __name__ == "__main__":
    unittest.main()
