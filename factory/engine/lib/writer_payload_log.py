"""Camera only — dump exact writer payloads to disk. Never affects build/QC."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factory.engine.paths import bible_path, book_workspace_dir


def sha256_short(path: Path) -> str | None:
    """Stable short content hash for payload source_versions."""
    try:
        if not path.exists() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def writer_source_versions(ws: Path, book: int) -> dict[str, str | None]:
    from factory.engine.lib.canon_registry import canon_registry_path
    from factory.engine.lib.state_updater import state_path

    return {
        "plan_hash": sha256_short(book_workspace_dir(ws, book) / "master_plan.json"),
        "state_hash": sha256_short(state_path(ws, book)),
        "canon_hash": sha256_short(canon_registry_path(ws)),
        "bible_hash": sha256_short(bible_path(ws)),
        "direction_hash": sha256_short(ws / "direction.yaml"),
    }


def write_writer_payload_artifact(
    ws: Path,
    book: int,
    ch: int,
    *,
    attempt_number: int,
    system_message: str,
    user_payload: str,
    retry_suffix: str,
    model_called: str | None,
    source_versions: dict[str, str | None],
    output: str | None,
    error: str | None = None,
    retry_reason_source: str | None = None,
    qc_result_before_retry: dict[str, Any] | None = None,
) -> None:
    """Write payloads/ch_NNN_attempt_M.json. Never raises into the write path."""
    try:
        out_dir = book_workspace_dir(ws, book) / "payloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"ch_{ch:03d}_attempt_{attempt_number}.json"
        payload: dict[str, Any] = {
            "chapter": ch,
            "attempt_number": attempt_number,
            "system_message": system_message,
            "user_payload": user_payload,
            "retry_suffix": retry_suffix or "",
            "model_called": model_called,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_versions": source_versions,
            "output": output,
            "error": error,
        }
        if retry_reason_source:
            payload["retry_reason_source"] = retry_reason_source
        if qc_result_before_retry is not None:
            payload["qc_result_before_retry"] = qc_result_before_retry
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        try:
            from factory.engine.lib.catalog import safe_print

            safe_print(
                f"  [payload] WARN ch_{ch:03d} attempt {attempt_number} write failed: {exc}"
            )
        except Exception:
            pass
