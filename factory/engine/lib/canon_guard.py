"""Tier 2 — Canon guard (registry-driven, blocks promote)."""

from __future__ import annotations

import json
from typing import Any

from factory.engine.lib.canon_prose_qc import (
    POV_FIRST_PERSON_THRESHOLD,
    count_first_person_outside_dialogue,
    find_name_drift_hits,
    find_spice_marker_hits,
    is_third_person_limited,
)
from factory.engine.lib.canon_registry import (
    CanonRegistry,
    build_canon_registry,
    canon_registry_path,
)
from factory.engine.paths import bible_path, workspace_dir


def _check(
    check_id: str,
    passed: bool,
    *,
    chapter: int | None = None,
    detail: str = "",
    snippet: str = "",
    severity: str = "error",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": check_id,
        "severity": severity,
        "passed": passed,
        "tier": 2,
    }
    if chapter is not None:
        row["chapter"] = chapter
    if detail:
        row["detail"] = detail
    if snippet:
        row["snippet"] = snippet[:240]
    return row


def load_canon_names(workspace_id: str) -> dict[str, Any]:
    """Character names + relations from bible/series.json (legacy helper)."""
    ws = workspace_dir(workspace_id)
    path = bible_path(ws)
    if not path.exists():
        return {"names": [], "mother_name": "Lin Mei", "father_name": "Marcus Thorne"}
    data = json.loads(path.read_text(encoding="utf-8"))
    names: list[str] = []
    leads = data.get("leads") or {}
    for side in ("female", "male"):
        n = (leads.get(side) or {}).get("name")
        if n:
            names.append(str(n))
    mother_name = "Lin Mei"
    father_name = "Marcus Thorne"
    for cast in data.get("supporting_cast") or []:
        nm = str(cast.get("name") or "")
        if nm:
            names.append(nm)
        rel = str(cast.get("relation_type") or "").lower()
        if "mother" in rel and cast.get("relation_to") == (leads.get("female") or {}).get("name"):
            mother_name = nm or mother_name
        if "father" in rel and "marcus" in nm.lower():
            father_name = nm
    return {
        "names": sorted(set(names)),
        "mother_name": mother_name,
        "father_name": father_name,
        "leads": leads,
        "supporting_cast": data.get("supporting_cast") or [],
    }


def _name_drift_checks(
    body: str, registry: CanonRegistry, chapter: int | None
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    hits = find_name_drift_hits(body, registry)
    if not hits:
        checks.append(_check("CG-01", True, chapter=chapter, detail="no forbidden lead names"))
        return checks
    for hit in hits:
        checks.append(
            _check(
                "CG-01",
                False,
                chapter=chapter,
                detail=f"name drift '{hit['found']}' — canon is {hit['canonical']}",
                snippet=hit["found"],
            )
        )
    return checks


def _pov_check(body: str, registry: CanonRegistry, chapter: int | None) -> dict[str, Any]:
    if not is_third_person_limited(registry):
        return _check("CG-02", True, chapter=chapter, detail="POV mode not third_person_limited")
    count = count_first_person_outside_dialogue(body)
    if count >= POV_FIRST_PERSON_THRESHOLD:
        return _check(
            "CG-02",
            False,
            chapter=chapter,
            detail=(
                f"first-person narration outside dialogue "
                f"({count} hits, threshold {POV_FIRST_PERSON_THRESHOLD})"
            ),
        )
    return _check("CG-02", True, chapter=chapter)


def _spice_checks(body: str, registry: CanonRegistry, chapter: int | None) -> list[dict[str, Any]]:
    if registry.spice_max > 1:
        return [_check("CG-03", True, chapter=chapter, detail="spice_max > 1 — spice check skipped")]
    markers = find_spice_marker_hits(body)
    if not markers:
        return [_check("CG-03", True, chapter=chapter, detail="no explicit spice markers")]
    return [
        _check(
            "CG-03",
            False,
            chapter=chapter,
            detail=f"explicit spice markers at spice_max={registry.spice_max}: {', '.join(markers)}",
            snippet=markers[0],
        )
    ]


def run_canon_guard(
    workspace_id: str,
    body: str,
    *,
    chapter: int | None = None,
    scope: str = "chapter",
    book: int = 1,
    registry: CanonRegistry | None = None,
) -> dict[str, Any]:
    """Run registry-driven canon checks on prose. Blocks promote when registry present."""
    ws = workspace_dir(workspace_id)
    if registry is None:
        if not canon_registry_path(ws).exists():
            return {
                "tier": 2,
                "scope": scope,
                "passed": True,
                "errors": 0,
                "checks": [],
                "skipped": True,
            }
        registry = build_canon_registry(ws, book)

    checks: list[dict[str, Any]] = []
    checks.extend(_name_drift_checks(body, registry, chapter))
    checks.append(_pov_check(body, registry, chapter))
    checks.extend(_spice_checks(body, registry, chapter))

    errors = sum(1 for c in checks if not c["passed"] and c["severity"] == "error")
    return {
        "tier": 2,
        "scope": scope,
        "passed": errors == 0,
        "errors": errors,
        "checks": checks,
        "skipped": False,
    }


def canon_guard_pass(report: dict[str, Any]) -> bool:
    if report.get("skipped"):
        return True
    return bool(report.get("passed"))


def format_canon_guard_reasons(report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for check in report.get("checks") or []:
        if check.get("passed"):
            continue
        ch = check.get("chapter")
        prefix = f"ch{ch:02d}" if ch else "book"
        reasons.append(f"{prefix} {check.get('id')}: {check.get('detail')}")
    return reasons
