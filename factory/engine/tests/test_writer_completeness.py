"""Writer completeness: finish_reason=length + EG-01 fallback."""

from __future__ import annotations

import unittest

from factory.engine.lib.writer_completeness import (
    continuation_suffix,
    extract_finish_reason,
    writer_output_incomplete,
)


class FinishReasonExtractTests(unittest.TestCase):
    def test_from_call_meta(self):
        self.assertEqual(extract_finish_reason({"finish_reason": "length"}), "length")
        self.assertEqual(extract_finish_reason({"finish_reason": "STOP"}), "stop")
        self.assertIsNone(extract_finish_reason({}))
        self.assertIsNone(extract_finish_reason(None))


class WriterIncompleteTests(unittest.TestCase):
    def test_finish_reason_length_always_incomplete(self):
        # Even a clean-looking ending — length means the model hit a wall.
        incomplete, code, detail = writer_output_incomplete(
            "She closed the door.",
            finish_reason="length",
            chapter=1,
        )
        self.assertTrue(incomplete)
        self.assertEqual(code, "truncated_by_length")
        self.assertIn("length", detail)

    def test_stop_with_clean_ending_ok(self):
        incomplete, code, _ = writer_output_incomplete(
            'She said, "Done."',
            finish_reason="stop",
            chapter=1,
        )
        self.assertFalse(incomplete)
        self.assertEqual(code, "")

    def test_no_finish_reason_falls_back_to_eg01_mid_sentence(self):
        incomplete, code, detail = writer_output_incomplete(
            "She looked at Lucian and\n\nShe",
            finish_reason=None,
            chapter=9,
        )
        self.assertTrue(incomplete)
        self.assertEqual(code, "truncated_eg01")
        self.assertIn("no finish_reason", detail)

    def test_no_finish_reason_unclosed_quote(self):
        incomplete, code, detail = writer_output_incomplete(
            'She yelled, "I want to know why my sister is lying dead on this roof!',
            finish_reason=None,
            chapter=1,
        )
        self.assertTrue(incomplete)
        self.assertEqual(code, "truncated_eg01")
        self.assertIn("unclosed", detail.lower())

    def test_continuation_suffix_mentions_code(self):
        s = continuation_suffix(
            code="truncated_by_length",
            detail="finish_reason=length",
            prior_tail="Last line of prose.",
            attempt=1,
        )
        self.assertIn("truncated_by_length", s)
        self.assertIn("Last line of prose.", s)
        self.assertIn("CONTINUATION", s)


if __name__ == "__main__":
    unittest.main()
