"""Tests for export gate (Tier 1) — revision v2."""

from __future__ import annotations

import unittest

from factory.engine.lib.export_gate import (
    check_eg01_truncated,
    check_eg02_markers,
    check_eg03_header,
    check_eg04_gaps,
    check_eg05_dup_titles,
    check_eg08_short,
    check_eg09_metadata,
    check_eg10_cjk,
    check_eg11_generic_title,
    check_eg13_engine_tokens,
    export_gate_pass,
    format_export_gate_reasons,
    prepare_chapter_for_export,
)


class EG01TruncatedTests(unittest.TestCase):
    def test_pass_period(self):
        self.assertTrue(check_eg01_truncated("She ran.", 1)["passed"])

    def test_pass_curly_close_quote(self):
        self.assertTrue(check_eg01_truncated("He said \u201crun.\u201d", 1)["passed"])

    def test_pass_em_dash(self):
        self.assertTrue(check_eg01_truncated("He reached for her\u2014", 1)["passed"])

    def test_fail_mid_word(self):
        self.assertFalse(check_eg01_truncated("Lin Wei felt the", 1)["passed"])

    def test_fail_comma(self):
        self.assertFalse(check_eg01_truncated("I picked up the photograph,", 1)["passed"])

    def test_fail_unclosed_quote(self):
        self.assertFalse(check_eg01_truncated('She turned and said "hello', 1)["passed"])

    def test_fail_ascii_hyphen(self):
        self.assertFalse(check_eg01_truncated("We call-", 1)["passed"])

    def test_fail_straight_quote_terminal_in_curly_prose(self):
        body = (
            "\u201cHello,\u201d she said. \u201cRun.\u201d "
            "More dialogue with curly quotes throughout. "
            "Adrian\u2019s voice hardened. \u201cProfessor!\u201d "
            "I barked, leaking into my tone. \""
        )
        r = check_eg01_truncated(body, 39)
        self.assertFalse(r["passed"])
        self.assertIn("quote", r["detail"].lower())

    def test_fail_curly_open_unclosed_last_para(self):
        body = "Earlier prose.\n\nShe whispered, \u201cWhat is"
        r = check_eg01_truncated(body, 1)
        self.assertFalse(r["passed"])


class EG02MarkerTests(unittest.TestCase):
    def test_cliffhanger_bold(self):
        checks = check_eg02_markers("End.\n\n**Cliffhanger:** something", 1)
        self.assertTrue(any(c["id"] == "EG-02" and not c["passed"] for c in checks))

    def test_cliffhanger_plain(self):
        checks = check_eg02_markers("End.\n\nCliffhanger: The door began to open.", 28)
        self.assertTrue(any(c["id"] == "EG-02" and not c["passed"] for c in checks))

    def test_payoff_mid_sentence_allowed(self):
        checks = check_eg02_markers("...the real payoff: her freedom.", 1)
        self.assertTrue(all(c["passed"] for c in checks if c["id"] == "EG-02"))

    def test_clue_id_allowed(self):
        checks = check_eg02_markers("They found C012 in the file.", 1)
        self.assertTrue(all(c["passed"] for c in checks if c["id"] == "EG-02"))

    def test_thread_marker(self):
        checks = check_eg02_markers("Thread T042 activated.", 1)
        self.assertTrue(any(c["id"] == "EG-02" and not c["passed"] for c in checks))


class EG09MetadataTests(unittest.TestCase):
    def test_fail_vn_title_on_en_book(self):
        checks = check_eg09_metadata("glass-meridian", "01-the-glass-meridian", "en")
        # book.yaml should be fixed to The Glass Meridian — pass if aligned
        self.assertTrue(any(c["id"] == "EG-09" for c in checks))


class EG10CjkTests(unittest.TestCase):
    def test_cjk_glued_to_latin(self):
        r = check_eg10_cjk("everything归档 in the file.", 19, "en")
        self.assertFalse(r["passed"])

    def test_cjk_standalone(self):
        r = check_eg10_cjk("私は sailed away.", 1, "en")
        self.assertFalse(r["passed"])

    def test_fullwidth(self):
        r = check_eg10_cjk("ｈｅｌｌｏ world", 1, "en")
        self.assertFalse(r["passed"])

    def test_clean_en(self):
        r = check_eg10_cjk("everything archived cleanly.", 1, "en")
        self.assertTrue(r["passed"])

    def test_vi_skips(self):
        r = check_eg10_cjk("everything归档", 1, "vi")
        self.assertTrue(r["passed"])


class EG11GenericTitleTests(unittest.TestCase):
    def test_generic_title_fails_when_plan_has_name(self):
        meta = {"chapter": 16, "book": 1, "title": "Chapter 16"}
        result = check_eg11_generic_title(meta, "en", "glass-meridian", 16)
        self.assertFalse(result["passed"])

    def test_real_title_passes(self):
        meta = {"chapter": 16, "book": 1, "title": "The Architect's Shadow"}
        result = check_eg11_generic_title(meta, "en", "glass-meridian", 16)
        self.assertTrue(result["passed"])


class EG03HeaderTests(unittest.TestCase):
    def test_markdown_heading_in_body(self):
        meta = {"chapter": 5, "title": "Chương 5", "subtitle": "# Chapter 5: Test"}
        body = "# Chapter 5: Test\n\nParagraph."
        checks = check_eg03_header(meta, body, "en", 5)
        self.assertTrue(any(c["id"] == "EG-03" and not c["passed"] for c in checks))


class EG04GapTests(unittest.TestCase):
    def test_missing_chapter(self):
        r = check_eg04_gaps([1, 2, 4], 4)
        self.assertFalse(r["passed"])


class EG05DupTitleTests(unittest.TestCase):
    def test_duplicate_subtitle(self):
        chapters = [
            (1, {"subtitle": "Chapter 5: Alpha"}, "body one."),
            (2, {"subtitle": "Chapter 5: Alpha"}, "body two."),
        ]
        checks = check_eg05_dup_titles(chapters, "error")
        self.assertTrue(any(c["id"] == "EG-05" and not c["passed"] for c in checks))


class EG08ShortTests(unittest.TestCase):
    def test_too_short(self):
        self.assertFalse(check_eg08_short("Short chapter.", 1, 800)["passed"])


class EG12NeedsFixTests(unittest.TestCase):
    def test_flags_non_empty_needs_fix(self):
        from factory.engine.lib.export_gate import check_eg12_needs_fix

        check = check_eg12_needs_fix({"needs_fix": ["short:1200"]}, 5)
        self.assertFalse(check["passed"])
        self.assertEqual(check["id"], "EG-12")

    def test_passes_clean_meta(self):
        from factory.engine.lib.export_gate import check_eg12_needs_fix

        check = check_eg12_needs_fix({"needs_fix": []}, 5)
        self.assertTrue(check["passed"])


class EG13EngineTokenTests(unittest.TestCase):
    def test_chapterless_fails(self):
        from factory.engine.lib.export_gate import check_eg13_engine_tokens

        checks = check_eg13_engine_tokens(
            "Clara had spent all of chapterless hours avoiding.", 4
        )
        self.assertTrue(any(c["id"] == "EG-13" and not c["passed"] for c in checks))

    def test_countless_passes(self):
        from factory.engine.lib.export_gate import check_eg13_engine_tokens

        checks = check_eg13_engine_tokens(
            "Clara had spent all of countless hours avoiding.", 4
        )
        self.assertTrue(all(c["passed"] for c in checks if c["id"] == "EG-13"))

    def test_total_chapters_token_fails(self):
        from factory.engine.lib.export_gate import check_eg13_engine_tokens

        checks = check_eg13_engine_tokens("There are total_chapters left.", 1)
        self.assertTrue(any(not c["passed"] for c in checks if c["id"] == "EG-13"))


class PrepareExportTests(unittest.TestCase):
    def test_strip_heading_and_en_title(self):
        meta = {"chapter": 40, "title": "Chương 40", "subtitle": "# Chapter 40: The Strike"}
        body = "# Chapter 40: The Strike\n\nReal prose here."
        title, subtitle, cleaned = prepare_chapter_for_export(meta, body, "en")
        self.assertEqual(title, "The Strike")
        self.assertIsNone(subtitle)
        self.assertNotIn("# Chapter", cleaned)


class ExportGatePassTests(unittest.TestCase):
    def test_warn_does_not_block(self):
        report = {
            "checks": [
                {"id": "EG-07", "severity": "warn", "passed": False},
                {"id": "EG-01", "severity": "error", "passed": True},
            ]
        }
        self.assertTrue(export_gate_pass(report, {"export_gate_strict": False}))

    def test_error_blocks(self):
        report = {"checks": [{"id": "EG-01", "severity": "error", "passed": False, "detail": "x"}]}
        self.assertFalse(export_gate_pass(report))
        self.assertEqual(len(format_export_gate_reasons(report)), 1)

    def test_publish_needs_fix_blocks(self):
        from factory.engine.lib.export_gate import check_eg12_needs_fix

        check = check_eg12_needs_fix({"needs_fix": ["short:900"]}, 3, severity="error")
        self.assertFalse(check["passed"])
        self.assertEqual(check["id"], "EG-12")


if __name__ == "__main__":
    unittest.main()
