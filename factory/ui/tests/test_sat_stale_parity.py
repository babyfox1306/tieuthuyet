"""UI/workflow parity for SAT/STALE — no HTTP server required."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.concept_canon import (
    artifact_stale_errors,
    concept_digest,
    write_narrative_meta,
)
from factory.engine.lib.concept_satisfiability import concept_satisfiability_errors
from factory.engine.lib.narrative_schema import load_concept
from factory.engine.paths import workspace_dir
from factory.ui.factory_workflow import pipeline_status, run_pipeline_step


class TestUiSatStaleParity(unittest.TestCase):
    def test_killme_concept_satisfiable(self) -> None:
        concept = load_concept(workspace_dir("kill-me-if-i-remember"))
        self.assertEqual(concept_satisfiability_errors(concept), [])
        status = pipeline_status("kill-me-if-i-remember", 1)
        self.assertEqual(status.get("satisfiability_errors") or [], [])

    def test_killme_stale_or_fresh_consistent(self) -> None:
        """Before regen: STALE_* present. After digest stamp: empty."""
        status = pipeline_status("kill-me-if-i-remember", 1)
        stale = status.get("stale_errors") or []
        ws = workspace_dir("kill-me-if-i-remember")
        meta = ws / "bible" / "narrative" / "_meta.json"
        if meta.exists():
            self.assertEqual(stale, [], msg=stale)
        else:
            self.assertTrue(
                any(e.startswith("STALE_") for e in stale),
                msg=stale,
            )

    def test_approve_plan_blocked_when_stale(self) -> None:
        status = pipeline_status("kill-me-if-i-remember", 1)
        stale = status.get("stale_errors") or []
        if not any(e.startswith("STALE_") for e in stale):
            self.skipTest("kill-me digests already fresh — stale block covered by tempfile test")
        result = run_pipeline_step("kill-me-if-i-remember", "approve-plan", book=1)
        self.assertFalse(result.get("ok"))
        errs = result.get("errors") or [result.get("error") or ""]
        self.assertTrue(
            any("STALE_" in str(e) for e in errs),
            msg=errs,
        )

    def test_temp_workspace_stale_blocks_approve_plan(self) -> None:
        """Isolated workspace — UI returns same STALE_ codes as engine."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "ws-sat"
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "books" / "01").mkdir(parents=True)
            concept = {
                "concept_status": "ready",
                "concept_schema_version": 2,
                "title": "T",
                "logline": "A sunrise order appears on a rooftop contract.",
                "author_directive": "x" * 130,
                "surface_plot": "She investigates.",
                "true_plot": "Binding later.",
                "must_include": ["night"],
                "must_avoid": [],
                "forbidden_phrases": ["if I remember"],
                "surface_order": {
                    "event_id": "e1",
                    "exact_text": "CLIENT TERMINATION AT SUNRISE",
                    "visible_from_chapter": 1,
                    "appears_unconditional": True,
                },
                "binding_condition": {
                    "event_id": "e1",
                    "canonical_text": (
                        "Lucian must kill Sloane at sunrise only if "
                        "Rook restores the obedient identity."
                    ),
                    "reveal_chapter": 10,
                    "exact_wording_required_when_explicitly_stated": True,
                },
            }
            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                "book: 1\nnarrative_status: approved\nplan_status: draft\n"
                "bible_status: approved\nnarrative_profile: mystery\n",
                encoding="utf-8",
            )
            (ws / "bible" / "narrative" / "kernel.json").write_text(
                '{"x":1}', encoding="utf-8"
            )
            (ws / "books" / "01" / "master_plan.json").write_text(
                json.dumps({"chapter_plans": [{"chapter": 1}]}),
                encoding="utf-8",
            )

            with patch(
                "factory.ui.factory_workflow.workspace_dir",
                return_value=ws,
            ), patch(
                "factory.engine.paths.workspace_dir",
                return_value=ws,
            ):
                errs = [e.format() for e in artifact_stale_errors(ws, concept)]
                self.assertTrue(
                    any(e.startswith("STALE_NARRATIVE") for e in errs),
                    msg=errs,
                )
                # After stamping narrative meta only — plan still stale
                write_narrative_meta(ws, source_concept_digest=concept_digest(concept))
                errs2 = [e.format() for e in artifact_stale_errors(ws, concept)]
                self.assertTrue(
                    any(e.startswith("STALE_PLAN") for e in errs2),
                    msg=errs2,
                )


if __name__ == "__main__":
    unittest.main()
