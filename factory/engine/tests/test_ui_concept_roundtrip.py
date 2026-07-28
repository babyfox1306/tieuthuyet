"""Concept form round-trip — no top-level key may be silently dropped on save."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from factory.engine.lib.narrative_schema import intentional_early_reveal, load_concept

RICH_CONCEPT = {
    "concept_status": "draft",
    "target_language": "en",
    "title": "Anti Hero Test",
    "logline": "She kills the guilty and the reader knows it from page one.",
    "author_directive": "LOCKED CAST — Elle Reyes (lead). " + "x" * 200,
    "surface_plot": "A podcaster reopens a cold case.",
    "true_plot": "She is the executioner; the reader knows from chapter 1.",
    "ending_book1": "Kroll dies; Elle is leashed.",
    "hook_book2": "Who holds the file?",
    "must_include": ["Two-way hunt"],
    "must_avoid": ["Unreliable narrator hiding the killing"],
    "notes": "38 chapters.",
    "intentional_early_reveal": True,
    # Hand-edited keys with no form widget — must survive untouched.
    "chapter_count": 38,
    "pov": {"character": "Elle Reyes", "mode": "first_person", "tense": "past"},
    "chapter_map": {1: "Elle finishes a target cleanly", 2: "Podcast fame as cover"},
    "characters": [{"name": "Elle Reyes", "role": "lead"}],
    "must_include_by_chapter": {"1": ["reader learns she kills"]},
    "gate_overrides": ["map_fidelity"],
}


def _form_body(concept: dict) -> dict:
    """Payload the concept form posts back for an unmodified page."""
    return {
        "target_language": concept.get("target_language", "en"),
        "title": concept.get("title", ""),
        "logline": concept.get("logline", ""),
        "author_directive": concept.get("author_directive", ""),
        "surface_plot": concept.get("surface_plot", ""),
        "true_plot": concept.get("true_plot", ""),
        "intentional_early_reveal": concept.get("intentional_early_reveal", False),
        "ending_book1": concept.get("ending_book1", ""),
        "hook_book2": concept.get("hook_book2", ""),
        "must_include": list(concept.get("must_include") or []),
        "must_avoid": list(concept.get("must_avoid") or []),
        "notes": concept.get("notes", ""),
        "characters": list(concept.get("characters") or []),
    }


class ConceptRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "anti-hero-test"
        self.ws.mkdir(parents=True)
        self._write(RICH_CONCEPT)

        from factory.ui import server

        self.server = server
        patcher = mock.patch.object(server, "workspace_dir", lambda ws_id: self.root / ws_id)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Keep the save path free of direction/manifest side effects.
        for name in ("_sync_workspace_language", "_sync_direction_manifest_from_concept"):
            p = mock.patch.object(server, name, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch(
            "factory.engine.lib.operator_sync.write_title_everywhere",
            lambda *a, **k: None,
        )
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data: dict) -> None:
        (self.ws / "concept.yaml").write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _raw(self) -> str:
        return (self.ws / "concept.yaml").read_text(encoding="utf-8")

    def test_flag_saved_as_top_level_boolean(self):
        self._write({**RICH_CONCEPT, "intentional_early_reveal": False})
        body = _form_body(RICH_CONCEPT)
        body["intentional_early_reveal"] = True
        self.server.save_concept("anti-hero-test", body)

        self.assertIn("\nintentional_early_reveal: true\n", self._raw())
        saved = load_concept(self.ws)
        self.assertIs(saved["intentional_early_reveal"], True)
        self.assertTrue(intentional_early_reveal(ws=self.ws))
        # Never smuggled into a text field.
        for key in ("notes", "author_directive", "true_plot"):
            self.assertNotIn("intentional_early_reveal", str(saved.get(key) or ""))

    def test_unchecked_saves_false_not_missing(self):
        body = _form_body(RICH_CONCEPT)
        body["intentional_early_reveal"] = False
        self.server.save_concept("anti-hero-test", body)

        self.assertIn("\nintentional_early_reveal: false\n", self._raw())
        self.assertFalse(intentional_early_reveal(ws=self.ws))

    def test_existing_flag_survives_body_without_key(self):
        """Backward compat: a save that omits the field must not reset it."""
        body = _form_body(RICH_CONCEPT)
        body.pop("intentional_early_reveal")
        self.server.save_concept("anti-hero-test", body)

        self.assertTrue(intentional_early_reveal(ws=self.ws))

    def test_form_load_reflects_flag(self):
        payload = self.server.concept_to_json("anti-hero-test")
        self.assertIs(payload["concept"]["intentional_early_reveal"], True)

        self._write({**RICH_CONCEPT, "intentional_early_reveal": False})
        payload = self.server.concept_to_json("anti-hero-test")
        self.assertIs(payload["concept"]["intentional_early_reveal"], False)

    def test_roundtrip_keeps_every_top_level_key(self):
        before = load_concept(self.ws)
        self.server.save_concept("anti-hero-test", _form_body(RICH_CONCEPT))
        after = load_concept(self.ws)

        lost = sorted(set(before) - set(after))
        self.assertEqual(lost, [], f"UI save dropped concept keys: {lost}")
        for key in ("chapter_count", "pov", "chapter_map", "characters",
                    "must_include_by_chapter", "gate_overrides"):
            self.assertEqual(after[key], before[key], key)

    def test_partial_save_does_not_wipe_untouched_text_fields(self):
        self.server.save_concept(
            "anti-hero-test", {"target_language": "en", "title": "Renamed"}
        )
        after = load_concept(self.ws)

        self.assertEqual(after["title"], "Renamed")
        self.assertEqual(after["notes"], RICH_CONCEPT["notes"])
        self.assertEqual(after["true_plot"], RICH_CONCEPT["true_plot"])
        self.assertEqual(after["must_include"], RICH_CONCEPT["must_include"])
        self.assertTrue(after["intentional_early_reveal"])

    def test_characters_form_field_roundtrip(self):
        body = _form_body(RICH_CONCEPT)
        body["characters"] = [
            {"name": "Elle Reyes", "role": "lead"},
            {"name": "Elise Marchetti", "role": "cold-case victim"},
        ]
        self.server.save_concept("anti-hero-test", body)
        after = load_concept(self.ws)
        self.assertEqual(after["characters"][1]["name"], "Elise Marchetti")
        payload = self.server.concept_to_json("anti-hero-test")
        self.assertEqual(payload["concept"]["characters"][1]["role"], "cold-case victim")

    def _valid_import(self) -> dict:
        return {
            "concept_status": "draft",
            "target_language": "en",
            "chapter_count": 2,
            "spice_level": 3,
            "spice_default": 0,
            "spice_explicit_chapters": [1, 2],
            "spice_schedule": {1: 3, 2: 2},
            "title": "The Test",
            "pen_name": "N. Vale",
            "logline": "Line one.\nLine two.\n",
            "surface_plot": "Surface\nplot\n",
            "true_plot": "True\nplot\n",
            "intentional_early_reveal": False,
            "pov": {
                "character": "Elle Reyes",
                "mode": "first_person",
                "tense": "past",
                "single_pov": True,
            },
            "characters": [
                {"name": "Elle Reyes", "role": "protagonist"},
                {"name": "Damien Kroll", "role": "antagonist"},
            ],
            "chapter_map": {
                1: "Flat beat",
                2: {
                    "title": "The File",
                    "beat": "Rich beat",
                    "required_beats": ["Open the file"],
                    "must_include": ["red thread"],
                    "must_not_reveal": ["the leak"],
                    "ending": "A knock",
                    "final_line": "She knew.",
                },
            },
            "author_directive": "Directive line 1\nDirective line 2\n",
            "ending_book1": "Case closes.\n",
            "hook_book2": "The file returns.\n",
            "must_include": ["Two-way hunt"],
            "must_avoid": ["Name drift"],
            "notes": "Note one.\nNote two.\n",
        }

    def test_import_fails_loud_without_partial_payload(self):
        raw = self._valid_import()
        raw.pop("true_plot")
        result = self.server.parse_concept_yaml(
            yaml.dump(raw, allow_unicode=True, sort_keys=False),
            fallback_language="en",
        )
        self.assertFalse(result["ok"])
        self.assertNotIn("concept", result)
        self.assertTrue(any("true_plot" in error for error in result["errors"]))

    def test_import_reports_yaml_line_and_column(self):
        result = self.server.parse_concept_yaml(
            "title: ok\n  broken: indent\n", fallback_language="en"
        )
        self.assertFalse(result["ok"])
        self.assertRegex(result["errors"][0], r"dòng \d+, cột \d+")

    def test_import_rejects_wrong_types_and_incomplete_pov(self):
        raw = self._valid_import()
        raw["intentional_early_reveal"] = "false"
        raw["must_include"] = "not-a-list"
        raw["pov"].pop("single_pov")
        result = self.server.parse_concept_yaml(
            yaml.dump(raw, allow_unicode=True, sort_keys=False),
            fallback_language="en",
        )
        self.assertFalse(result["ok"])
        joined = "\n".join(result["errors"])
        self.assertIn("intentional_early_reveal", joined)
        self.assertIn("must_include", joined)
        self.assertIn("single_pov", joined)

    def test_import_rejects_invalid_spice_schedule(self):
        raw = self._valid_import()
        raw["spice_schedule"] = {1: 3}
        result = self.server.parse_concept_yaml(
            yaml.dump(raw, allow_unicode=True, sort_keys=False),
            fallback_language="en",
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("explicit but has no" in error for error in result["errors"])
        )

    def test_unknown_key_warns_and_survives_import_export(self):
        raw = self._valid_import()
        raw["future_metadata"] = {"keep": True}
        imported = self.server.parse_concept_yaml(
            yaml.dump(raw, allow_unicode=True, sort_keys=False),
            fallback_language="en",
        )
        self.assertTrue(imported["ok"])
        self.assertTrue(any("future_metadata" in warning for warning in imported["warnings"]))
        self.assertEqual(imported["passthrough"]["future_metadata"], {"keep": True})

    def test_import_warns_on_machine_qc_foreign_characters_and_does_not_save(self):
        before = self._raw()
        raw = self._valid_import()
        raw["logline"] = "This English concept contains tiếng Việt."
        imported = self.server.parse_concept_yaml(
            yaml.dump(raw, allow_unicode=True, sort_keys=False),
            fallback_language="en",
        )
        self.assertTrue(imported["ok"])
        self.assertTrue(
            any("logline" in warning and "target_language=en" in warning
                for warning in imported["warnings"])
        )
        self.assertEqual(self._raw(), before)

    def test_export_import_roundtrip_keeps_rich_map_and_multiline_text(self):
        original = self._valid_import()
        body = {
            **{key: original[key] for key in self.server.CONCEPT_FORM_KEYS},
            "target_language": original["target_language"],
            "_concept_passthrough": {
                key: value
                for key, value in original.items()
                if key not in self.server.CONCEPT_FORM_KEYS
            },
        }
        exported = self.server.export_concept_yaml("anti-hero-test", body)
        for key in self.server.CONCEPT_FREE_TEXT_KEYS:
            self.assertRegex(exported["yaml"], rf"(?m)^{key}: \|")

        imported = self.server.parse_concept_yaml(
            exported["yaml"], fallback_language="en"
        )
        self.assertTrue(imported["ok"], imported.get("errors"))
        for key in self.server.CONCEPT_FORM_KEYS:
            self.assertEqual(imported["concept"][key], original[key], key)
        self.assertEqual(imported["passthrough"]["chapter_count"], 2)
        self.assertEqual(imported["passthrough"]["spice_schedule"], {1: 3, 2: 2})


class UnnamedPlotRoleGateTests(unittest.TestCase):
    def test_anonymous_victim_warns_without_cast_name(self):
        from factory.engine.lib.narrative_schema import warn_unnamed_plot_roles

        warns = warn_unnamed_plot_roles(
            {
                "surface_plot": "She reopens the murder of a young woman.",
                "chapter_map": {3: "cold-case murder of a young woman"},
                "characters": [],
                "author_directive": "No locked cast here.",
            }
        )
        self.assertTrue(any("unnamed_plot_role:victim" in e for e in warns))

    def test_role_without_name_blocks(self):
        from factory.engine.lib.narrative_schema import concept_unnamed_plot_role_errors

        errs = concept_unnamed_plot_role_errors(
            {"characters": [{"name": "", "role": "cold-case victim"}]}
        )
        self.assertTrue(any("role_without_name" in e for e in errs))

    def test_named_victim_in_characters_passes(self):
        from factory.engine.lib.narrative_schema import (
            concept_unnamed_plot_role_errors,
            warn_unnamed_plot_roles,
        )

        concept = {
            "surface_plot": "She reopens the murder of a young woman.",
            "chapter_map": {3: "cold-case murder of a young woman"},
            "characters": [{"name": "Elise Marchetti", "role": "cold-case victim"}],
        }
        self.assertEqual(concept_unnamed_plot_role_errors(concept), [])
        self.assertEqual(warn_unnamed_plot_roles(concept), [])


if __name__ == "__main__":
    unittest.main()
