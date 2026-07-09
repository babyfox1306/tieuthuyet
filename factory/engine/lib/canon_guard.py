"""Tier 2 — Canon guard (skeleton).

Roadmap: tune rules using real errors from Book 2 writing sessions.
Do not treat this module as complete — extend CG-* checks as new drift patterns appear.

Must-catch examples (Book 1 regressions):
  - CG-01: "Ms. Li" when mother's canon name is Lin Mei
  - CG-02: "Isabella Vale" labeled as Adrian's Father (gender swap; father is Marcus Thorne)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.paths import bible_path, workspace_dir

# --- Roadmap (implement incrementally) ---
CANON_GUARD_ROADMAP = """
CG-01  Name whitelist / forbidden aliases     [skeleton — Ms. Li]
CG-02  Relation + gender consistency          [skeleton — Isabella Vale father]
CG-03  POV / knowledge violations             [planned]
CG-04  Mystery reveal timing vs plan          [planned]
"""

# Mother aliases that must NOT appear (canon: Lin Mei)
_MOTHER_WRONG_NAMES = (
    re.compile(r"\bMs\.?\s*Li\b", re.IGNORECASE),
    re.compile(r"\bMrs\.?\s*Li\b", re.IGNORECASE),
    re.compile(r"\bMother\s+Li\b", re.IGNORECASE),
)

# Female name wrongly used for Adrian's father
_ISABELLA_FATHER = re.compile(
    r"Isabella\s+Vale\s*\([^)]*(?:father|dad|parent)[^)]*\)",
    re.IGNORECASE,
)
_ISABELLA_THORNE_FATHER = re.compile(
    r"Isabella\s+(?:Vale|Thorne)\s*\([^)]*Adrian['\u2019]?s\s+Father",
    re.IGNORECASE,
)


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
    """Character names + relations from bible/series.json."""
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


def check_cg01_mother_name(body: str, canon: dict[str, Any], chapter: int | None = None) -> dict[str, Any]:
    mother = canon.get("mother_name", "Lin Mei")
    for pat in _MOTHER_WRONG_NAMES:
        m = pat.search(body)
        if m:
            return _check(
                "CG-01",
                False,
                chapter=chapter,
                detail=f"wrong mother name '{m.group(0).strip()}' — canon is {mother}",
                snippet=m.group(0),
            )
    return _check("CG-01", True, chapter=chapter)


def check_cg02_gender_relation(body: str, chapter: int | None = None) -> dict[str, Any]:
    for pat in (_ISABELLA_FATHER, _ISABELLA_THORNE_FATHER):
        m = pat.search(body)
        if m:
            return _check(
                "CG-02",
                False,
                chapter=chapter,
                detail="Isabella Vale is female — Adrian's father is Marcus Thorne",
                snippet=m.group(0),
            )
    return _check("CG-02", True, chapter=chapter)


def run_canon_guard(
    workspace_id: str,
    body: str,
    *,
    chapter: int | None = None,
    scope: str = "chapter",
) -> dict[str, Any]:
    """Run skeleton canon checks on prose. scope: chapter | book (future)."""
    canon = load_canon_names(workspace_id)
    checks = [
        check_cg01_mother_name(body, canon, chapter),
        check_cg02_gender_relation(body, chapter),
    ]
    errors = sum(1 for c in checks if not c["passed"] and c["severity"] == "error")
    return {
        "tier": 2,
        "scope": scope,
        "passed": errors == 0,
        "errors": errors,
        "checks": checks,
        "roadmap": CANON_GUARD_ROADMAP.strip(),
    }


def canon_guard_pass(report: dict[str, Any]) -> bool:
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
