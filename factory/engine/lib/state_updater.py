"""Update state.json after chapter PASS.

current_chapter is narrative truth: it advances ONLY when state_updater
successfully writes a full state blob (timeline + facts). Never bump the
counter alone — a leading counter corrupts every later writer prompt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.lib.call_9router import call_9router, parse_json_response
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import book_workspace_dir

# Timeline lines like "Ch4: …", "Chapter 12 — …", "ch 3 pass"
_TIMELINE_CHAPTER_RE = re.compile(
    r"(?i)\b(?:ch(?:apter)?)\s*[:\-]?\s*(\d+)\b"
)


def state_path(ws: Path, book: int) -> Path:
    return book_workspace_dir(ws, book) / "state.json"


def load_state(ws: Path, book: int = 1) -> dict:
    path = state_path(ws, book)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {
        "current_book": book,
        "current_chapter": 0,
        "timeline": [],
        "character_status": {},
        "open_threads": [],
        "facts_established": [],
        "spice_progression": "",
        "phrases_used": [],
        "promoted_chapters": [],
    }


def save_state(ws: Path, book: int, state: dict) -> None:
    path = state_path(ws, book)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def last_timeline_chapter(state: dict) -> int:
    """Highest chapter number reflected in timeline entries (0 if none)."""
    hi = 0
    for entry in state.get("timeline") or []:
        for m in _TIMELINE_CHAPTER_RE.finditer(str(entry)):
            hi = max(hi, int(m.group(1)))
    return hi


def timeline_has_chapter_markers(state: dict) -> bool:
    return any(
        _TIMELINE_CHAPTER_RE.search(str(entry)) for entry in (state.get("timeline") or [])
    )


def ensure_timeline_chapter_marker(timeline: list[Any], chapter_num: int) -> list[str]:
    """Guarantee at least one Ch{n}: entry so divergence checks can read the counter."""
    out = [str(e).strip() for e in (timeline or []) if str(e).strip()]
    ch_pat = re.compile(rf"(?i)\b(?:ch(?:apter)?)\s*[:\-]?\s*{int(chapter_num)}\b")
    if any(ch_pat.search(s) for s in out):
        return out
    for i in range(len(out) - 1, -1, -1):
        if not _TIMELINE_CHAPTER_RE.search(out[i]):
            out[i] = f"Ch{int(chapter_num)}: {out[i]}"
            return out
    out.append(f"Ch{int(chapter_num)}: chapter {int(chapter_num)} recorded")
    return out


def state_chapter_divergence(state: dict) -> dict[str, Any]:
    """Detect when current_chapter lies ahead of timeline content.

    Divergent when current_chapter is more than 1 ahead of the last chapter
    reflected in timeline (silent leading counter → corrupt continuity).

    Timeline entries without ChN: markers are common (state_updater historically
    omitted them). Non-empty unlabeled timeline is NOT treated as ch0 — that was
    a systemic false positive. Empty timeline + counter > 1 still fails.
    """
    cur = int(state.get("current_chapter") or 0)
    timeline = list(state.get("timeline") or [])
    if timeline_has_chapter_markers(state):
        tl = last_timeline_chapter(state)
        divergent = cur > tl + 1
    elif not timeline:
        tl = 0
        divergent = cur > 1
    else:
        # Content present, no parseable chapter labels — cannot prove a lead.
        tl = cur
        divergent = False
    ahead = cur - tl
    return {
        "divergent": divergent,
        "current_chapter": cur,
        "timeline_chapter": tl,
        "ahead_by": ahead,
        "message": (
            f"state.json current_chapter={cur} but timeline only reaches ch{tl} "
            f"(ahead by {ahead}). Counter must not lead timeline — reconcile "
            f"state or re-run state_updater before export."
            if divergent
            else ""
        ),
    }


def record_promoted_chapter(ws: Path, book: int, chapter_num: int) -> dict:
    """Approve/promote progress — does NOT touch current_chapter."""
    state = load_state(ws, book)
    promoted = list(state.get("promoted_chapters") or [])
    if chapter_num not in promoted:
        promoted.append(int(chapter_num))
        promoted = sorted(set(int(x) for x in promoted))
        state["promoted_chapters"] = promoted
        state["current_book"] = book
        save_state(ws, book, state)
    return state


def _parse_state_response(raw: str, ws: Path, book: int, direction: dict) -> dict:
    try:
        return parse_json_response(raw)
    except json.JSONDecodeError:
        repair_raw, _ = call_9router(
            "state_updater",
            "Sửa thành JSON hợp lệ ONLY, không thêm text:\n" + raw[:14000],
            max_tokens=8192,
            direction=direction,
        )
        return parse_json_response(repair_raw)


def update_state_after_pass(
    ws: Path,
    chapter_num: int,
    chapter_text: str,
    book: int = 1,
) -> dict:
    """Full LLM state update. Advances current_chapter only on success.

    On parse/LLM failure: leave state.json unchanged (counter stays behind —
    honest). Never bump current_chapter without timeline/facts.
    """
    state = load_state(ws, book)
    direction = load_direction(ws)
    payload = json.dumps(
        {
            "current_state": state,
            "chapter_number": chapter_num,
            "book": book,
            "chapter_excerpt": chapter_text[:3500],
            "target_language": direction.get("target_language"),
        },
        ensure_ascii=False,
        indent=2,
    )
    raw, _ = call_9router("state_updater", payload, max_tokens=8192, direction=direction)
    try:
        new_state = _parse_state_response(raw, ws, book, direction)
        if not isinstance(new_state, dict):
            raise json.JSONDecodeError("state_updater returned non-object", str(raw)[:200], 0)
    except json.JSONDecodeError:
        err_path = (
            book_workspace_dir(ws, book)
            / "pipeline"
            / "ready"
            / f"ch_{chapter_num:03d}_state_raw.txt"
        )
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(raw if isinstance(raw, str) else str(raw), encoding="utf-8")
        from factory.engine.lib.catalog import safe_print

        safe_print(
            f"  state_updater FAIL ch{chapter_num:03d} — "
            f"current_chapter unchanged at {int(state.get('current_chapter') or 0)} "
            f"(raw -> {err_path.name})"
        )
        return state

    # Success: one writer sets counter together with the LLM-authored blob.
    new_state["current_book"] = book
    new_state["current_chapter"] = chapter_num
    # Preserve promote list if model drops it
    if "promoted_chapters" not in new_state and state.get("promoted_chapters"):
        new_state["promoted_chapters"] = list(state["promoted_chapters"])

    from factory.engine.lib.canon_registry import (
        format_conflicts,
        validate_story_state_cast,
    )
    from factory.engine.lib.catalog import safe_print

    cast_conflicts = validate_story_state_cast(ws, new_state, book)
    if cast_conflicts:
        safe_print(
            "  state_updater CANON — invented cast blocked:\n  "
            + "\n  ".join(format_conflicts(cast_conflicts))
        )
        allowed_blob = " ".join(c.get("value", "") for c in cast_conflicts)
        timeline = list(new_state.get("timeline") or [])
        new_state["timeline"] = [
            t
            for t in timeline
            if not any(
                str(c.get("value") or "") in str(t)
                for c in cast_conflicts
                if c.get("code", "").startswith("invented_doctor")
            )
        ]
        status = new_state.get("character_status")
        if isinstance(status, dict):
            cleaned: dict = {}
            for key, val in status.items():
                if any(
                    str(c.get("value") or "") == str(key)
                    for c in cast_conflicts
                    if c.get("code") == "invented_cast_in_story_state"
                ):
                    continue
                if isinstance(val, dict):
                    rel = str(val.get("relationship_other") or "")
                    if any(str(c.get("value") or "") in rel for c in cast_conflicts):
                        val = dict(val)
                        if "Dr." in rel or "doctor" in rel.lower():
                            val["relationship_other"] = (
                                "Reports to Dr. Ovid by phone only — not romantic"
                            )
                        else:
                            val["relationship_other"] = rel
                cleaned[key] = val
            new_state["character_status"] = cleaned
        new_state.setdefault("facts_established", [])
        if isinstance(new_state["facts_established"], list):
            new_state["facts_established"].append(
                "CANON: invented doctors stripped from state; "
                f"blocked={allowed_blob[:120]}"
            )

    new_state["timeline"] = ensure_timeline_chapter_marker(
        list(new_state.get("timeline") or []), chapter_num
    )
    save_state(ws, book, new_state)
    return new_state
