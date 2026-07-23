"""LLM QC closed loop: FAIL → verbatim feedback → rewrite (cap 2)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.qc_eval import (
    llm_qc_revision_suffix,
    verbatim_llm_qc_feedback,
)
from factory.engine.lib.writer_payload_log import write_writer_payload_artifact


def _long_chapter(n: int = 400) -> str:
    return "# Chapter 1: Test\n\n" + ("The corridor held. She moved. " * n)


class VerbatimFeedbackTests(unittest.TestCase):
    def test_prefers_details_skips_bare_tags(self) -> None:
        qc = {
            "verdict": "FAIL",
            "fail_reasons": [
                "verdict_fail",
                "continuity_conflict",
                "content_boundary_violation: Lucian reveals the sunrise clause before chapter 10.",
            ],
            "continuity_conflict": {
                "flag": True,
                "details": "Action restarted instead of continuing from the ledge.",
            },
        }
        lines = verbatim_llm_qc_feedback(qc)
        self.assertIn("Action restarted instead of continuing from the ledge.", lines)
        self.assertIn(
            "Lucian reveals the sunrise clause before chapter 10.",
            lines,
        )
        self.assertNotIn("verdict_fail", lines)
        self.assertNotIn("continuity_conflict", lines)

    def test_empty_reasons_get_fallback_suffix(self) -> None:
        suffix = llm_qc_revision_suffix({"verdict": "FAIL", "fail_reasons": ["verdict_fail"]}, attempt=1)
        self.assertIn("LLM QC attempt 1", suffix)
        self.assertIn("no detailed reasons", suffix)
        self.assertIn("LENGTH HARD RULE", suffix)
        self.assertIn("minimum word", suffix)


class LlmQcShortFloorTests(unittest.TestCase):
    def test_qc_rewrite_short_expands_five_then_machine_blocks(self) -> None:
        """After LLM QC rewrite, short drafts expand up to 5×; min_word_count never waived."""
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"writer": 0, "qc": 0}
        short = "# Chapter 1: Test\n\n" + ("She walked. " * 20)  # well under 100
        long = _long_chapter(400)
        writer_payloads: list[str] = []

        def fake_router(role, payload, **kwargs):
            calls[role] = calls.get(role, 0) + 1
            if role == "writer":
                writer_payloads.append(str(payload))
                # First write long (machine pass); QC rewrite + expands stay short
                if calls["writer"] == 1:
                    return long, {}
                return short, {}
            body = json.dumps(
                {
                    "verdict": "FAIL",
                    "fail_reasons": [
                        "content_boundary_violation: Early reveal of the architect."
                    ],
                    "content_boundary_ok": False,
                    "continuity_conflict": {"flag": False},
                    "voice_drift": {"flag": False},
                    "spice_ok": True,
                }
            )
            return body, {}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 5,
            # clamp in code forces length_max >= 1 → one full rewrite after expands
            "writer_length_max_retries": 1,
            "writer_content_max_retries": 2,
            "writer_llm_qc_max_retries": 2,
            "throttle_seconds": 0,
            "banned_phrases": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "books" / "01" / "pipeline" / "draft").mkdir(parents=True)
            (ws / "books" / "01" / "payloads").mkdir(parents=True)
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.build_qc_payload",
                        return_value="QC_PROMPT",
                    ):
                        with patch(
                            "factory.engine.run_factory.load_state",
                            return_value={"phrases_used": []},
                        ):
                            with patch(
                                "factory.engine.run_factory.load_role",
                                return_value="SYS",
                            ):
                                _chapter, issues, qc = _draft_chapter_prose(
                                    ws, 1, 1, cfg, {"target_language": "en"},
                                    run_llm_qc=True,
                                )
        # 1 initial + 1 QC rewrite + 5 expands + 1 length full rewrite
        self.assertEqual(calls["writer"], 8)
        self.assertEqual(issues.get("retry_meta", {}).get("short_expands"), 5)
        self.assertEqual(issues.get("retry_meta", {}).get("max_short_retries"), 5)
        self.assertIn("short", issues)
        self.assertLess(int(issues.get("word_count") or 0), 100)
        self.assertNotEqual((qc or {}).get("verdict"), "PASS")
        self.assertTrue(issues.get("llm_qc_before_machine_fail"))
        self.assertTrue(any("LENGTH HARD RULE" in p for p in writer_payloads[1:]))



class LlmQcRetryLoopTests(unittest.TestCase):
    def test_qc_fail_rewrites_with_verbatim_feedback_then_passes(self) -> None:
        from factory.engine.run_factory import _draft_chapter_prose

        calls: list[tuple[str, str]] = []

        def fake_router(role, payload, **kwargs):
            calls.append((role, str(payload)))
            if role == "writer":
                return _long_chapter(), {"model": "auto/fast"}
            # First QC fails with detail; second passes
            qc_calls = [c for c in calls if c[0] == "qc"]
            if len(qc_calls) <= 1:
                body = json.dumps(
                    {
                        "verdict": "FAIL",
                        "fail_reasons": [
                            "content_boundary_violation: Lucian reveals the sunrise clause "
                            "in chapter 1, before chapter 10."
                        ],
                        "content_boundary_ok": False,
                        "continuity_conflict": {"flag": False, "details": ""},
                        "voice_drift": {"flag": False, "details": ""},
                        "spice_ok": True,
                    }
                )
            else:
                body = json.dumps(
                    {
                        "verdict": "PASS",
                        "fail_reasons": [],
                        "content_boundary_ok": True,
                        "continuity_conflict": {"flag": False, "details": ""},
                        "voice_drift": {"flag": False, "details": ""},
                        "spice_ok": True,
                    }
                )
            return body, {"model": "auto/fast"}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 0,
            "writer_content_max_retries": 2,
            "writer_llm_qc_max_retries": 2,
            "throttle_seconds": 0,
            "banned_phrases": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "books" / "01" / "pipeline" / "draft").mkdir(parents=True)
            (ws / "books" / "01" / "payloads").mkdir(parents=True)
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.build_qc_payload",
                        return_value="QC_PROMPT",
                    ):
                        with patch(
                            "factory.engine.run_factory.load_state",
                            return_value={"phrases_used": []},
                        ):
                            with patch(
                                "factory.engine.run_factory.load_role",
                                return_value="SYS",
                            ):
                                chapter, issues, qc = _draft_chapter_prose(
                                    ws, 1, 1, cfg, {"target_language": "en"},
                                    run_llm_qc=True,
                                )
            self.assertTrue(qc and qc.get("verdict") == "PASS")
            self.assertEqual(issues.get("retry_meta", {}).get("llm_qc_rewrites"), 1)
            writer_payloads = [p for role, p in calls if role == "writer"]
            self.assertGreaterEqual(len(writer_payloads), 2)
            self.assertIn("sunrise clause", writer_payloads[1])
            self.assertIn("before chapter 10", writer_payloads[1])
            # Camera: attempt 2 should record llm_qc source
            cam = ws / "books" / "01" / "payloads" / "ch_001_attempt_2.json"
            self.assertTrue(cam.exists(), cam)
            data = json.loads(cam.read_text(encoding="utf-8"))
            self.assertEqual(data.get("retry_reason_source"), "llm_qc")
            self.assertIn("sunrise clause", data.get("retry_suffix", ""))
            self.assertIsInstance(data.get("qc_result_before_retry"), dict)

    def test_qc_fail_caps_at_two_rewrites(self) -> None:
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"writer": 0, "qc": 0}

        def fake_router(role, payload, **kwargs):
            calls[role] = calls.get(role, 0) + 1
            if role == "writer":
                return _long_chapter(), {}
            body = json.dumps(
                {
                    "verdict": "FAIL",
                    "fail_reasons": [
                        "content_boundary_violation: Past Sloane explains the mystery in a speech."
                    ],
                    "content_boundary_ok": False,
                    "continuity_conflict": {"flag": False},
                    "voice_drift": {"flag": False},
                    "spice_ok": True,
                }
            )
            return body, {}

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 0,
            "writer_content_max_retries": 2,
            "writer_llm_qc_max_retries": 2,
            "throttle_seconds": 0,
            "banned_phrases": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "books" / "01" / "pipeline" / "draft").mkdir(parents=True)
            (ws / "books" / "01" / "payloads").mkdir(parents=True)
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.build_qc_payload",
                        return_value="QC_PROMPT",
                    ):
                        with patch(
                            "factory.engine.run_factory.load_state",
                            return_value={"phrases_used": []},
                        ):
                            with patch(
                                "factory.engine.run_factory.load_role",
                                return_value="SYS",
                            ):
                                _ch, issues, qc = _draft_chapter_prose(
                                    ws, 1, 1, cfg, {"target_language": "en"},
                                    run_llm_qc=True,
                                )
        # 1 initial write + 2 QC rewrites = 3 writer; 3 QC (fail each time)
        self.assertEqual(calls["writer"], 3)
        self.assertEqual(calls["qc"], 3)
        self.assertEqual(issues.get("retry_meta", {}).get("llm_qc_rewrites"), 2)
        self.assertEqual(qc.get("verdict"), "FAIL")


class CameraExtraFieldsTests(unittest.TestCase):
    def test_artifact_stores_qc_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            write_writer_payload_artifact(
                ws,
                1,
                3,
                attempt_number=2,
                system_message="SYS",
                user_payload="PROMPT",
                retry_suffix="[REVISION — LLM QC]",
                model_called="auto",
                source_versions={},
                output="text",
                retry_reason_source="llm_qc",
                qc_result_before_retry={"verdict": "FAIL", "fail_reasons": ["x"]},
            )
            path = ws / "books" / "01" / "payloads" / "ch_003_attempt_2.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["retry_reason_source"], "llm_qc")
            self.assertEqual(data["qc_result_before_retry"]["verdict"], "FAIL")


class LlmQcTransportInfraSkipTests(unittest.TestCase):
    def test_transport_error_skips_writer_rewrite(self) -> None:
        """TODO(revert) night-run safety: QC transport → qc_infra_skipped, keep prose."""
        from factory.engine.run_factory import _draft_chapter_prose

        calls = {"writer": 0, "qc": 0}
        first_prose = _long_chapter(420)

        def fake_router(role, payload, **kwargs):
            calls[role] = calls.get(role, 0) + 1
            if role == "writer":
                return first_prose, {"model": "auto/fast"}
            raise RuntimeError("All models failed: connection reset")

        cfg = {
            "min_word_count": 100,
            "writer_max_tokens": 1024,
            "writer_short_retries": 0,
            "writer_content_max_retries": 2,
            "writer_llm_qc_max_retries": 2,
            "throttle_seconds": 0,
            "banned_phrases": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "books" / "01" / "pipeline" / "draft").mkdir(parents=True)
            (ws / "books" / "01" / "payloads").mkdir(parents=True)
            with patch("factory.engine.run_factory.call_9router", side_effect=fake_router):
                with patch(
                    "factory.engine.run_factory.build_writer_payload",
                    return_value="PROMPT",
                ):
                    with patch(
                        "factory.engine.run_factory.build_qc_payload",
                        return_value="QC_PROMPT",
                    ):
                        with patch(
                            "factory.engine.run_factory.load_state",
                            return_value={"phrases_used": []},
                        ):
                            with patch(
                                "factory.engine.run_factory.load_role",
                                return_value="SYS",
                            ):
                                chapter, issues, qc = _draft_chapter_prose(
                                    ws, 1, 1, cfg, {"target_language": "en"},
                                    run_llm_qc=True,
                                )
            self.assertEqual(calls["writer"], 1)
            self.assertEqual(calls["qc"], 1)
            self.assertEqual(issues.get("retry_meta", {}).get("llm_qc_rewrites"), 0)
            self.assertEqual(qc.get("source"), "qc_infra_skipped")
            self.assertIn("qc_infra_skipped", qc.get("fail_reasons") or [])
            self.assertEqual(chapter.strip(), first_prose.strip())
            cam = ws / "books" / "01" / "payloads" / "ch_001_attempt_1.json"
            self.assertTrue(cam.exists(), cam)
            data = json.loads(cam.read_text(encoding="utf-8"))
            self.assertEqual((data.get("output") or "").strip(), first_prose.strip())


if __name__ == "__main__":
    unittest.main()
