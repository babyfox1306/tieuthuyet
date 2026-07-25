"""Update state.json after chapter PASS."""

from __future__ import annotations

import json
import re
from pathlib import Path

from factory.engine.lib.call_9router import call_9router, parse_json_response
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import book_workspace_dir

_TIMELINE_CH_RE = re.compile(r"\bch(?:apter)?\s*[:\-]?\s*(\d+)", re.IGNORECASE)


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
        "locked_names": {},
    }


def save_state(ws: Path, book: int, state: dict) -> None:
    path = state_path(ws, book)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def last_timeline_chapter(state: dict) -> int:
    """Highest chapter number referenced in timeline entries (0 if none/unlabeled)."""
    highest = 0
    for entry in state.get("timeline") or []:
        m = _TIMELINE_CH_RE.search(str(entry))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def state_chapter_divergence(state: dict) -> dict:
    """Detect when state.current_chapter runs ahead of the recorded timeline.

    Divergence = current_chapter leads the last recorded timeline chapter by
    more than 1 (one ahead is normal for an in-flight chapter). A non-empty but
    unlabeled timeline (real state_updater output rarely prefixes "ChN:") is
    treated as aligned to avoid false positives; only an empty timeline reads
    as chapter 0.
    """
    current = int(state.get("current_chapter") or 0)
    timeline = state.get("timeline") or []
    labeled = last_timeline_chapter(state)
    if not timeline:
        timeline_chapter = 0
    elif labeled > 0:
        timeline_chapter = labeled
    else:
        timeline_chapter = current

    ahead_by = current - timeline_chapter
    divergent = ahead_by > 1
    message = ""
    if divergent:
        message = (
            f"state.current_chapter={current} leads timeline "
            f"(last recorded ch{timeline_chapter}) by {ahead_by} — "
            "state/timeline out of sync; reconcile before export"
        )
    return {
        "divergent": divergent,
        "current_chapter": current,
        "timeline_chapter": timeline_chapter,
        "ahead_by": ahead_by,
        "message": message,
    }


def _fallback_state_bump(state: dict, chapter_num: int, book: int) -> dict:
    """JSON state_updater fail — giữ state cũ, chỉ bump chapter."""
    bumped = dict(state)
    bumped["current_book"] = book
    bumped["current_chapter"] = chapter_num
    bumped.setdefault("timeline", [])
    bumped["timeline"].append(f"Ch{chapter_num} pass (state_updater JSON fail — cần review tay)")
    return bumped


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
    state = load_state(ws, book)
    direction = load_direction(ws)
    # State dài → excerpt ngắn hơn để model còn token cho JSON output
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
        err_path = book_workspace_dir(ws, book) / "pipeline" / "ready" / f"ch_{chapter_num:03d}_state_raw.txt"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(raw, encoding="utf-8")
        new_state = _fallback_state_bump(state, chapter_num, book)
    new_state.setdefault("current_book", book)
    new_state.setdefault("current_chapter", chapter_num)
    # Preserve prior locks if model dropped the field
    if "locked_names" not in new_state and isinstance(state.get("locked_names"), dict):
        new_state["locked_names"] = dict(state["locked_names"])

    from factory.engine.lib.canon_registry import (
        format_conflicts,
        validate_story_state_cast,
    )
    from factory.engine.lib.catalog import safe_print
    from factory.engine.lib.locked_names import apply_locked_names_after_pass

    cast_conflicts = validate_story_state_cast(ws, new_state, book)
    if cast_conflicts:
        # Drop invented doctors from timeline / relationships; keep chapter bump.
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
                        # Prefer declared attending if relationship mentioned a doctor.
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

    # Đòn 1+2: extract supporting names from prose; one name per role; block E.M. invent
    new_state = apply_locked_names_after_pass(new_state, chapter_text)

    save_state(ws, book, new_state)
    return new_state
