"""Update story_state.json after chapter PASS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from story_factory.lib.call_9router import call_9router, parse_json_response


def load_state(series_dir: Path) -> dict:
    path = series_dir / "story_state.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "current_book": 1,
        "current_chapter": 0,
        "timeline": [],
        "character_status": {},
        "open_threads": [],
        "facts_established": [],
        "spice_progression": "",
        "phrases_used": [],
    }


def save_state(series_dir: Path, state: dict) -> None:
    path = series_dir / "story_state.json"
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def update_state_after_pass(
    series_dir: Path,
    chapter_num: int,
    chapter_text: str,
    book: int = 1,
) -> dict:
    state = load_state(series_dir)
    payload = json.dumps(
        {
            "current_state": state,
            "chapter_number": chapter_num,
            "book": book,
            "chapter_excerpt": chapter_text[:6000],
        },
        ensure_ascii=False,
        indent=2,
    )
    raw, _ = call_9router("state_updater", payload, max_tokens=4096)
    new_state = parse_json_response(raw)
    new_state.setdefault("current_book", book)
    new_state.setdefault("current_chapter", chapter_num)
    save_state(series_dir, new_state)
    return new_state
