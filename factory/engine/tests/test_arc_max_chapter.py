"""_arc_max_chapter must tolerate string act_structure labels."""

from __future__ import annotations

import unittest

from factory.engine.lib.operator_sync import _arc_max_chapter


class ArcMaxChapterTests(unittest.TestCase):
    def test_string_act_labels(self) -> None:
        # Meridian / Kessler style: phase labels, not chapter maps
        self.assertEqual(_arc_max_chapter({"act_structure": ["act1", "act2", "act3"]}), 0)

    def test_dict_acts_with_chapters(self) -> None:
        self.assertEqual(
            _arc_max_chapter(
                {"act_structure": [{"chapters": [1, 8]}, {"chapters": [9, 22]}]}
            ),
            22,
        )

    def test_mixed_string_and_dict(self) -> None:
        self.assertEqual(
            _arc_max_chapter({"act_structure": ["act1", {"chapters": [1, 5]}]}),
            5,
        )


if __name__ == "__main__":
    unittest.main()
