"""Canon pipeline P0–P2 fixtures — Zero-Day infection cases + schema coverage."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.canonical_ir import (
    build_ingest_report,
    compile_canonical_ir,
    ingest_concept_to_workspace,
    load_canonical_ir,
)
from factory.engine.lib.chapter_contract import (
    build_and_seal_chapter_artifacts,
    compile_chapter_contract,
    compile_writer_packet,
)
from factory.engine.lib.plan_provenance import (
    generalize_claim,
    seal_chapter_plan,
    validate_plan_against_ir,
)
from factory.engine.lib.prose_claim_gate import validate_prose_against_ir
from factory.engine.lib.prose_settlement import build_settlement

CE_CONCEPT = Path(
    r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml"
)


def _load_ce() -> dict:
    return yaml.safe_load(CE_CONCEPT.read_text(encoding="utf-8"))


@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestCanonicalIRIngest(unittest.TestCase):
    def test_coverage_classifies_all_top_level_paths(self) -> None:
        concept = _load_ce()
        report = build_ingest_report(concept)
        self.assertTrue(report["ok"], report.get("blocking_errors"))
        self.assertTrue(report["path_coverage"]["ok"])
        self.assertTrue(report["reference_resolution"]["ok"])
        covered = {row["source_path"] for row in report["path_coverage"]["coverage"]}
        for key in concept.keys():
            self.assertIn(key, covered)

    def test_unresolved_contract_text_ref_blocks(self) -> None:
        concept = _load_ce()
        poisoned = json.loads(json.dumps(concept, default=str))
        poisoned["chapter_map"]["2"]["must_happen"].append(
            "text_ref: /does/not/exist/anywhere"
        )
        report = build_ingest_report(poisoned)
        self.assertFalse(report["ok"])
        self.assertFalse(report["reference_resolution"]["ok"])
        self.assertTrue(report["path_coverage"]["ok"])
        self.assertTrue(any("does/not/exist" in e for e in report["blocking_errors"]))

    def test_fact_registry_includes_dead_blocks(self) -> None:
        concept = _load_ce()
        ir = compile_canonical_ir(concept)
        kinds = {f["kind"] for f in ir["facts"]}
        self.assertIn("clue", kinds)
        self.assertIn("reveal", kinds)
        self.assertIn("prop", kinds)
        self.assertIn("villain", kinds)
        self.assertIn("body", kinds)
        self.assertIn("psychology", kinds)
        self.assertIn("honeytoken", kinds)
        self.assertTrue(any(f["fact_id"] == "F_CLUE_C5" for f in ir["facts"]))
        self.assertTrue(
            any("anticoagulant" in f["claim"].casefold() for f in ir["facts"])
        )

    def test_workspace_ingest_writes_artifacts(self) -> None:
        concept = _load_ce()
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(concept, allow_unicode=True),
                encoding="utf-8",
            )
            result = ingest_concept_to_workspace(ws)
            self.assertTrue((ws / "bible" / "canonical_ir.json").exists())
            self.assertTrue((ws / "bible" / "ingest_report.json").exists())
            self.assertTrue((ws / "source" / "concept.yaml").exists())
            self.assertEqual(
                result["ir"]["source_sha256"],
                load_canonical_ir(ws)["source_sha256"],
            )


@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestPlanProvenanceGate(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = compile_canonical_ir(_load_ce())

    def test_edta_generalized(self) -> None:
        text, notes = generalize_claim(
            "Blood shows 0.47 micrograms/ml K2EDTA in a 7.5ml tube"
        )
        self.assertTrue(notes)
        self.assertNotIn("EDTA", text.upper().replace("ANTICOAGULANT TREATMENT", ""))
        self.assertIn("anticoagulant", text.casefold())

    def test_edta_in_plan_does_not_block_after_generalize(self) -> None:
        plan = {
            "chapter": 2,
            "must_happen": [
                "Mara notes chemical traces of an anticoagulant (e.g., EDTA) on the phone."
            ],
            "beat_summary": "She confirms EDTA.",
            "title": "Anticoagulant",
        }
        result = validate_plan_against_ir(plan, self.ir)
        repaired = " ".join(
            str(x) for x in (result["repaired_plan"].get("must_happen") or [])
        )
        self.assertNotIn("EDTA", repaired.upper().replace("ANTICOAGULANT", ""))
        # specificity alone should not leave blockers after generalize
        blockers = [
            u
            for u in result["unverified_claims"]
            if u.get("reason") == "unsourced_proper_noun"
            and "EDTA" in str(u.get("claim"))
        ]
        self.assertEqual(blockers, [])

    def test_holloway_proper_noun_blocks_seal(self) -> None:
        plan = {
            "chapter": 2,
            "must_happen": [
                "Mara recalls Dr. Patricia Holloway at Suite 401 after eleven months of therapy."
            ],
            "title": "Anticoagulant",
            "beat_summary": "Therapy notes.",
        }
        result = validate_plan_against_ir(plan, self.ir)
        self.assertEqual(result["status"], "blocked")
        reasons = {u["reason"] for u in result["unverified_claims"]}
        self.assertTrue(
            "unsourced_proper_noun" in reasons
            or any("Holloway" in str(u.get("claim")) for u in result["unverified_claims"])
        )

    def test_motive_swap_worthy_partner_blocks(self) -> None:
        plan = {
            "chapter": 11,
            "must_happen": [
                "Adrian reveals he orchestrated the entire confrontation to test whether Mara was a worthy partner."
            ],
            "beat_summary": "He had already decided to offer partnership as a test.",
            "title": "Two Victories",
            "cliffhanger": "She passed the worthy partner test.",
        }
        result = validate_plan_against_ir(plan, self.ir)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(
            any(
                u.get("reason") == "motive_swap_vs_true_plot"
                for u in result["unverified_claims"]
            )
        )

    def test_mutation_proper_noun_in_proposal_not_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(_load_ce(), allow_unicode=True),
                encoding="utf-8",
            )
            ingest_concept_to_workspace(ws)
            plan = {
                "chapter": 1,
                "title": "The Bloody Phone",
                "must_happen": ["Marcus Chen the driver arrives with coffee."],
                "beat_summary": "Marcus Chen waits outside.",
            }
            out = seal_chapter_plan(ws, 1, plan)
            self.assertFalse(out["sealed"])


@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestChapterContractPacket(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = compile_canonical_ir(_load_ce())

    def test_excluded_reveal_not_in_writer_packet(self) -> None:
        plan = {
            "chapter": 3,
            "title": "Synthetic Alibi",
            "must_happen": ["Mara creates the false alibi."],
        }
        # Seal-equivalent repaired plan
        result = validate_plan_against_ir(plan, self.ir)
        contract = compile_chapter_contract(
            self.ir, result["repaired_plan"], chapter=3
        )
        packet = compile_writer_packet(contract)
        # Future reveals must be physically absent — not listed as hidden ids/text.
        self.assertNotIn("excluded_facts", packet)
        self.assertGreater(int(packet.get("hidden_future_reveal_count") or 0), 0)
        blob = json.dumps(packet).casefold()
        self.assertNotIn('"r3"', blob)
        self.assertNotIn("secretly hired adrian to kill", blob)
        self.assertNotIn("f_reveal_r3", blob)

    def test_true_plot_not_dumped_to_packet(self) -> None:
        plan = {"chapter": 1, "title": "The Bloody Phone", "must_happen": []}
        contract = compile_chapter_contract(self.ir, plan, chapter=1)
        packet = compile_writer_packet(contract)
        blob = json.dumps(packet).casefold()
        self.assertNotIn("f_plot_true_plot", blob)


@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestProseClaimGate(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = compile_canonical_ir(_load_ce())

    def test_holloway_blocked_once(self) -> None:
        prose = (
            "I opened the file and saw Dr. Patricia Holloway's letter from Costa Rica."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(
                "Holloway" in str(v.get("claim"))
                for v in result["violations"]
            )
        )

    def test_edta_specificity_blocked(self) -> None:
        prose = "The assay returned 0.47 micrograms/ml of K2EDTA."
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "fail")

    def test_motive_swap_blocked_in_prose(self) -> None:
        prose = (
            "He orchestrated the entire confrontation to test whether I was a worthy partner."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=11)
        self.assertEqual(result["status"], "fail")

    def test_clean_anticoagulant_prose_passes(self) -> None:
        prose = (
            "I studied the blood on Adrian Thorne's phone and saw signs of anticoagulant treatment, "
            "not a fresh transfer from an uncontrolled wound."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "pass", result.get("violations"))

    def test_canon_name_in_dialogue_passes_with_span_type(self) -> None:
        prose = (
            'I kept my voice flat. "Adrian Thorne, put the phone on the desk." '
            "He did not smile."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "pass", result.get("violations"))
        pn = [
            c
            for c in result["claims"]
            if c.get("kind") == "proper_noun" and "Adrian" in str(c.get("claim"))
        ]
        self.assertTrue(pn)
        self.assertTrue(any(c.get("span_type") == "dialogue" for c in pn))

    def test_invented_name_in_dialogue_blocks(self) -> None:
        prose = (
            'I kept my voice flat. "Call Dr. Patricia Holloway immediately." '
            "The line stayed dead."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(c.get("span_type") == "dialogue" for c in result["violations"])
        )

    def test_future_fact_without_new_name_blocks(self) -> None:
        prose = (
            "I already knew the truth: I secretly hired him to kill Claire Thorne "
            "and planned the frame from the start."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(v.get("reason") == "reveal_chapter_timing" for v in result["violations"])
        )

    def test_generic_texture_passes_but_excluded_from_settlement(self) -> None:
        prose = (
            "The fluorescent light hummed above the desk while steam rose from the coffee."
        )
        result = validate_prose_against_ir(prose, self.ir, chapter=2)
        self.assertEqual(result["status"], "pass", result.get("violations"))
        self.assertGreater(len(result.get("texture_claims_excluded_from_state") or []), 0)
        settlement = build_settlement(chapter=2, canon_qc=result, prose_len=len(prose))
        self.assertEqual(settlement["status"], "sealed")
        self.assertGreater(int(settlement.get("texture_excluded_from_state") or 0), 0)
        self.assertFalse(
            any(
                c.get("kind") == "generic_texture"
                for c in settlement.get("facts_expressed") or []
            )
        )

@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestSettlementP0(unittest.TestCase):
    def test_settlement_requires_canon_pass(self) -> None:
        bad = build_settlement(chapter=2, canon_qc={"status": "fail"})
        self.assertEqual(bad["status"], "blocked")
        good = build_settlement(
            chapter=2,
            canon_qc={"status": "pass", "claims": []},
            prose_len=100,
        )
        self.assertEqual(good["status"], "sealed")
        self.assertIn("settlement_digest", good)

    def test_end_to_end_seal_and_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(_load_ce(), allow_unicode=True),
                encoding="utf-8",
            )
            ingest_concept_to_workspace(ws)
            plan = {
                "chapter": 2,
                "title": "Anticoagulant",
                "must_happen": [
                    "Mara observes anticoagulant treatment on the blood-stained phone."
                ],
                "beat_summary": "She scrapes Claire Thorne data and confirms anticoagulant staging.",
                "must_not": ["Mara leaves the office."],
            }
            sealed = seal_chapter_plan(ws, 1, plan)
            self.assertTrue(sealed["sealed"], sealed)
            built = build_and_seal_chapter_artifacts(
                ws,
                1,
                2,
                sealed["repaired_plan"],
            )
            self.assertIn("packet_digest", built["packet"])
            self.assertTrue(
                (ws / "books" / "01" / "chapters" / "02" / "writer_request.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
