"""Regression tests for chapter-scoped mystery reveal timing."""

from __future__ import annotations

import unittest

from factory.engine.lib.bible_schema import mystery_reveal_timing_issues
from factory.engine.lib.narrative_compiler import hidden_reveal_facts_at_chapter


FACT_CH7 = (
    "Grant manufactures instability using deleted camera intervals and timed "
    "concern messages during Lena's walks."
)
FACT_CH10 = (
    "Lena establishes explicit revocable alliance rules governing recording "
    "consent evidence preservation and staged reports."
)
FACT_CH14 = (
    "Lena reveals her complete controlled visibility design using planner receipts "
    "door seals honeytoken routines withheld behavior prediction and direction."
)
FACT_CH17 = (
    "The settlement trap forces Grant to authenticate false custody before footage "
    "audit notebook planner contract originals and timestamps contradict him."
)


def _ledger() -> dict:
    return {
        "canonical_reveal_chapter": 14,
        "truth": " ".join((FACT_CH7, FACT_CH10, FACT_CH14, FACT_CH17)),
        "major_reveals": [
            {"id": "MR07", "chapter": 7, "description": FACT_CH7},
            {"id": "MR10", "chapter": 10, "description": FACT_CH10},
            {"id": "MR14", "chapter": 14, "description": FACT_CH14},
            {"id": "MR17", "chapter": 17, "description": FACT_CH17},
        ],
    }


def _bible(answer: str | None = None, reveal_chapter: int = 14) -> dict:
    return {
        "central_mystery": {
            "question": "Who controls the record?",
            "answer": answer or _ledger()["truth"],
            "reveal_chapter": reveal_chapter,
        },
        "leads": {
            "female": {"name": "Lena Hart"},
            "male": {"name": "Calder Reed"},
        },
        "supporting_cast": [{"name": "Grant Hart"}],
    }


def _issues(chapter: int, prose: str, ledger: dict | None = None) -> list[str]:
    return mystery_reveal_timing_issues(
        {"chapter": chapter, "beat_summary": prose},
        _bible(),
        ledger=ledger,
    )


class RevealTimelineGateTests(unittest.TestCase):
    def test_fact_opened_ch7_does_not_flag_ch8(self) -> None:
        self.assertEqual(_issues(8, FACT_CH7, _ledger()), [])

    def test_fact_opened_in_current_chapter_does_not_flag(self) -> None:
        self.assertEqual(_issues(10, FACT_CH10, _ledger()), [])

    def test_ch14_mechanism_still_flags_ch10(self) -> None:
        issues = _issues(10, FACT_CH14, _ledger())
        self.assertTrue(any("mystery_reveal_too_early:MR14:before_ch14" in x for x in issues))

    def test_ch17_fact_still_flags_ch10(self) -> None:
        issues = _issues(10, FACT_CH17, _ledger())
        self.assertTrue(any("mystery_reveal_too_early:MR17:before_ch17" in x for x in issues))

    def test_shared_evidence_vocabulary_is_not_a_full_future_reveal(self) -> None:
        prose = (
            "The envelope clipped corner unique phrase checklist unedited lobby "
            "footage establish the honeytoken, without authenticating settlement custody."
        )
        self.assertEqual(_issues(10, prose, _ledger()), [])

    def test_legacy_single_reveal_keeps_answer_gate(self) -> None:
        answer = "The archivist forged every timestamp receipt ledger signature and camera record."
        ledger = {
            "canonical_reveal_chapter": 18,
            "major_reveals": [
                {"id": "MR18", "chapter": 18, "description": "The final truth."}
            ],
        }
        issues = mystery_reveal_timing_issues(
            {"chapter": 10, "beat_summary": answer},
            _bible(answer, reveal_chapter=18),
            ledger=ledger,
        )
        self.assertTrue(any("mystery_reveal_too_early:MR18:before_ch18" in x for x in issues))

    def test_intentional_early_reveal_does_not_disable_timeline(self) -> None:
        ledger = _ledger()
        ledger["intentional_early_reveal"] = True
        issues = _issues(10, FACT_CH14, ledger)
        self.assertTrue(any("mystery_reveal_too_early:MR14" in x for x in issues))

    def test_unmapped_answer_fragment_fails_loud_when_matched(self) -> None:
        ledger = _ledger()
        unmapped = (
            "Obsidian falcons encode violet calendars beneath copper staircases "
            "beside silent telescopes."
        )
        bible = _bible(f"{ledger['truth']} {unmapped}")
        issues = mystery_reveal_timing_issues(
            {"chapter": 10, "beat_summary": unmapped},
            bible,
            ledger=ledger,
        )
        self.assertTrue(any("mystery_answer_fragment_unmapped" in x for x in issues))

    def test_accessor_partitions_opened_and_hidden_facts(self) -> None:
        timeline = hidden_reveal_facts_at_chapter(
            _ledger(),
            10,
            fallback_answer=_ledger()["truth"],
            fallback_reveal_chapter=14,
        )
        self.assertEqual([x["id"] for x in timeline["opened"]], ["MR07", "MR10"])
        self.assertEqual([x["id"] for x in timeline["hidden"]], ["MR14", "MR17"])


if __name__ == "__main__":
    unittest.main()
