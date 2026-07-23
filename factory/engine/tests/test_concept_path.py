"""Per-book concept.yaml resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml


class TestConceptPath(unittest.TestCase):
    def test_book1_uses_root_concept(self) -> None:
        from factory.engine.lib.narrative_schema import concept_path, load_concept, save_concept_yaml

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "concept.yaml").write_text(
                yaml.dump({"title": "Book One", "concept_status": "ready"}),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text("book: 1\n", encoding="utf-8")
            self.assertEqual(concept_path(ws, 1).name, "concept.yaml")
            self.assertEqual(load_concept(ws, 1)["title"], "Book One")

    def test_book2_isolated_from_book1(self) -> None:
        from factory.engine.lib.narrative_schema import concept_path, load_concept, save_concept_yaml

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "concept.yaml").write_text(
                yaml.dump({"title": "Book One", "concept_status": "ready"}),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text("book: 2\n", encoding="utf-8")
            (ws / "books" / "02").mkdir(parents=True)
            save_concept_yaml(ws, {"title": "Book Two", "concept_status": "draft"}, 2)
            self.assertTrue(str(concept_path(ws, 2)).endswith("books\\02\\concept.yaml") or str(concept_path(ws, 2)).endswith("books/02/concept.yaml"))
            self.assertEqual(load_concept(ws, 2)["title"], "Book Two")
            self.assertEqual(load_concept(ws, 1)["title"], "Book One")
            # Missing book-3 must not fall back to book 1
            self.assertEqual(load_concept(ws, 3), {})


if __name__ == "__main__":
    unittest.main()
