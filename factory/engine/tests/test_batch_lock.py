"""Tests for stale batch lock detection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.ui import batch_state
from factory.ui import factory_workflow as wf


class BatchLockTests(unittest.TestCase):
    def test_clears_stale_running_without_active_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws_id = "test-ws"
            ws = Path(tmp) / ws_id
            ws.mkdir()
            prog = {
                "running": True,
                "phase": "write",
                "current_ch": 23,
                "log": ["▶ ch23 dang viet..."],
            }
            (ws / "batch_progress.json").write_text(
                json.dumps(prog), encoding="utf-8"
            )
            with patch.object(wf, "workspace_dir", return_value=ws):
                with patch.object(wf, "_batch_is_active", return_value=False):
                    out = wf.get_batch_progress(ws_id)
            self.assertFalse(out["running"])
            self.assertIn("batch bi ngat", out.get("error", ""))

    def test_keeps_running_when_thread_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws_id = "test-ws"
            ws = Path(tmp) / ws_id
            ws.mkdir()
            prog = {"running": True, "phase": "write", "current_ch": 5, "log": []}
            (ws / "batch_progress.json").write_text(
                json.dumps(prog), encoding="utf-8"
            )
            with patch.object(wf, "workspace_dir", return_value=ws):
                with patch.object(wf, "_batch_is_active", return_value=True):
                    out = wf.get_batch_progress(ws_id)
            self.assertTrue(out["running"])

    def test_batch_state_survives_workflow_reload(self):
        import importlib
        import threading
        import time

        ws_id = "reload-ws"
        done = threading.Event()

        def _hold():
            done.wait(timeout=5)

        t = threading.Thread(target=_hold, daemon=True)
        t.start()
        batch_state.register_thread(ws_id, t)
        importlib.reload(wf)
        self.assertTrue(batch_state.batch_is_active(ws_id))
        done.set()
        t.join(timeout=2)
        batch_state.unregister_thread(ws_id)


if __name__ == "__main__":
    unittest.main()
