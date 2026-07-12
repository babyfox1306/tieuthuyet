"""Human-readable reasons when a chapter is blocked (needs_fix / needs_review)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from factory.engine.lib.machine_qc import format_machine_reasons
from factory.engine.lib.qc_eval import format_qc_reasons
from factory.engine.paths import pipeline_dir


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def chapter_block_info(ws: Path, book: int, status: str, ch: int) -> dict[str, Any]:
    """Load why a chapter is in needs_fix / needs_review (empty for other statuses)."""
    if status == "needs_fix":
        issues = _load_json(pipeline_dir(ws, book, "needs_fix") / f"ch_{ch:03d}_issues.json")
        if not issues:
            return {
                "reasons": ["không có file issues — chạy lại write hoặc kiểm tra pipeline"],
                "reason_summary": "thiếu issues.json",
                "issues": None,
                "qc": None,
            }
        reasons = format_machine_reasons(issues)
        if not reasons:
            reasons = ["machine QC fail (không rõ chi tiết)"]
        return {
            "reasons": reasons,
            "reason_summary": "; ".join(reasons),
            "issues": issues,
            "qc": None,
        }

    if status == "needs_review":
        qc = _load_json(pipeline_dir(ws, book, "needs_review") / f"ch_{ch:03d}_qc.json")
        issues = _load_json(pipeline_dir(ws, book, "needs_review") / f"ch_{ch:03d}_issues.json")
        reasons: list[str] = []
        if qc:
            reasons.extend(format_qc_reasons(qc) or [])
            # Content-cap reports put human strings directly in fail_reasons
            if qc.get("source") == "machine_content_cap" and not reasons:
                for raw in qc.get("fail_reasons") or []:
                    if isinstance(raw, str) and raw.strip():
                        reasons.append(raw.strip())
        if issues and not reasons:
            reasons = format_machine_reasons(issues)
        if not qc and not issues:
            return {
                "reasons": ["không có file QC — chạy lại write hoặc kiểm tra pipeline"],
                "reason_summary": "thiếu qc.json",
                "issues": None,
                "qc": None,
            }
        if not reasons:
            reasons = ["QC FAIL (không rõ chi tiết)"]
        return {
            "reasons": reasons,
            "reason_summary": "; ".join(reasons),
            "issues": issues,
            "qc": qc,
        }

    return {"reasons": [], "reason_summary": "", "issues": None, "qc": None}


def format_status_with_reason(status: str, reason_summary: str = "") -> str:
    if status in ("needs_fix", "needs_review") and reason_summary:
        short = reason_summary if len(reason_summary) <= 160 else reason_summary[:157] + "…"
        return f"{status} — {short}"
    return status
