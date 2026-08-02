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
from factory.engine.lib.story_intelligence import (
    compile_chapter_intelligence,
    move_fact_ref_errors,
    project_character_cognition,
    project_honeytoken_state,
    project_prop_state,
    project_villain_knowledge,
    validate_move_fact_refs,
)
from factory.engine.lib.canon_ops import (
    cache_key_for_chapter,
    classify_error_layer,
    should_skip_literary_fixer,
)
from factory.engine.lib.prose_settlement import (
    build_settlement,
    continuity_from_prior,
    load_settlement,
    write_settlement,
)

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
class TestStoryIntelligenceP1(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = compile_canonical_ir(_load_ce())

    def test_villain_knowledge_phase(self) -> None:
        opening = project_villain_knowledge(self.ir, 2)
        self.assertEqual(opening["phase"], "opening")
        self.assertTrue(opening["actions"] or opening["knows"])
        final = project_villain_knowledge(self.ir, 12)
        self.assertEqual(final["phase"], "final")

    def test_prop_holder_by_chapter(self) -> None:
        props = {p["prop_id"]: p for p in project_prop_state(self.ir, 1)}
        self.assertEqual(props["P1"]["holder"], "Mara")
        self.assertIn("allowed_actions", props["P1"])
        props12 = {p["prop_id"]: p for p in project_prop_state(self.ir, 12)}
        self.assertEqual(props12["P1"]["holder"], "Adrian")

    def test_honeytoken_pre_vs_post_reuse(self) -> None:
        pre = project_honeytoken_state(self.ir, 3)
        self.assertEqual(pre["phase"], "pre_reuse")
        self.assertIn("hidden", pre)
        post = project_honeytoken_state(self.ir, 8)
        self.assertEqual(post["phase"], "at_or_after_reuse")
        self.assertIn("evidentiary_value", post.get("visible") or {})

    def test_character_cognition_fields(self) -> None:
        rows = project_character_cognition(self.ir, 2)
        self.assertTrue(rows)
        mara = next(r for r in rows if "Mara" in str(r.get("character") or ""))
        self.assertTrue(mara.get("goal_now"))
        self.assertTrue(mara.get("fear_active"))
        self.assertTrue(mara.get("coping_active"))
        self.assertTrue(mara.get("misbeliefs"))

    def test_moves_have_fact_refs(self) -> None:
        intel = compile_chapter_intelligence(self.ir, 2)
        moves = intel["moves"]
        self.assertTrue(moves["antagonist_move"].get("fact_refs"))
        self.assertTrue(moves["countermove"].get("fact_refs"))
        self.assertEqual(move_fact_ref_errors(moves), [])

    def test_missing_fact_refs_stop(self) -> None:
        bad = {
            "countermove": {
                "action": "Invented unsupported action with no IR source",
                "fact_refs": [],
                "ephemeral_safe": False,
            }
        }
        errs = move_fact_ref_errors(bad)
        self.assertTrue(errs)
        self.assertEqual(errs[0]["reason"], "move_missing_fact_refs")

    def test_compile_intelligence_bundle(self) -> None:
        intel = compile_chapter_intelligence(self.ir, 8)
        self.assertIn("moves", intel)
        self.assertIn("psychology_active", intel)
        self.assertIn("prop_state", intel)
        self.assertIn("character_cognition", intel)
        self.assertIn("character_state", intel)
        self.assertIn("relationship_delta_target", intel)


@unittest.skipUnless(CE_CONCEPT.exists(), "CE Zero-Day concept missing")
class TestSettlementAndOpsP1P2(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = compile_canonical_ir(_load_ce())

    def test_settlement_clamps_knows_before_pov_clock(self) -> None:
        """Case-C-at-settlement: observation of locked reveal must not mint early knows."""
        early = (
            "Adrian planted a backdoor in Mara's alibi software that leaks "
            "metadata to his server"
        )
        ok_obs = "The blood was treated with anticoagulants."
        # Simulate settlement seeing both: surface-legal obs + early reveal text
        # (over-inference). Prose may stay; knows must clamp.
        settle = build_settlement(
            chapter=2,
            canon_qc={
                "status": "pass",
                "claims": [
                    {"claim": ok_obs, "kind": "event"},
                    {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
                    {"claim": early, "kind": "event"},
                ],
            },
            intelligence={
                **compile_chapter_intelligence(self.ir, 2),
                "moves": {
                    **compile_chapter_intelligence(self.ir, 2)["moves"],
                    "antagonist_move": {
                        "action": early,
                        "fact_refs": ["F_REVEAL_R5"],
                    },
                    "countermove": {
                        "action": "Mara scrapes Claire Thorne's data.",
                        "required_events": ["Mara scrapes Claire Thorne's data."],
                        "fact_refs": ["F_MAP_CH2_must_happen_0"],
                    },
                },
            },
            ir=self.ir,
        )
        deltas = (settle.get("character_updates") or {}).get("deltas") or {}
        knows = deltas.get("knows_gained") or []
        clamped = deltas.get("knows_clamped") or []
        self.assertTrue(
            any("anticoagulant" in k.casefold() for k in knows),
            knows,
        )
        self.assertFalse(
            any("backdoor" in k.casefold() for k in knows),
            knows,
        )
        self.assertTrue(
            any(
                c.get("decision") == "clamped"
                and c.get("clock_used") == "pov_knows_chapter"
                and c.get("reason") == "pov_clock_not_reached"
                and "backdoor" in str(c.get("claim") or "").casefold()
                for c in clamped
            ),
            clamped,
        )
        # Defense in depth: poisoned settlement cannot smuggle into N+1.
        poisoned = dict(settle)
        poisoned["character_updates"] = {
            **(poisoned.get("character_updates") or {}),
            "deltas": {
                **deltas,
                "knows_gained": list(knows) + [early],
                "knows_clamped": [],
            },
        }
        intel3 = compile_chapter_intelligence(
            self.ir, 3, prior_settlement=poisoned
        )
        mara = next(
            r
            for r in (intel3.get("character_state") or [])
            if "Mara" in str(r.get("character") or "")
        )
        self.assertFalse(
            any("backdoor" in k.casefold() for k in (mara.get("knows") or [])),
            mara.get("knows"),
        )
        self.assertTrue(
            any("anticoagulant" in k.casefold() for k in (mara.get("knows") or [])),
            mara.get("knows"),
        )

    def test_settlement_allows_knows_at_pov_clock(self) -> None:
        """R4 unlocks at pov_knows_chapter=2 — anticoagulant may enter knows at ch2."""
        text = "The blood was treated with anticoagulants."
        settle = build_settlement(
            chapter=2,
            canon_qc={
                "status": "pass",
                "claims": [{"claim": text, "kind": "event"}],
            },
            intelligence=compile_chapter_intelligence(self.ir, 2),
            ir=self.ir,
        )
        deltas = (settle.get("character_updates") or {}).get("deltas") or {}
        self.assertTrue(
            any("anticoagulant" in k.casefold() for k in (deltas.get("knows_gained") or []))
        )
        self.assertFalse(
            any(
                "anticoagulant" in str(c.get("claim") or "").casefold()
                for c in (deltas.get("knows_clamped") or [])
            )
        )

    def test_settlement_requires_canon_pass(self) -> None:
        bad = build_settlement(chapter=2, canon_qc={"status": "fail"})
        self.assertEqual(bad["status"], "blocked")
        good = build_settlement(
            chapter=2,
            canon_qc={
                "status": "pass",
                "claims": [
                    {
                        "claim": "Mara scrapes Claire Thorne's data.",
                        "kind": "event",
                    },
                    {
                        "claim": "The blood was treated with anticoagulants.",
                        "kind": "event",
                    },
                ],
            },
            intelligence=compile_chapter_intelligence(self.ir, 2),
            prose_len=100,
            ir=self.ir,
        )
        self.assertEqual(good["status"], "sealed")
        self.assertIn("settlement_digest", good)
        self.assertTrue(good.get("events_realized"))
        self.assertIsNotNone((good.get("power_delta") or {}).get("realized"))
        deltas = (good.get("character_updates") or {}).get("deltas") or {}
        self.assertTrue(deltas.get("knows_gained"))
        self.assertTrue(good.get("strategy_updates"))

    def test_prose_changes_n1_memory_custody_strategy(self) -> None:
        """Acceptance: real ch-N claims change live N+1 state — Outliner foresight loses."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(_load_ce(), allow_unicode=True),
                encoding="utf-8",
            )
            ingest_concept_to_workspace(ws)
            ir = load_canonical_ir(ws)

            sealed2 = seal_chapter_plan(
                ws,
                1,
                {
                    "chapter": 2,
                    "title": "Anticoagulant",
                    "must_happen": [
                        "Mara observes anticoagulant treatment on the blood-stained phone."
                    ],
                    "beat_summary": (
                        "She scrapes Claire Thorne data and confirms anticoagulant staging."
                    ),
                    "must_not": ["Mara leaves the office."],
                },
            )
            self.assertTrue(sealed2["sealed"], sealed2)
            build_and_seal_chapter_artifacts(ws, 1, 2, sealed2["repaired_plan"])

            # Prose A: observes anticoagulant + scrapes data (no transfer).
            settle_a = build_settlement(
                chapter=2,
                canon_qc={
                    "status": "pass",
                    "claims": [
                        {
                            "claim": "The blood was treated with anticoagulants.",
                            "kind": "event",
                        },
                        {
                            "claim": "Mara scrapes Claire Thorne's data.",
                            "kind": "event",
                        },
                        {
                            "claim": "Mara retains custody of the Zero-Day Server.",
                            "kind": "event",
                        },
                    ],
                },
                intelligence=compile_chapter_intelligence(ir, 2),
                ir=ir,
            )
            write_settlement(ws, 1, 2, settle_a)
            self.assertIn(
                "The blood was treated with anticoagulants.",
                (settle_a["character_updates"]["deltas"]["knows_gained"]),
            )

            plan3 = {
                "chapter": 3,
                "title": "Next",
                "must_happen": ["Mara creates the false alibi."],
                "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
                "must_not": ["Mara leaves the office."],
                "carries_to_next": "Outliner invents a yacht chase Mara never saw",
            }
            sealed3 = seal_chapter_plan(ws, 1, plan3)
            self.assertTrue(sealed3["sealed"], sealed3)
            built_a = build_and_seal_chapter_artifacts(ws, 1, 3, sealed3["repaired_plan"])
            packet_a = built_a["packet"]
            mara_a = next(
                r
                for r in (packet_a.get("character_state") or [])
                if "Mara" in str(r.get("character") or "")
            )
            self.assertTrue(
                any("anticoagulant" in k.casefold() for k in (mara_a.get("knows") or [])),
                mara_a.get("knows"),
            )
            self.assertTrue(
                any("scrapes" in k.casefold() for k in (mara_a.get("knows") or [])),
                mara_a.get("knows"),
            )
            props_a = {p["prop_id"]: p for p in (packet_a.get("prop_state") or [])}
            self.assertEqual(props_a["P2"]["holder"], "Mara")
            self.assertTrue((packet_a.get("moves") or {}).get("prior_realized"))
            self.assertEqual(
                (packet_a.get("continuity") or {}).get("source"), "settlement"
            )
            self.assertTrue(
                (packet_a.get("continuity") or {}).get("plan_foresight_superseded")
            )
            # Foresight may be retained for audit, but must not be active continuity.
            self.assertIsNone((packet_a.get("continuity") or {}).get("carries_to_next"))
            self.assertNotEqual(
                (packet_a.get("continuity") or {}).get("source"), "plan_foresight"
            )

            # Prose B: different verified observation set → different N+1 memory.
            settle_b = build_settlement(
                chapter=2,
                canon_qc={
                    "status": "pass",
                    "claims": [
                        {
                            "claim": "Mara scrapes Claire Thorne's data.",
                            "kind": "event",
                        },
                        {
                            "claim": (
                                "Adrian Thorne takes the Blood-stained phone from the desk."
                            ),
                            "kind": "event",
                        },
                    ],
                },
                intelligence=compile_chapter_intelligence(ir, 2),
                ir=ir,
            )
            write_settlement(ws, 1, 2, settle_b)
            built_b = build_and_seal_chapter_artifacts(ws, 1, 3, sealed3["repaired_plan"])
            packet_b = built_b["packet"]
            mara_b = next(
                r
                for r in (packet_b.get("character_state") or [])
                if "Mara" in str(r.get("character") or "")
            )
            # Anticoagulant observation absent from prose B → not forced into knows
            # from settlement A (settlement replaced).
            self.assertFalse(
                any("anticoagulant" in k.casefold() for k in (mara_b.get("knows") or [])),
                mara_b.get("knows"),
            )
            self.assertTrue(
                any("scrapes" in k.casefold() for k in (mara_b.get("knows") or [])),
                mara_b.get("knows"),
            )
            props_b = {p["prop_id"]: p for p in (packet_b.get("prop_state") or [])}
            # Illegal early transfer: IR keeps P1 with Mara until ch12.
            self.assertTrue(
                "Mara" in str(props_b["P1"]["holder"]),
                props_b["P1"],
            )
            self.assertNotEqual(
                packet_a.get("packet_digest"), packet_b.get("packet_digest")
            )
            # Outliner foresight still does not become continuity authority.
            self.assertEqual(
                (packet_b.get("continuity") or {}).get("source"), "settlement"
            )

    def test_settlement_feeds_next_chapter_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "concept.yaml").write_text(
                yaml.safe_dump(_load_ce(), allow_unicode=True),
                encoding="utf-8",
            )
            ingest_concept_to_workspace(ws)
            ir = load_canonical_ir(ws)
            settle = build_settlement(
                chapter=2,
                canon_qc={
                    "status": "pass",
                    "claims": [
                        {
                            "claim": "Mara scrapes Claire Thorne's data.",
                            "kind": "event",
                        }
                    ],
                },
                intelligence=compile_chapter_intelligence(ir, 2),
                prose_len=50,
                ir=ir,
            )
            write_settlement(ws, 1, 2, settle)
            loaded = load_settlement(ws, 1, 2)
            self.assertEqual(loaded["settlement_digest"], settle["settlement_digest"])

            plan3 = {
                "chapter": 3,
                "title": "Next",
                "must_happen": ["Mara reviews the scraped Claire Thorne data."],
                "beat_summary": "Mara reviews Claire Thorne data already scraped.",
                "must_not": ["Mara leaves the office."],
                "carries_to_next": "Outliner foresight that should lose to settlement",
            }
            sealed2 = seal_chapter_plan(
                ws,
                1,
                {
                    "chapter": 2,
                    "title": "Anticoagulant",
                    "must_happen": [
                        "Mara observes anticoagulant treatment on the blood-stained phone."
                    ],
                    "beat_summary": "She scrapes Claire Thorne data and confirms anticoagulant staging.",
                    "must_not": ["Mara leaves the office."],
                },
            )
            self.assertTrue(sealed2["sealed"], sealed2)
            build_and_seal_chapter_artifacts(
                ws,
                1,
                2,
                sealed2["repaired_plan"],
                intelligence=compile_chapter_intelligence(ir, 2),
            )
            sealed3 = seal_chapter_plan(ws, 1, plan3)
            self.assertTrue(sealed3["sealed"], sealed3)
            built3 = build_and_seal_chapter_artifacts(
                ws,
                1,
                3,
                sealed3["repaired_plan"],
                # omit intelligence so compiler loads settlement N-1
            )
            packet = built3["packet"]
            prior = packet.get("prior_settlement") or {}
            self.assertEqual(prior.get("settlement_digest"), settle["settlement_digest"])
            continuity = packet.get("continuity") or {}
            self.assertEqual(continuity.get("source"), "settlement")
            self.assertTrue(continuity.get("plan_foresight_superseded"))
            # Mutate settlement → packet digest must change when rebuilt.
            settle2 = dict(settle)
            settle2["events_realized"] = list(settle.get("events_realized") or []) + [
                {"action": "extra realized beat", "kind": "test"}
            ]
            from factory.engine.lib.canonical_ir import sha256_obj

            settle2["settlement_digest"] = sha256_obj(
                {k: v for k, v in settle2.items() if k != "settlement_digest"}
            )
            write_settlement(ws, 1, 2, settle2)
            rebuilt = build_and_seal_chapter_artifacts(
                ws, 1, 3, sealed3["repaired_plan"]
            )
            self.assertNotEqual(
                (rebuilt["packet"].get("prior_settlement") or {}).get(
                    "settlement_digest"
                ),
                settle["settlement_digest"],
            )

    def test_continuity_settlement_overrides_foresight(self) -> None:
        prior = {
            "status": "sealed",
            "settlement_digest": "abc",
            "events_realized": [{"action": "Phone returned to Mara"}],
        }
        cont = continuity_from_prior(
            {"carries_to_next": "Outliner invents a yacht chase"},
            prior,
        )
        self.assertEqual(cont["source"], "settlement")
        self.assertTrue(cont["plan_foresight_superseded"])
        self.assertIsNone(cont["carries_to_next"])

    def test_cache_key_stable(self) -> None:
        a = cache_key_for_chapter("ir1", "p1", "c1")
        b = cache_key_for_chapter("ir1", "p1", "c1")
        c = cache_key_for_chapter("ir2", "p1", "c1")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_classify_error_layer(self) -> None:
        self.assertEqual(classify_error_layer("canonical_ir ingest blocked"), "importer_or_ce")
        self.assertEqual(classify_error_layer("plan_provenance_fail"), "planner")
        self.assertEqual(classify_error_layer("move_missing_fact_refs"), "planner")
        self.assertEqual(classify_error_layer("canon_qc fail"), "writer")
        self.assertTrue(should_skip_literary_fixer({"status": "fail", "violations": [1]}))

    def test_golden_ir_digest_stable(self) -> None:
        a = compile_canonical_ir(_load_ce())["ir_digest"]
        b = compile_canonical_ir(_load_ce())["ir_digest"]
        self.assertEqual(a, b)

    def test_packet_has_structured_intelligence(self) -> None:
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
                intelligence=compile_chapter_intelligence(load_canonical_ir(ws), 2),
            )
            packet = built["packet"]
            self.assertTrue(packet.get("character_state"))
            self.assertTrue(packet.get("moves", {}).get("countermove", {}).get("fact_refs"))
            self.assertTrue(packet.get("prop_state"))
            self.assertTrue(packet.get("psychology_active"))
            self.assertTrue(packet.get("relationship_delta_target"))
            # Writer must not see honeytoken hidden pre-reuse block.
            honey = packet.get("honeytoken_state") or {}
            self.assertNotIn("hidden", honey)

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
                intelligence=compile_chapter_intelligence(load_canonical_ir(ws), 2),
            )
            self.assertIn("packet_digest", built["packet"])
            self.assertTrue(
                (ws / "books" / "01" / "chapters" / "02" / "writer_request.json").exists()
            )


class P1CustodyBeliefStrategyTests(unittest.TestCase):
    """Runtime acceptance for the three remaining P1 layers."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ir = compile_canonical_ir(_load_ce())

    def test_custody_correct_holder_allowed(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_prop_holder_claim

        v = evaluate_prop_holder_claim(
            ir=self.ir,
            prop_id="P1",
            chapter=1,
            proposed_holder="Mara",
            action="Adrian gives phone to Mara",
            source="prose_custody_chain",
        )
        self.assertEqual(v["decision"], "allowed", v)

    def test_custody_wrong_holder_blocked(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_prop_holder_claim

        v = evaluate_prop_holder_claim(
            ir=self.ir,
            prop_id="P1",
            chapter=2,
            proposed_holder="Det. Miller",
            action="Det. Miller seizes the phone",
            source="prose_possession",
        )
        self.assertEqual(v["decision"], "clamped", v)
        self.assertEqual(v["reason"], "holder_not_on_schedule")

    def test_custody_disallowed_action_blocked(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_prop_holder_claim

        v = evaluate_prop_holder_claim(
            ir=self.ir,
            prop_id="P1",
            chapter=1,
            proposed_holder="Mara",
            action="Mara destroys the Blood-stained phone forever",
            source="prose_prop_action",
        )
        self.assertEqual(v["decision"], "clamped", v)
        self.assertEqual(v["reason"], "action_not_allowed")

    def test_custody_poisoned_settlement_reclamped(self) -> None:
        from factory.engine.lib.prose_settlement import apply_settlement_to_intelligence

        poison = {
            "status": "sealed",
            "chapter": 2,
            "settlement_digest": "poison-prop",
            "events_realized": [],
            "character_updates": {
                "deltas": {"character": "Mara Voss", "knows_gained": []}
            },
            "prop_updates": [
                {
                    "prop_id": "P1",
                    "name": "Blood-stained phone",
                    "holder": "Det. Miller",
                    "source": "prose_possession",
                    "evidence": "fake seizure",
                }
            ],
            "strategy_updates": {},
        }
        intel = apply_settlement_to_intelligence(
            compile_chapter_intelligence(self.ir, 3),
            poison,
            chapter=3,
            ir=self.ir,
        )
        p1 = next(p for p in intel["prop_state"] if p["prop_id"] == "P1")
        self.assertIn("Mara", str(p1.get("holder")))
        self.assertTrue(
            any(
                a.get("prop_id") == "P1" and a.get("decision") == "clamped"
                for a in (intel.get("prop_custody_audit") or [])
            ),
            intel.get("prop_custody_audit"),
        )

    def test_custody_verified_transfer_carries(self) -> None:
        settle = build_settlement(
            chapter=12,
            canon_qc={
                "status": "pass",
                "claims": [
                    {
                        "claim": "Mara returns phone with decryption key to Adrian.",
                        "kind": "event",
                    }
                ],
            },
            intelligence=compile_chapter_intelligence(self.ir, 12),
            ir=self.ir,
        )
        props = {p["prop_id"]: p for p in (settle.get("prop_updates") or [])}
        self.assertIn("Adrian", str(props["P1"].get("holder")))
        intel_next = compile_chapter_intelligence(
            self.ir, 12, prior_settlement={**settle, "status": "sealed"}
        )
        # Applying at ch12 (same schedule) keeps Adrian.
        p1 = next(p for p in intel_next["prop_state"] if p["prop_id"] == "P1")
        self.assertIn("Adrian", str(p1.get("holder")))

    def test_belief_with_observation_provenance_pass(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_belief_provenance

        kept, audit = evaluate_belief_provenance(
            [
                {
                    "text": "Professional suspicion sharpens.",
                    "provenance": "observation",
                    "ref": "may_observe",
                }
            ],
            self.ir,
            2,
        )
        self.assertIn("Professional suspicion sharpens.", kept)
        self.assertTrue(any(a.get("decision") == "allowed" for a in audit))

    def test_belief_missing_provenance_omitted(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_belief_provenance

        kept, audit = evaluate_belief_provenance(
            ["Orphan belief with no source at all."],
            self.ir,
            2,
            source="unit_test",
        )
        self.assertEqual(kept, [])
        self.assertTrue(
            any(a.get("decision") == "omitted" for a in audit),
            audit,
        )

    def test_hidden_truth_as_misbelief_blocked(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_belief_provenance

        r5 = next(r for r in self.ir["reveal_schedule"] if r.get("id") == "R5")
        kept, audit = evaluate_belief_provenance(
            [
                {
                    "text": r5["fact"],
                    "provenance": "psychology",
                }
            ],
            self.ir,
            2,
            target="character_state.misbeliefs",
        )
        self.assertNotIn(r5["fact"], kept)
        self.assertTrue(
            any(a.get("decision") == "clamped" for a in audit),
            audit,
        )

    def test_psychology_misbelief_allowed(self) -> None:
        from factory.engine.lib.prose_settlement import evaluate_belief_provenance

        text = "Believes Adrian is a tool while being used by him as a predator"
        kept, audit = evaluate_belief_provenance(
            [{"text": text, "provenance": "psychology"}],
            self.ir,
            2,
            target="character_state.misbeliefs",
        )
        self.assertIn(text, kept)

    def test_strategy_missing_ref_stop(self) -> None:
        errs = validate_move_fact_refs(
            {
                "countermove": {
                    "action": "Mara scrapes Claire Thorne's data.",
                    "fact_refs": [],
                }
            },
            ir=self.ir,
            chapter=2,
        )
        self.assertTrue(any(e["reason"] == "move_missing_fact_refs" for e in errs))

    def test_strategy_irrelevant_ref_stop(self) -> None:
        errs = validate_move_fact_refs(
            {
                "countermove": {
                    "action": "Mara scrapes Claire Thorne's data.",
                    "fact_refs": ["F_REVEAL_R8"],
                }
            },
            ir=self.ir,
            chapter=2,
        )
        reasons = {e["reason"] for e in errs}
        self.assertTrue(
            reasons & {"move_irrelevant_fact_refs", "move_future_fact_ref"},
            errs,
        )

    def test_strategy_wrong_actor_stop(self) -> None:
        errs = validate_move_fact_refs(
            {
                "countermove": {
                    "action": "Adrian Thorne scrapes Claire Thorne's data.",
                    "fact_refs": ["F_MAP_CH2_must_happen_0"],
                }
            },
            ir=self.ir,
            chapter=2,
        )
        self.assertTrue(
            any(e["reason"] == "move_wrong_actor" for e in errs),
            errs,
        )

    def test_strategy_future_ref_stop(self) -> None:
        errs = validate_move_fact_refs(
            {
                "countermove": {
                    "action": "Mara finds the backdoor in her alibi software.",
                    "fact_refs": ["F_REVEAL_R5"],
                }
            },
            ir=self.ir,
            chapter=2,
        )
        self.assertTrue(
            any(e["reason"] == "move_future_fact_ref" for e in errs),
            errs,
        )

    def test_strategy_wrong_prop_action_stop(self) -> None:
        errs = validate_move_fact_refs(
            {
                "countermove": {
                    "action": "Mara destroys the Blood-stained phone forever.",
                    "fact_refs": ["F_PROP_P1"],
                }
            },
            ir=self.ir,
            chapter=2,
        )
        self.assertTrue(
            any(
                e["reason"]
                in {"move_prop_action_not_allowed", "move_irrelevant_fact_refs"}
                for e in errs
            ),
            errs,
        )


class P2HarnessTests(unittest.TestCase):
    """P2 golden/budget/kill-point/lock smoke (no LLM)."""

    def test_romance_and_mystery_lite_compile(self) -> None:
        from factory.engine.lib.p2_fixtures import (
            MYSTERY_LITE_CONCEPT,
            ROMANCE_GATE_CONCEPT,
        )

        romance = compile_canonical_ir(ROMANCE_GATE_CONCEPT)
        mystery = compile_canonical_ir(MYSTERY_LITE_CONCEPT)
        self.assertTrue(romance.get("ir_digest"))
        self.assertTrue(mystery.get("ir_digest"))
        self.assertGreaterEqual(len(mystery.get("reveal_schedule") or []), 2)

    def test_call_budget_zero_on_canon_fail(self) -> None:
        from factory.engine.lib.canon_ops import should_skip_literary_fixer
        from factory.engine.lib.p2_harness import (
            assert_canon_fail_budget_zero,
            get_call_budget,
            reset_call_budget,
        )

        reset_call_budget()
        self.assertTrue(
            should_skip_literary_fixer(
                {"status": "fail", "violations": [{"reason": "x"}]}
            )
        )
        assert_canon_fail_budget_zero()
        self.assertEqual(get_call_budget()["literary_qc_calls"], 0)

    def test_killpoint_and_write_lock(self) -> None:
        from factory.engine.lib.p2_harness import (
            assert_no_incomplete_seal_promoted,
            begin_seal_journal,
            book_write_lock,
            complete_seal_journal,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            begin_seal_journal(ws, 1, 2, "plan")
            with self.assertRaises(RuntimeError):
                assert_no_incomplete_seal_promoted(ws, 1, 2)
            complete_seal_journal(ws, 1, 2)
            assert_no_incomplete_seal_promoted(ws, 1, 2)
            with book_write_lock(ws, 1):
                lock = ws / ".canon_write_locks" / "book_01.lock"
                self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
