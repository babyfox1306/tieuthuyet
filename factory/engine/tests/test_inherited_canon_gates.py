"""Tests for inherited_canon (EG-19) and reveal-order-by-role (EG-20)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.export_gate import (
    check_eg13_engine_tokens,
    check_eg19_inherited_canon,
    check_eg20_reveal_order_role,
)
from factory.engine.lib.inherited_canon import (
    InheritedCanonLock,
    InheritedFact,
    find_inherited_canon_violations,
    load_inherited_canon,
)
from factory.engine.lib.reveal_order_gate import find_early_tier4_identity_hits


class InheritedCanonTests(unittest.TestCase):
    def test_kessler_bridge_blocked(self):
        lock = InheritedCanonLock(
            prior_workspace="the-kessler-line",
            facts=[
                InheritedFact(
                    id="kessler_structure",
                    fact="tunnel",
                    forbid_patterns=[],
                )
            ],
        )
        hits = find_inherited_canon_violations(
            "the same method that collapsed the Kessler Bridge.", lock
        )
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "kessler_structure")

    def test_kessler_coupon_blocked_meridian_coupon_ok(self):
        lock = InheritedCanonLock(prior_workspace="the-kessler-line", facts=[])
        bad = find_inherited_canon_violations(
            "She compared it to the Kessler coupon micrograph.", lock
        )
        good = find_inherited_canon_violations(
            "The Meridian Spine certified coupon showed seven points.", lock
        )
        self.assertTrue(bad)
        self.assertFalse(good)

    def test_load_from_registry_file(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            data = {
                "characters": {
                    "female_lead": {"canonical": "A"},
                    "male_lead": {"canonical": "B"},
                },
                "prior_workspace": "the-kessler-line",
                "inherited_canon": [
                    {
                        "id": "kessler_structure",
                        "fact": "tunnel",
                        "forbid_patterns": [r"\bkessler\s+bridge\b"],
                    }
                ],
            }
            (ws / "canon_registry.yaml").write_text(
                yaml.dump(data), encoding="utf-8"
            )
            lock = load_inherited_canon(ws)
            self.assertEqual(lock.prior_workspace, "the-kessler-line")
            self.assertEqual(len(lock.facts), 1)


class RevealOrderRoleTests(unittest.TestCase):
    def test_named_adversary_before_reveal(self):
        prose = (
            "DIRECTOR OF POLICY: STELLAN MARSH.\n\n"
            "She watched them. The system had declared war, "
            "and she had just named her adversary."
        )
        hits = find_early_tier4_identity_hits(
            prose,
            antagonist_canonical="Stellan Marsh",
            antagonist_aliases=["Marsh", "Stellan"],
            reveal_chapter=20,
            chapter=12,
        )
        self.assertTrue(hits)
        cues = {h["role_cue"].lower() for h in hits}
        self.assertTrue(
            any("adversary" in c or "director of policy" in c for c in cues),
            cues,
        )

    def test_after_reveal_ok(self):
        prose = "Stellan Marsh was the adversary at the top."
        hits = find_early_tier4_identity_hits(
            prose,
            antagonist_canonical="Stellan Marsh",
            antagonist_aliases=["Marsh"],
            reveal_chapter=20,
            chapter=20,
        )
        self.assertFalse(hits)


class ExportGateNewRulesTests(unittest.TestCase):
    def test_eg13_blocks_c001_planted(self):
        checks = check_eg13_engine_tokens(
            '"C001 planted: a conflict in approval timestamps."', 2
        )
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)
        self.assertTrue(any("planted" in (c.get("detail") or "") for c in fails))

    def test_eg13_allows_advisory_panel_code(self):
        checks = check_eg13_engine_tokens(
            'She found a file marked "Advisory_Panel_C008."', 17
        )
        self.assertTrue(all(c["passed"] for c in checks))

    def test_eg13_blocks_book_1_literal(self):
        checks = check_eg13_engine_tokens(
            "She opens the redacted page file from Book 1 again.", 2
        )
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)

    def test_eg13_blocks_chapter_heading_in_body(self):
        checks = check_eg13_engine_tokens("Chapter 8: Transmission\n\nIris entered.", 20)
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)
        self.assertTrue(any("Chapter N:" in (c.get("detail") or "") for c in fails))

    def test_eg13_blocks_chapters_n_and_m(self):
        checks = check_eg13_engine_tokens(
            'Celia asked about "transaction records from Chapters 19 and 20."', 21
        )
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)

    def test_eg13_blocks_c011_holds_up(self):
        checks = check_eg13_engine_tokens('"We ran every test twice. C011 holds up."', 22)
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)

    def test_eg19_eg20_require_workspace(self):
        # Without workspace, checks pass (nothing to load)
        self.assertTrue(
            all(c["passed"] for c in check_eg19_inherited_canon("x", 1, workspace_id=None))
        )
        self.assertTrue(
            all(
                c["passed"]
                for c in check_eg20_reveal_order_role("x", 1, workspace_id=None)
            )
        )


class CharacterIdentityGateTests(unittest.TestCase):
    def setUp(self):
        from factory.engine.lib.character_identity_gate import (
            load_character_identity_for_workspace,
        )

        self.lock = load_character_identity_for_workspace("the-meridian-spine")
        self.assertFalse(self.lock.empty)

    def test_blocks_lund_male_pronoun(self):
        from factory.engine.lib.character_identity_gate import find_pronoun_violations

        prose = (
            "The audit captures Lund in his office, confirming the substitution. "
            "He verifies the tool-mark signature."
        )
        hits = find_pronoun_violations(prose, self.lock)
        self.assertTrue(any(h["canonical"] == "Petra Lund" for h in hits))

    def test_blocks_okafor_male_pronoun(self):
        from factory.engine.lib.character_identity_gate import find_pronoun_violations

        prose = "Okafor had surrendered, his statement in the audit logs damning him."
        hits = find_pronoun_violations(prose, self.lock)
        self.assertTrue(any(h["canonical"] == "Nadia Okafor" for h in hits))

    def test_allows_lund_female_pronoun(self):
        from factory.engine.lib.character_identity_gate import find_pronoun_violations

        prose = (
            "Lund signed the falsified coupons in her office. "
            "She verified the tool-mark was hers alone."
        )
        hits = find_pronoun_violations(prose, self.lock)
        self.assertFalse(any(h["canonical"] == "Petra Lund" for h in hits))

    def test_blocks_marsh_special_agent_role(self):
        from factory.engine.lib.character_identity_gate import find_role_flip_violations

        prose = "Special Agent Marsh took the podium and opened the briefing."
        hits = find_role_flip_violations(prose, self.lock)
        self.assertTrue(any(h["canonical"] == "Stellan Marsh" for h in hits))

    def test_allows_cross_gender_reference(self):
        from factory.engine.lib.character_identity_gate import find_pronoun_violations

        # Iris talking about Marsh's file — must NOT flag Iris↔his
        prose = "Iris Kane took his file from the desk and read the memo."
        hits = find_pronoun_violations(prose, self.lock)
        self.assertFalse(any(h["canonical"] == "Iris Kane" for h in hits))

    def test_skips_possessive_name_false_positive(self):
        from factory.engine.lib.character_identity_gate import find_pronoun_violations

        prose = (
            "Marsh's signature on a thousand memos, invisible until it became "
            "all she could see."
        )
        hits = find_pronoun_violations(prose, self.lock)
        self.assertFalse(any(h["canonical"] == "Stellan Marsh" for h in hits))

    def test_eg21_export_check_blocks(self):
        from factory.engine.lib.export_gate import check_eg21_character_identity

        checks = check_eg21_character_identity(
            "Lund in his office confirmed everything.",
            22,
            workspace_id="the-meridian-spine",
        )
        fails = [c for c in checks if not c["passed"]]
        self.assertTrue(fails)


if __name__ == "__main__":
    unittest.main()
