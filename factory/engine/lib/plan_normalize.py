"""Normalize chapter_plan objects — unwrap nested JSON, detect legacy VN content."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.paths import book_workspace_dir

LEGACY_VI_MARKERS = (
    "Diệp Tâm",
    "Hàn Thừa Uyên",
    "Lâm Vũ Trinh",
    "Lâm Tịch",
    "Từ Tố Nhi",
    "tập đoàn Hàn",
    "một tỷ đồng",
    "Lê Hồng Vân",
)

# English plan must not use Vietnamese chapter labels in title/task.
LEGACY_VI_TITLE_PATTERNS = (
    re.compile(r"chương\s*\d", re.I),
    re.compile(r"một tỷ", re.I),
)

_LIST_FIELDS = ("must_happen", "must_not")
_TEXT_FIELDS = (
    "title",
    "one_line_summary",
    "beat_summary",
    "chapter_task",
    "opens_with",
    "cliffhanger",
    "signature_detail_hint",
    "spice_note",
    "carries_to_next",
    "slug",
)


def coerce_text_list(val: Any) -> list[str]:
    """Flatten LLM lists — outliner sometimes nests sub-lists in must_happen."""
    if val is None:
        return []
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, list):
        out: list[str] = []
        for item in val:
            out.extend(coerce_text_list(item))
        return out
    if isinstance(val, dict):
        out: list[str] = []
        for item in val.values():
            out.extend(coerce_text_list(item))
        return out
    s = str(val).strip()
    return [s] if s else []


def coerce_text_field(val: Any) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, (list, dict)):
        return "; ".join(coerce_text_list(val))
    if val is None:
        return ""
    return str(val)


def _coerce_plan_fields(plan: dict[str, Any]) -> dict[str, Any]:
    for key in _LIST_FIELDS:
        if key in plan:
            plan[key] = coerce_text_list(plan.get(key))
    for key in _TEXT_FIELDS:
        if key in plan and not isinstance(plan.get(key), str):
            plan[key] = coerce_text_field(plan.get(key))
    return plan


def normalize_chapter_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Flatten outliner wrapper ``{chapter_plan: {...}, chapter: N}``."""
    if not plan:
        return {"chapter": 0}
    out = dict(plan)
    nested = out.get("chapter_plan")
    if isinstance(nested, dict):
        ch = out.get("chapter") or nested.get("chapter")
        merged = dict(nested)
        if ch is not None:
            merged["chapter"] = ch
        for key, val in out.items():
            if key == "chapter_plan":
                continue
            if key not in merged or merged.get(key) in (None, "", []):
                merged[key] = val
        out = merged
    out.pop("chapter_plan", None)
    if "spice" not in out and out.get("spice_note"):
        out["spice"] = 3
    return _coerce_plan_fields(out)


def normalize_chapter_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_chapter_plan(p) for p in plans if p]


def plan_text_blob(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False)


def plan_has_legacy_vi_content(plan: dict[str, Any]) -> bool:
    blob = plan_text_blob(plan)
    if any(m in blob for m in LEGACY_VI_MARKERS):
        return True
    if (plan.get("target_language") or "").lower() == "en":
        title = str(plan.get("title", ""))
        for pat in LEGACY_VI_TITLE_PATTERNS:
            if pat.search(title):
                return True
    return False


def validate_plan_language(plan: dict[str, Any], lang: str) -> list[str]:
    """EN workspaces must not ship Vietnamese legacy names in plans."""
    if lang != "en" or plan.get("locked"):
        return []
    ch = int(plan.get("chapter") or 0)
    if plan_has_legacy_vi_content(plan):
        return [f"ch{ch}:legacy_vi_content"]
    return []


def validate_duplicate_beats(plan: dict[str, Any], all_plans: list[dict[str, Any]]) -> list[str]:
    """Flag repeated one_line_summary / opens_with across chapters."""
    if plan.get("locked"):
        return []
    ch = int(plan.get("chapter") or 0)
    issues: list[str] = []
    ol = (plan.get("one_line_summary") or "").strip().lower()
    if ol:
        for p in all_plans:
            pch = int(p.get("chapter") or 0)
            if pch == ch:
                continue
            if (p.get("one_line_summary") or "").strip().lower() == ol:
                issues.append(f"ch{ch}:duplicate_one_line_summary:ch{pch}")
    opens = (plan.get("opens_with") or "").strip().lower()
    if len(opens) > 40:
        for p in all_plans:
            pch = int(p.get("chapter") or 0)
            if pch == ch:
                continue
            if (p.get("opens_with") or "").strip().lower() == opens:
                issues.append(f"ch{ch}:duplicate_opens_with:ch{pch}")
    return issues


def persist_normalized_master_plan(ws: Path, book: int) -> bool:
    """Load master_plan, normalize all chapter_plans, save if changed."""
    path = book_workspace_dir(ws, book) / "master_plan.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("chapter_plans", [])
    normalized = normalize_chapter_plans(raw)
    if normalized == raw:
        return False
    data["chapter_plans"] = normalized
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def locked_plans_look_vietnamese_legacy(plans: list[dict[str, Any]]) -> bool:
    return any(plan_has_legacy_vi_content(p) for p in plans)
