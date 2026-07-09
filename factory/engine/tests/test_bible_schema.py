"""Tests for bible schema validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from factory.engine.lib.bible_schema import relation_type_valid, validate_bible

ROOT = Path(__file__).resolve().parents[3]
CEO_BIBLE = ROOT / "factory" / "workspaces" / "ceo-contract" / "bible" / "series.json"


class TestRelationType(unittest.TestCase):
    def test_vi_enum_pass(self):
        self.assertTrue(relation_type_valid("mẹ ruột", "vi"))
        self.assertTrue(relation_type_valid("bạn thân", "vi"))

    def test_vi_invalid(self):
        self.assertFalse(relation_type_valid("mother", "vi"))
        self.assertFalse(relation_type_valid("attending physician", "vi"))

    def test_en_enum_pass(self):
        self.assertTrue(relation_type_valid("mother", "en"))
        self.assertTrue(relation_type_valid("former colleague", "en"))

    def test_en_free_label_pass(self):
        self.assertTrue(relation_type_valid("attending physician", "en"))
        self.assertTrue(relation_type_valid("uncle", "en"))
        self.assertTrue(relation_type_valid("best friend and fixer", "en"))
        self.assertTrue(relation_type_valid("business partner and Glass Meridian superior", "en"))

    def test_en_unicode_pass(self):
        self.assertTrue(relation_type_valid("former fiancée", "en"))
        self.assertTrue(relation_type_valid("ex-fiancée", "en"))

    def test_en_descriptive_pass(self):
        self.assertTrue(relation_type_valid("editor and mentor", "en"))
        self.assertTrue(relation_type_valid("younger cousin", "en"))
        self.assertTrue(relation_type_valid("childhood friend", "en"))
        self.assertTrue(relation_type_valid("head of security", "en"))
        self.assertFalse(relation_type_valid("", "en"))
        self.assertFalse(relation_type_valid("x", "en"))
        self.assertFalse(relation_type_valid("123", "en"))
        self.assertFalse(relation_type_valid("mẹ ruột", "en"))


class TestCeoContractBible(unittest.TestCase):
    @unittest.skipUnless(CEO_BIBLE.exists(), "ceo-contract bible missing")
    def test_series_json_passes_validate(self):
        bible = json.loads(CEO_BIBLE.read_text(encoding="utf-8"))
        errors = validate_bible(bible)
        cast = bible.get("supporting_cast", [])
        for i, c in enumerate(cast):
            rt = c.get("relation_type", "")
            self.assertTrue(
                relation_type_valid(rt, "en"),
                f"supporting_cast[{i}] relation_type={rt!r} should be valid",
            )
        self.assertEqual(errors, [], f"validate_bible errors: {errors}")


if __name__ == "__main__":
    unittest.main()
