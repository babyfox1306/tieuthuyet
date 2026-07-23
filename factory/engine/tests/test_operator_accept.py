"""Operator approve waives machine needs_fix; EN Latin-1 loanwords allowed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.engine.lib.catalog import (
    accept_catalog_chapter,
    build_frontmatter,
    parse_markdown,
    promote_chapter,
)
from factory.engine.lib.language import find_foreign_chars


class LatinExtendedForeignTests(unittest.TestCase):
    def test_protege_not_foreign_en(self):
        self.assertEqual(find_foreign_chars("You were Marsh's protégé.", "en"), [])

    def test_cafe_naive_resume_ok(self):
        text = "They met at a café; she was naïve about his résumé."
        self.assertEqual(find_foreign_chars(text, "en"), [])

    def test_vietnamese_specific_still_flags(self):
        # ư / đ are outside Latin-1 Supplement
        found = find_foreign_chars("người được chọn", "en")
        self.assertTrue(found)
        self.assertTrue(any(c in found for c in ("ư", "đ", "ợ", "ườ")))


class OperatorAcceptWaiveTests(unittest.TestCase):
    def test_accept_clears_catalog_needs_fix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cat = root / "catalog" / "demo" / "books" / "01-demo" / "chapters"
            cat.mkdir(parents=True)
            meta = {
                "series": "demo",
                "book": 1,
                "chapter": 3,
                "title": "Accepted",
                "needs_fix": ["stray_whitespace", "foreign:é"],
            }
            body = "Clean enough prose for the operator.\n"
            path = cat / "03-accepted.md"
            path.write_text(build_frontmatter(meta) + "\n\n" + body, encoding="utf-8")

            with mock.patch(
                "factory.engine.lib.catalog.book_catalog_dir",
                return_value=root / "catalog" / "demo" / "books" / "01-demo",
            ), mock.patch(
                "factory.engine.lib.catalog.catalog_series_dir",
                return_value=root / "catalog" / "demo",
            ), mock.patch(
                "factory.engine.lib.catalog.resolve_book_slug",
                return_value="01-demo",
            ), mock.patch(
                "factory.engine.lib.catalog.workspace_dir",
                return_value=root / "workspaces" / "demo",
            ), mock.patch(
                "factory.engine.lib.catalog.sync_chapter_pipeline_from_catalog",
                return_value=True,
            ):
                out = accept_catalog_chapter("demo", 1, 3, book_slug="01-demo")

            self.assertIsNotNone(out)
            new_meta, _ = parse_markdown(path)
            self.assertEqual(new_meta.get("needs_fix") or [], [])

    def test_manual_promote_writes_empty_needs_fix(self):
        """auto=False (operator) must not stamp machine format debt."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = root / "workspaces" / "demo"
            ready = ws / "books" / "01" / "pipeline" / "ready"
            ready.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                "id: demo\ntarget_language: en\nbook: 1\n", encoding="utf-8"
            )
            (ws / "manifest.yaml").write_text("id: demo\n", encoding="utf-8")
            prose = "# Chapter 1: Test\n\n" + ("word " * 400) + "\nprotégé café\n"
            (ready / "ch_001.txt").write_text(prose, encoding="utf-8")

            cat_book = root / "catalog" / "demo" / "books" / "01-demo"
            (cat_book / "chapters").mkdir(parents=True)
            (cat_book / "book.yaml").write_text(
                "book: 1\nslug: 01-demo\ntitle: Demo\nlanguage: en\n",
                encoding="utf-8",
            )

            with mock.patch(
                "factory.engine.lib.catalog.workspace_dir", return_value=ws
            ), mock.patch(
                "factory.engine.lib.catalog.CATALOG", root / "catalog"
            ), mock.patch(
                "factory.engine.paths.CATALOG", root / "catalog"
            ), mock.patch(
                "factory.engine.lib.catalog.resolve_book_slug",
                return_value="01-demo",
            ), mock.patch(
                "factory.engine.lib.catalog.book_catalog_dir",
                return_value=cat_book,
            ), mock.patch(
                "factory.engine.lib.catalog.catalog_series_dir",
                return_value=root / "catalog" / "demo",
            ), mock.patch(
                "factory.engine.lib.catalog.load_manifest",
                return_value={"id": "demo"},
            ), mock.patch(
                "factory.engine.lib.catalog.check_chapter_for_promote",
                return_value=[],
            ), mock.patch(
                "factory.engine.lib.catalog.export_gate_pass",
                return_value=True,
            ), mock.patch(
                "factory.engine.lib.canon_guard.run_canon_guard",
                return_value={"passed": True},
            ), mock.patch(
                "factory.engine.lib.catalog.sync_series_yaml",
                return_value=None,
            ), mock.patch(
                "factory.engine.lib.catalog.ensure_book_yaml",
                return_value=cat_book / "book.yaml",
            ), mock.patch(
                "factory.engine.lib.catalog.promoted_marker",
                side_effect=lambda _ws, _b, ch: ready.parent.parent
                / "pipeline"
                / "ready"
                / f"ch_{ch:03d}.promoted",
            ), mock.patch(
                "factory.engine.paths.promoted_marker",
                side_effect=lambda _ws, _b, ch: ready / f"ch_{ch:03d}.promoted",
            ):
                # promoted_marker is imported from paths into catalog — patch catalog attr
                marker = ready / "ch_001.promoted"
                with mock.patch(
                    "factory.engine.lib.catalog.promoted_marker",
                    side_effect=lambda *_a, **_k: marker,
                ):
                    out, reasons = promote_chapter(
                        "demo", 1, 1, book_slug="01-demo", auto=False
                    )

            self.assertEqual(reasons, [])
            self.assertIsNotNone(out)
            meta, _ = parse_markdown(out)
            self.assertEqual(meta.get("needs_fix") or [], [])


if __name__ == "__main__":
    unittest.main()
