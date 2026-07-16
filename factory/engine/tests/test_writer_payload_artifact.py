"""Writer payload camera — file dump only, no build-logic changes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.engine.lib.writer_payload_log import write_writer_payload_artifact


class WriterPayloadArtifactTests(unittest.TestCase):
    def test_writes_success_and_failure_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "demo"
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)

            with mock.patch(
                "factory.engine.lib.writer_payload_log.book_workspace_dir",
                return_value=book_dir,
            ):
                write_writer_payload_artifact(
                    ws,
                    1,
                    3,
                    attempt_number=1,
                    system_message="SYS",
                    user_payload="USER BASE",
                    retry_suffix="\nRETRY",
                    model_called="auto/fast",
                    source_versions={"plan_hash": "abc"},
                    output="# Chapter 3\nok",
                    error=None,
                )
                write_writer_payload_artifact(
                    ws,
                    1,
                    3,
                    attempt_number=2,
                    system_message="SYS",
                    user_payload="USER BASE",
                    retry_suffix="",
                    model_called=None,
                    source_versions={"plan_hash": "abc"},
                    output=None,
                    error="All models failed",
                )

            ok = json.loads(
                (book_dir / "payloads" / "ch_003_attempt_1.json").read_text(encoding="utf-8")
            )
            bad = json.loads(
                (book_dir / "payloads" / "ch_003_attempt_2.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ok["chapter"], 3)
            self.assertEqual(ok["model_called"], "auto/fast")
            self.assertEqual(ok["output"], "# Chapter 3\nok")
            self.assertIsNone(ok["error"])
            self.assertIsNone(bad["output"])
            self.assertIn("All models failed", bad["error"])

    def test_write_failure_does_not_raise(self):
        ws = Path("/nonexistent/no/permission/ws")
        write_writer_payload_artifact(
            ws,
            1,
            1,
            attempt_number=1,
            system_message="s",
            user_payload="u",
            retry_suffix="",
            model_called=None,
            source_versions={},
            output=None,
            error="x",
        )


if __name__ == "__main__":
    unittest.main()
