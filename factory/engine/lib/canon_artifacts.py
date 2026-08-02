"""Seal / stale / chapter artifact paths for the canon pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factory.engine.lib.canonical_ir import sha256_obj
from factory.engine.paths import book_workspace_dir


def chapter_artifact_dir(ws: Path, book: int, chapter: int) -> Path:
    return book_workspace_dir(ws, book) / "chapters" / f"{int(chapter):02d}"


def artifact_path(ws: Path, book: int, chapter: int, name: str) -> Path:
    return chapter_artifact_dir(ws, book, chapter) / name


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def make_seal(
    *,
    status: str,
    source_ir_hash: str,
    artifact_hash: str,
    validators: dict[str, str],
    unverified_claims: list[Any] | None = None,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "source_ir_hash": source_ir_hash,
        "artifact_hash": artifact_hash,
        "validators": validators,
        "unverified_claims": unverified_claims or [],
        "warnings": warnings or [],
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "validator_version": "1.0.0",
    }
    if extra:
        payload.update(extra)
    return payload


def is_sealed(approval: dict[str, Any] | None) -> bool:
    return bool(approval) and str(approval.get("status") or "") == "sealed"


def is_stale(approval: dict[str, Any] | None, current_ir_hash: str) -> bool:
    if not approval:
        return True
    if str(approval.get("status") or "") == "stale":
        return True
    return str(approval.get("source_ir_hash") or "") != str(current_ir_hash or "")


def mark_stale_descendants(ws: Path, book: int, *, reason: str) -> list[str]:
    """Mark sealed chapter approvals stale when IR changes."""
    root = book_workspace_dir(ws, book) / "chapters"
    touched: list[str] = []
    if not root.exists():
        return touched
    for ch_dir in sorted(root.iterdir()):
        if not ch_dir.is_dir():
            continue
        for name in ("plan.approval.json", "contract.json", "writer_request.json"):
            path = ch_dir / name
            data = read_json(path)
            if not data:
                continue
            data["status"] = "stale"
            data["stale_reason"] = reason
            write_json(path, data)
            touched.append(str(path))
    return touched
