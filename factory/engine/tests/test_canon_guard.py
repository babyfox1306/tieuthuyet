"""Tests for Tier 2 canon guard skeleton."""

import unittest

from factory.engine.lib.canon_guard import (
    check_cg01_mother_name,
    check_cg02_gender_relation,
    load_canon_names,
    run_canon_guard,
)


class TestCanonGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.canon = {
            "mother_name": "Lin Mei",
            "father_name": "Marcus Thorne",
            "names": ["Lin Wei", "Adrian Vale", "Lin Mei", "Marcus Thorne"],
        }

    def test_cg01_catches_ms_li(self) -> None:
        body = "Ms. Li was resting in the ICU when Lin Wei arrived."
        check = check_cg01_mother_name(body, self.canon, chapter=3)
        self.assertFalse(check["passed"])
        self.assertEqual(check["id"], "CG-01")

    def test_cg01_allows_lin_mei(self) -> None:
        body = "Lin Mei opened her eyes slowly."
        check = check_cg01_mother_name(body, self.canon, chapter=3)
        self.assertTrue(check["passed"])

    def test_cg02_catches_isabella_father(self) -> None:
        body = "POV knowledge: Isabella Vale (Adrian's Father) signed the protocol."
        check = check_cg02_gender_relation(body, chapter=1)
        self.assertFalse(check["passed"])
        self.assertEqual(check["id"], "CG-02")

    def test_cg02_allows_marcus_thorne(self) -> None:
        body = "Marcus Thorne had orchestrated the Meridian for decades."
        check = check_cg02_gender_relation(body, chapter=10)
        self.assertTrue(check["passed"])

    def test_run_canon_guard_loads_bible(self) -> None:
        report = run_canon_guard(
            "glass-meridian",
            "Ms. Li needed oxygen. Isabella Vale (Adrian's Father) appeared in the file.",
            chapter=1,
        )
        self.assertFalse(report["passed"])
        failed = [c["id"] for c in report["checks"] if not c["passed"]]
        self.assertIn("CG-01", failed)
        self.assertIn("CG-02", failed)

    def test_load_canon_names_glass_meridian(self) -> None:
        canon = load_canon_names("glass-meridian")
        self.assertEqual(canon["mother_name"], "Lin Mei")
        self.assertIn("Lin Wei", canon["names"])


if __name__ == "__main__":
    unittest.main()
