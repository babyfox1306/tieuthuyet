"""Single-quoted dialogue normalize — apostrophes must not fake POV hits."""

from __future__ import annotations

import unittest

from factory.engine.lib.canon_prose_qc import (
    count_first_person_outside_dialogue,
    normalize_quotes,
    normalize_single_quoted_dialogue,
    strip_dialogue_for_pov,
)


class SingleQuotedDialogueTests(unittest.TestCase):
    def test_normalize_converts_dialogue_keeps_apostrophes(self) -> None:
        raw = (
            "Rook's voice fills the room: 'Bring me Sloane, and I'll let you live "
            "long enough to see Mara Mercer's hand.' As they drag him."
        )
        out = normalize_quotes(raw)
        self.assertIn('"Bring me Sloane', out)
        self.assertIn("Rook's", out)
        self.assertIn("I'll", out)
        self.assertIn("Mercer's", out)
        self.assertNotIn("'Bring me", out)

    def test_pov_count_ignores_ill_inside_single_quoted_dialogue(self) -> None:
        raw = (
            "Rook's voice fills the room: 'Bring me Sloane Mercer, and I'll let you "
            "live long enough to see Mara Mercer's hand make the broadcast yourself.' "
            "As his men drag Lucian toward the bay."
        )
        self.assertEqual(count_first_person_outside_dialogue(raw), 0)
        stripped = strip_dialogue_for_pov(raw)
        self.assertNotIn("I'll", stripped)
        self.assertIn("Rook's", stripped)  # possessive narration kept

    def test_true_narration_first_person_still_counts(self) -> None:
        raw = "I watched Rook's hand. He said, 'Stay.' I did not move."
        self.assertGreaterEqual(count_first_person_outside_dialogue(raw), 2)

    def test_noop_without_single_quotes(self) -> None:
        raw = 'She said, "I will stay." He nodded.'
        self.assertEqual(normalize_single_quoted_dialogue(raw), raw)


if __name__ == "__main__":
    unittest.main()
