"""Romance micro-beat in plan_qc is opt-in — keyword forbid is advisory only."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.plan_qc import (
    is_advisory_plan_issue,
    romance_forbidden,
    romance_microbeat_required,
    validate_all_plans,
    validate_plan,
)


def _minimal_plan(*, chapter: int = 6, with_romance: bool = False) -> dict:
    must = [
        "Marget maps the cold spots in her ledger.",
        "Arthur shortens the deadline without explanation.",
        "The raven stays on the fractured centre stone.",
    ]
    if with_romance:
        must.append("[ROMANCE] Their hands brush when he takes her ledger.")
    return {
        "chapter": chapter,
        "title": "The Ledger Frost",
        "slug": "the-ledger-frost",
        "one_line_summary": "Marget's numbness advances another millimetre.",
        "beat_summary": "She reads three stones; Arthur confiscates her ledger.",
        "must_happen": must,
        "must_not": ["Oswin speaks", "Arthur explains the mystery"],
        "opens_with": "Cold under the second finger pad on the slate.",
        "cliffhanger": "The next plot is already colder than her glove can refuse.",
        "signature_detail_hint": "Thumb-callus blood she can no longer feel.",
        "spice": 1,
        "chapter_task": "Write 1600-1900 words in third-limited Marget POV.",
    }


class RomanceOptInTests(unittest.TestCase):
    def test_forbidden_concept_skips_hard_block_on_keyword(self) -> None:
        """Keyword romance_forbidden may fire, but must not require romance either."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "must_avoid": ["Romance of any kind"],
                        "author_directive": "Spice: 1. No romance line at all.\n"
                        "Arthur is antagonist. NOT a love interest.",
                        "notes": "Gothic psychological horror, no romance.",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "canon_registry.yaml").write_text(
                yaml.dump(
                    {
                        "characters": {
                            "female_lead": {"canonical": "Marget Halloway"},
                            "male_lead": {"canonical": "Arthur Penhaligon"},
                        },
                        "pov_mode": "third_person_limited",
                        "spice_max": 1,
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            direction = {
                "narrative_profile": "gothic_psychological_horror",
                "spice_default": 1,
                "spice_level": 1,
                "spice_steamy_chapters": [],
                "spice_explicit_chapters": [],
            }
            self.assertTrue(romance_forbidden(direction, ws=ws))
            # No romance in profile → microbeat not required
            self.assertFalse(romance_microbeat_required(direction, ws=ws))

            issues = validate_plan(_minimal_plan(with_romance=False), direction, ws=ws)
            romance_issues = [i for i in issues if "romance" in i.lower()]
            self.assertEqual(
                romance_issues,
                [],
                f"horror/no-romance workspace must not require [ROMANCE]: {issues}",
            )

    def test_romance_opt_in_still_requires_microbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "must_avoid": ["Cross-cultural romance reduced to stereotype"],
                        "author_directive": "Write Book 1 as a 50-chapter romance-thriller.",
                        "notes": "Slow-burn romance with thriller stakes.",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "canon_registry.yaml").write_text(
                yaml.dump(
                    {
                        "characters": {
                            "female_lead": {"canonical": "Lin Wei"},
                            "male_lead": {"canonical": "Adrian Vale"},
                        },
                        "pov_mode": "third_person_limited",
                        "spice_max": 3,
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            direction = {
                "narrative_profile": "romance_thriller",
                "spice_default": 1,
                "spice_level": 1,
                "spice_steamy_chapters": [8],
                "spice_explicit_chapters": [3],
            }
            self.assertTrue(romance_microbeat_required(direction, ws=ws))

            missing = validate_plan(_minimal_plan(with_romance=False), direction, ws=ws)
            self.assertTrue(
                any("missing_romance_micro_beat" in i for i in missing),
                missing,
            )
            ok = validate_plan(_minimal_plan(with_romance=True), direction, ws=ws)
            self.assertFalse(
                any("missing_romance_micro_beat" in i for i in ok),
                ok,
            )

    def test_keyword_forbid_is_advisory_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {"must_avoid": ["Romance of any kind"], "notes": "no romance"},
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            direction = {
                "narrative_profile": "gothic_psychological_horror",
                "spice_default": 1,
                "spice_level": 1,
            }
            raw = validate_plan(_minimal_plan(with_romance=True), direction, ws=ws)
            adv = [i for i in raw if "forbidden_romance_when_concept_forbids" in i]
            self.assertTrue(adv, raw)
            self.assertTrue(all(is_advisory_plan_issue(i) for i in adv), adv)
            # approve-plan path uses validate_all_plans → advisory stripped
            blocked = validate_all_plans(
                [_minimal_plan(with_romance=True)], direction, ws=ws
            )
            self.assertEqual(blocked, {})

    def test_pedagogical_not_a_love_interest_does_not_block_romance_book(self) -> None:
        """Keyword may still match; advisory must not block approve-plan."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "must_avoid": ["Head-hopping"],
                        "author_directive": (
                            "If he only protects and asks permission, he is a "
                            "bodyguard, not a love interest.\n"
                            "Write as a romance-thriller."
                        ),
                        "notes": "dark romance",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            direction = {
                "narrative_profile": "international thriller-romance, dark romance",
                "spice_default": 1,
                "spice_level": 3,
            }
            self.assertTrue(romance_microbeat_required(direction, ws=ws))
            plan = _minimal_plan(with_romance=True)
            blocked = validate_all_plans([plan], direction, ws=ws)
            self.assertFalse(
                any(
                    "forbidden_romance" in i
                    for iss in blocked.values()
                    for i in iss
                ),
                blocked,
            )


if __name__ == "__main__":
    unittest.main()
