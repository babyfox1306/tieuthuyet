"""Tests for Tier 2 canon guard (registry-driven)."""

from __future__ import annotations

import unittest

from factory.engine.lib.canon_guard import run_canon_guard
from factory.engine.lib.canon_registry import CanonRegistry, CharacterCanon


def _registry_with_forbidden() -> CanonRegistry:
    return CanonRegistry(
        workspace_id="guard-test",
        book=1,
        book_slug="01-guard-test",
        chapter_count=10,
        target_language="en",
        pov_mode="third_person_limited",
        spice_max=1,
        characters={
            "female_lead": CharacterCanon(
                role="female_lead",
                canonical="Lin Wei",
                forbidden_aliases=["Ms. Li", "Mrs. Li"],
            ),
            "male_lead": CharacterCanon(
                role="male_lead",
                canonical="Adrian Vale",
                forbidden_aliases=["Isabella Vale"],
            ),
        },
    )


class TestCanonGuard(unittest.TestCase):
    def test_cg01_catches_forbidden_mother_alias(self) -> None:
        reg = _registry_with_forbidden()
        body = "Ms. Li was resting in the ICU when Lin Wei arrived."
        report = run_canon_guard("guard-test", body, chapter=3, registry=reg)
        self.assertFalse(report["passed"])
        failed = [c for c in report["checks"] if not c["passed"]]
        self.assertTrue(any(c["id"] == "CG-01" for c in failed))

    def test_cg01_allows_canonical_names(self) -> None:
        reg = _registry_with_forbidden()
        body = "Lin Wei opened the file. Adrian Vale nodded."
        report = run_canon_guard("guard-test", body, chapter=3, registry=reg)
        self.assertTrue(report["passed"])

    def test_cg02_catches_first_person_pov(self) -> None:
        reg = _registry_with_forbidden()
        body = (
            "I stepped forward. My hand trembled. I could not look back. "
            "I knew what waited in the dark."
        )
        report = run_canon_guard("guard-test", body, chapter=7, registry=reg)
        self.assertFalse(report["passed"])
        failed_ids = [c["id"] for c in report["checks"] if not c["passed"]]
        self.assertIn("CG-02", failed_ids)

    def test_cg03_catches_spice_markers(self) -> None:
        reg = _registry_with_forbidden()
        body = "Elias Crane pulled her close, thrusting harder as she moaned."
        report = run_canon_guard("guard-test", body, chapter=3, registry=reg)
        self.assertFalse(report["passed"])
        failed_ids = [c["id"] for c in report["checks"] if not c["passed"]]
        self.assertIn("CG-03", failed_ids)


if __name__ == "__main__":
    unittest.main()
