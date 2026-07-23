"""Concept satisfiability, chapter canon compiler, digest stale."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.concept_canon import (
    artifact_stale_errors,
    compile_chapter_canon_rules,
    concept_digest,
    narrative_digest,
    stamp_plan_digests,
    write_narrative_meta,
)
from factory.engine.lib.concept_satisfiability import concept_satisfiability_errors


def _clean_pair() -> dict:
    return {
        "concept_status": "ready",
        "concept_schema_version": 2,
        "title": "Test",
        "logline": "An investigator finds a sunrise order on a contract.",
        "author_directive": "x" * 130,
        "surface_plot": "She investigates.",
        "true_plot": "He restores the obedient identity later.",
        "must_include": ["One night"],
        "must_avoid": ["Never use memory-recovery shorthands"],
        "forbidden_phrases": ["if I remember", "if you remember"],
        "surface_order": {
            "event_id": "sloane_termination_at_sunrise",
            "exact_text": "CLIENT TERMINATION AT SUNRISE",
            "visible_from_chapter": 1,
            "appears_unconditional": True,
        },
        "binding_condition": {
            "event_id": "sloane_termination_at_sunrise",
            "canonical_text": (
                "Lucian must kill Sloane at sunrise only if "
                "Rook restores the obedient identity."
            ),
            "reveal_chapter": 10,
            "exact_wording_required_when_explicitly_stated": True,
        },
    }


class TestConceptSatisfiability(unittest.TestCase):
    def test_clean_pair_passes(self) -> None:
        errs = concept_satisfiability_errors(_clean_pair())
        self.assertEqual(errs, [])

    def test_pair_incomplete(self) -> None:
        c = _clean_pair()
        del c["binding_condition"]
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_PAIR_INCOMPLETE", codes)

    def test_event_id_mismatch(self) -> None:
        c = _clean_pair()
        c["binding_condition"]["event_id"] = "other"
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_EVENT_ID_MISMATCH", codes)

    def test_ambiguous_touch_rule(self) -> None:
        c = _clean_pair()
        c["must_include"] = [
            "The binding condition is stated identically in every chapter that touches it"
        ]
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_AMBIGUOUS_TOUCH_RULE", codes)

    def test_forbidden_phrase_in_logline(self) -> None:
        c = _clean_pair()
        c["logline"] = "She signed kill me if I remember on the page."
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_FORBIDDEN_PHRASE_IN_LOGLINE", codes)

    def test_invalid_reveal_window(self) -> None:
        c = _clean_pair()
        c["binding_condition"]["reveal_chapter"] = 1
        c["surface_order"]["visible_from_chapter"] = 5
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_INVALID_REVEAL_WINDOW", codes)

    def test_must_avoid_mention_does_not_scan(self) -> None:
        """must_avoid may quote banned phrases as instructions — not scanned."""
        c = _clean_pair()
        c["must_avoid"] = ['Do not let her believe "if I remember" is the real condition.']
        self.assertEqual(concept_satisfiability_errors(c), [])

    def test_author_directive_may_list_forbidden_as_instructions(self) -> None:
        """author_directive may say NO Vance / NO Rook — bans live in forbidden_phrases."""
        c = _clean_pair()
        c["forbidden_phrases"] = ["Vance", "Rook", "brain chip"]
        c["author_directive"] = (
            "x" * 130
            + "\nFORBIDDEN: NO Vance, NO Rook, NO brain chip. See forbidden_phrases."
        )
        self.assertEqual(concept_satisfiability_errors(c), [])


class TestCompileChapterCanonRules(unittest.TestCase):
    def test_surface_only_before_reveal(self) -> None:
        c = _clean_pair()
        for ch in (1, 9):
            r = compile_chapter_canon_rules(c, ch)
            self.assertEqual(r.reveal_state, "surface_only")
            self.assertIn("CLIENT TERMINATION AT SUNRISE", r.allowed_exact_quotes)
            self.assertTrue(r.forbidden_facts)
            self.assertEqual(r.required_exact_wording, [])

    def test_binding_revealed_from_ten(self) -> None:
        c = _clean_pair()
        for ch in (10, 11):
            r = compile_chapter_canon_rules(c, ch)
            self.assertEqual(r.reveal_state, "binding_revealed")
            self.assertEqual(r.forbidden_facts, [])
            self.assertTrue(r.required_exact_wording)
            # ch11: required list present for explicit state only — not "every sunrise"
            self.assertIn("Rook restores the obedient identity", r.required_exact_wording[0])

    def test_forbidden_phrase_gates_staged(self) -> None:
        c = _clean_pair()
        c["forbidden_phrase_gates"] = [
            {
                "id": "early",
                "unlock_chapter": 18,
                "phrases": ["the inquiry is the cover-up"],
            },
            {
                "id": "mid",
                "unlock_chapter": 19,
                "phrases": ["Renn fast-tracked"],
            },
            {
                "id": "late",
                "unlock_chapter": 20,
                "phrases": ["Renn buried"],
            },
        ]
        # binding reveal is still 10 in clean pair — focus on gated phrases
        c["binding_condition"]["reveal_chapter"] = 20
        r17 = compile_chapter_canon_rules(c, 17)
        self.assertTrue(any("cover-up" in f for f in r17.forbidden_facts))
        self.assertTrue(any("fast-tracked" in f for f in r17.forbidden_facts))
        self.assertTrue(any("buried" in f for f in r17.forbidden_facts))
        r18 = compile_chapter_canon_rules(c, 18)
        self.assertFalse(any("cover-up" in f for f in r18.forbidden_facts))
        self.assertTrue(any("fast-tracked" in f for f in r18.forbidden_facts))
        r19 = compile_chapter_canon_rules(c, 19)
        self.assertFalse(any("fast-tracked" in f for f in r19.forbidden_facts))
        self.assertTrue(any("buried" in f for f in r19.forbidden_facts))
        r20 = compile_chapter_canon_rules(c, 20)
        self.assertEqual(r20.reveal_state, "binding_revealed")
        self.assertFalse(any("buried" in f for f in r20.forbidden_facts))

    def test_gate_invalid_unlock(self) -> None:
        c = _clean_pair()
        c["forbidden_phrase_gates"] = [{"unlock_chapter": 0, "phrases": ["x"]}]
        codes = {e.code for e in concept_satisfiability_errors(c)}
        self.assertIn("SAT_GATE_INVALID", codes)


class TestDigestStale(unittest.TestCase):
    def test_stale_when_pair_and_no_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "bible" / "narrative" / "kernel.json").write_text(
                '{"x":1}', encoding="utf-8"
            )
            (ws / "direction.yaml").write_text("book: 1\n", encoding="utf-8")
            (ws / "books" / "01").mkdir(parents=True)
            concept = _clean_pair()
            (ws / "concept.yaml").write_text(
                "concept_schema_version: 2\n", encoding="utf-8"
            )
            # use concept dict directly
            errs = artifact_stale_errors(ws, concept)
            codes = {e.code for e in errs}
            self.assertIn("STALE_NARRATIVE_VS_CONCEPT", codes)

    def test_fresh_after_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (nd / "kernel.json").write_text('{"a":1}', encoding="utf-8")
            (ws / "direction.yaml").write_text("book: 1\n", encoding="utf-8")
            books = ws / "books" / "01"
            books.mkdir(parents=True)
            concept = _clean_pair()
            import yaml

            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            dig = concept_digest(concept)
            write_narrative_meta(ws, source_concept_digest=dig)
            plan = {"chapter_plans": [{"chapter": 1}]}
            stamp_plan_digests(ws, plan)
            (books / "master_plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            errs = artifact_stale_errors(ws, concept)
            self.assertEqual(errs, [])

    def test_digest_stable(self) -> None:
        c = _clean_pair()
        self.assertEqual(concept_digest(c), concept_digest(c))
        c2 = dict(c)
        c2["notes"] = "changed notes should not matter"
        # notes not in DIGEST_FIELDS
        self.assertEqual(concept_digest(c), concept_digest(c2))


if __name__ == "__main__":
    unittest.main()
