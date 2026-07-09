"""Deterministic QC verdict — do not trust LLM ``verdict`` alone."""

from __future__ import annotations

from typing import Any


def _flagged(obj: Any) -> bool:
    if isinstance(obj, dict):
        return bool(obj.get("flag"))
    return bool(obj)


def qc_fail_reasons(qc: dict[str, Any]) -> list[str]:
    """Hard-fail reasons from LLM QC JSON."""
    reasons: list[str] = []
    if qc.get("verdict") != "PASS":
        reasons.append("verdict_fail")
    if _flagged(qc.get("continuity_conflict")):
        reasons.append("continuity_conflict")
    if _flagged(qc.get("voice_drift")):
        reasons.append("voice_drift")
    if qc.get("pacing_issue"):
        reasons.append("pacing_issue")
    return reasons


def _detail_of(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("details") or "").strip()
    return ""


def format_qc_reasons(qc: dict[str, Any]) -> list[str]:
    """Human-readable why a chapter landed in needs_review."""
    reasons: list[str] = []
    seen: set[str] = set()

    def add(label: str, detail: str = "") -> None:
        text = f"{label}: {detail}" if detail else label
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        reasons.append(text)

    cont = qc.get("continuity_conflict")
    if _flagged(cont):
        add("đứt mạch (continuity)", _detail_of(cont))
    voice = qc.get("voice_drift")
    if _flagged(voice):
        add("lệch giọng (voice)", _detail_of(voice))
    pacing = qc.get("pacing_issue")
    if pacing:
        detail = _detail_of(pacing) if isinstance(pacing, dict) else (str(pacing) if pacing is not True else "")
        add("nhịp chậm / pacing", detail)

    for raw in qc.get("fail_reasons") or []:
        tag = str(raw).strip()
        if not tag or tag in ("verdict_fail", "continuity_conflict", "voice_drift", "pacing_issue"):
            continue
        add(tag)

    if not reasons and qc.get("verdict") != "PASS":
        add("QC FAIL", "verdict không PASS")
    return reasons


def qc_passes(qc: dict[str, Any]) -> bool:
    return not qc_fail_reasons(qc)
