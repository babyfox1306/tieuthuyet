"""Rolling catalog archive — one folder per book."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.catalog import backup_catalog_book
from factory.engine.paths import catalog_archive_dir


class CatalogArchiveTests(unittest.TestCase):
    def test_backup_replaces_previous_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog" / "series-a" / "books" / "01-book" / "chapters"
            catalog.mkdir(parents=True)
            (catalog / "01-x.md").write_text("---\nchapter: 1\n---\n\nHi.", encoding="utf-8")

            archive_base = root / "archive"

            with patch("factory.engine.lib.catalog.CATALOG", root / "catalog"), patch(
                "factory.engine.lib.catalog.book_catalog_dir",
                lambda ws, slug: root / "catalog" / ws / "books" / slug,
            ), patch(
                "factory.engine.lib.catalog.catalog_archive_dir",
                lambda ws, slug: archive_base / f"catalog_{ws}_{slug}",
            ):
                dest1 = backup_catalog_book("series-a", "01-book")
                self.assertTrue((dest1 / "chapters" / "01-x.md").exists())
                (catalog / "02-y.md").write_text("---\nchapter: 2\n---\n\nMore.", encoding="utf-8")
                dest2 = backup_catalog_book("series-a", "01-book")
                self.assertEqual(dest1, dest2)
                self.assertFalse(list(archive_base.glob("catalog_series-a_01-book_*")))
                self.assertTrue((dest2 / "chapters" / "01-x.md").exists())
                self.assertTrue((dest2 / "chapters" / "02-y.md").exists())


if __name__ == "__main__":
    unittest.main()
