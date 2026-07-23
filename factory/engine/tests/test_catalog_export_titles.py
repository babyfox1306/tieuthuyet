"""Tests for catalog slug / EN export title structure."""

from __future__ import annotations

import unittest

from factory.engine.lib.catalog import normalize_chapter_slug, chapter_filename, reader_title, text_to_catalog_md
from factory.engine.lib.export_gate import prepare_chapter_for_export


class SlugNormalizeTests(unittest.TestCase):
    def test_strips_leading_chapter_number(self):
        self.assertEqual(normalize_chapter_slug(1, "01-the-terms-of-reference"), "the-terms-of-reference")
        self.assertEqual(normalize_chapter_slug(11, "11-the-moles-confession"), "the-moles-confession")
        self.assertEqual(normalize_chapter_slug(6, "the-dissenting-vote"), "the-dissenting-vote")

    def test_filename_not_doubled(self):
        self.assertEqual(
            chapter_filename(1, "01-the-terms-of-reference"),
            "01-the-terms-of-reference.md",
        )


class EnExportTitleTests(unittest.TestCase):
    def test_drops_polluted_en_subtitle(self):
        meta = {
            "chapter": 6,
            "title": "The Dissenting Vote",
            "subtitle": 'The motion carries," Renn said, his voice smooth. "The inquiry finds Marek.',
        }
        title, subtitle, body = prepare_chapter_for_export(meta, "Body prose here.", "en")
        self.assertEqual(title, "The Dissenting Vote")
        self.assertIsNone(subtitle)

    def test_eg03_fails_truncated_opening(self):
        from factory.engine.lib.export_gate import check_eg03_header

        checks = check_eg03_header(
            {"chapter": 6, "title": "The Dissenting Vote"},
            "the inevitable; she had volunteered.",
            "en",
            6,
        )
        self.assertTrue(any(not c["passed"] and "truncated opening" in str(c.get("detail")) for c in checks))

    def test_eg03_fails_polluted_subtitle(self):
        from factory.engine.lib.export_gate import check_eg03_header

        checks = check_eg03_header(
            {
                "chapter": 6,
                "title": "The Dissenting Vote",
                "subtitle": 'The motion carries," Renn said. "The inquiry finds Marek responsible for everything here.',
            },
            "Iris waited at the table.",
            "en",
            6,
        )
        self.assertTrue(
            any(not c["passed"] and "polluted EN subtitle" in str(c.get("detail")) for c in checks)
        )

    def test_reader_title_en(self):
        self.assertEqual(
            reader_title({"chapter": 1, "title": "The Terms of Reference"}, lang="en"),
            "Chapter 1: The Terms of Reference",
        )

    def test_text_to_catalog_md_en_no_subtitle_from_dialogue(self):
        text = (
            '# Chapter 6: The Dissenting Vote\n\n'
            'Iris waited.\n\n'
            '"The motion carries," Renn said.\n'
        )
        _md, meta = text_to_catalog_md(
            text,
            series_id="the-kessler-line",
            book=1,
            chapter=6,
            title="The Dissenting Vote",
            slug="the-dissenting-vote",
            target_lang="en",
        )
        self.assertEqual(meta.get("title"), "The Dissenting Vote")
        self.assertNotIn("subtitle", meta)


if __name__ == "__main__":
    unittest.main()
