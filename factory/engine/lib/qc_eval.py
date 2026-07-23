"""Deterministic QC verdict — do not trust LLM ``verdict`` alone."""

from __future__ import annotations

from typing import Any


def _flagged(obj: Any) -> bool:
    if isinstance(obj, dict):
        return bool(obj.get("flag"))
    return bool(obj)


def qc_fail_reasons(qc: dict[str, Any]) -> list[str]:
    """Hard-fail reasons from LLM QC JSON."""
    if not isinstance(qc, dict):
        return ["qc_not_object"]
    reasons: list[str] = []
    if qc.get("verdict") != "PASS":
        reasons.append("verdict_fail")
    if _flagged(qc.get("continuity_conflict")):
        reasons.append("continuity_conflict")
    if _flagged(qc.get("voice_drift")):
        reasons.append("voice_drift")
    if qc.get("pacing_issue"):
        reasons.append("pacing_issue")
    # Concept-driven content boundary checks (spice / must_avoid)
    if qc.get("spice_ok") is False:
        reasons.append("spice_exceeds_max")
    if qc.get("content_boundary_ok") is False:
        reasons.append("content_boundary_violation")
    return reasons


def _detail_of(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("details") or "").strip()
    return ""


def format_qc_reasons(qc: dict[str, Any]) -> list[str]:
    """Human-readable why a chapter landed in needs_review."""
    if not isinstance(qc, dict):
        return ["QC response không phải JSON object"]
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

    if qc.get("spice_ok") is False:
        add("nội dung vượt spice_max (spice_exceeds_max)")
    if qc.get("content_boundary_ok") is False:
        # look for detail in fail_reasons
        detail = ""
        for raw in qc.get("fail_reasons") or []:
            if "content_boundary" in str(raw).lower():
                detail = str(raw)
                break
        add("vi phạm ranh giới nội dung (content_boundary_violation)", detail)

    if not reasons and qc.get("verdict") != "PASS":
        add("QC FAIL", "verdict không PASS")
    return reasons


def qc_passes(qc: dict[str, Any]) -> bool:
    return not qc_fail_reasons(qc)


_BARE_FAIL_TAGS = frozenset(
    {
        "verdict_fail",
        "continuity_conflict",
        "voice_drift",
        "pacing_issue",
        "content_boundary_violation",
        "spice_exceeds_max",
        "qc_not_object",
        "qc_json_parse_error",
        "qc_transport_error",
        "qc_infra_skipped",
    }
)


def verbatim_llm_qc_feedback(qc: dict[str, Any]) -> list[str]:
    """Extract verbatim QC detail lines for writer retry — no paraphrase/summary.

    Prefer full English detail strings from the QC JSON. Skip bare tags
    (``verdict_fail``, ``continuity_conflict``, …) that carry no repair signal.
    """
    if not isinstance(qc, dict):
        return []
    lines: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        s = str(text or "").strip()
        if not s:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        lines.append(s)

    for key in ("continuity_conflict", "voice_drift"):
        obj = qc.get(key)
        if isinstance(obj, dict) and obj.get("flag"):
            detail = str(obj.get("details") or "").strip()
            if detail:
                add(detail)

    pacing = qc.get("pacing_issue")
    if pacing:
        if isinstance(pacing, dict):
            detail = str(pacing.get("details") or "").strip()
            if detail:
                add(detail)
        elif pacing is not True:
            add(str(pacing))

    for raw in qc.get("fail_reasons") or []:
        tag = str(raw).strip()
        if not tag:
            continue
        lower = tag.lower()
        if lower in _BARE_FAIL_TAGS:
            continue
        # "content_boundary_violation: <detail>" → keep full line (detail is the signal)
        if lower.startswith("content_boundary_violation:"):
            detail = tag.split(":", 1)[1].strip()
            add(detail if detail else tag)
            continue
        add(tag)

    return lines


def llm_qc_revision_suffix(qc: dict[str, Any], *, attempt: int) -> str:
    """Build writer retry_suffix from verbatim QC reasons."""
    lines = verbatim_llm_qc_feedback(qc)
    if not lines:
        lines = [
            "QC verdict FAIL with no detailed reasons — rewrite to satisfy the chapter "
            "plan, series bible binding conditions, content boundaries, and continuity "
            "with the immediate prior chapter. Do not invent early reveals or change "
            "locked facts."
        ]
    header = f"[REVISION — LLM QC attempt {attempt}] Fix ALL of the following QC failures:"
    body = "\n".join(f"- {line}" for line in lines)
    # Hard floor is machine_qc (min_word_count); QC rewrite must not shrink under it.
    length_rule = (
        "LENGTH HARD RULE: Keep the chapter at or above the configured minimum word "
        "count (machine_qc). Fix QC failures by rewriting scenes — do NOT shorten "
        "below the floor."
    )
    return f"\n\n{header}\n{body}\n- {length_rule}\n"
