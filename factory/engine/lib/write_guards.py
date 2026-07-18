"""Write pipeline guards — parallel (plan-driven) or sequential state catch-up."""

from __future__ import annotations

import re
from pathlib import Path

from factory.engine.lib.state_updater import load_state, update_state_after_pass
from factory.engine.paths import chapter_pipeline_path, load_config


class WriteBlockedError(RuntimeError):
    """Raised when chapter N cannot be written safely (sequential mode only)."""


PRIOR_EXCERPT_MAX = 2500


def _state_current_chapter(state: dict) -> int:
    """Safe int from state — key may exist as null (JSON null)."""
    return int(state.get("current_chapter") or 0)


def is_sequential_writes(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return str(cfg.get("write_mode", "parallel")).lower() == "sequential"


def _strip_title(text: str) -> str:
    return re.sub(r"^#.*$", "", text, flags=re.M).strip()


def load_prior_chapter_excerpt(ws: Path, book: int, ch: int) -> str:
    """Last ~2500 chars of the previous READY chapter (canonical prose), if any."""
    if ch <= 1:
        return ""
    path = chapter_pipeline_path(ws, book, "ready", ch - 1)
    if not path.exists():
        return ""
    body = _strip_title(path.read_text(encoding="utf-8"))
    if not body:
        return ""
    if len(body) > PRIOR_EXCERPT_MAX:
        body = f"...[prior chapter truncated]\n{body[-PRIOR_EXCERPT_MAX:]}"
    from factory.engine.lib.canon_registry import (
        build_canon_registry,
        canon_registry_path,
        sanitize_text_for_registry,
    )

    if canon_registry_path(ws).exists():
        registry = build_canon_registry(ws, book)
        body = sanitize_text_for_registry(body, registry)
    return body


def highest_ready_chapter(ws: Path, book: int) -> int:
    hi = 0
    for ch in range(1, 200):
        if chapter_pipeline_path(ws, book, "ready", ch).exists():
            hi = ch
        elif ch > hi + 3:
            break
    return hi


def contiguous_ready_prefix(ws: Path, book: int, before_ch: int) -> int:
    """Highest chapter N < before_ch such that 1..N are all ready."""
    hi = 0
    for c in range(1, before_ch):
        if chapter_pipeline_path(ws, book, "ready", c).exists():
            hi = c
        else:
            break
    return hi


def state_chain_complete(ws: Path, book: int, ch: int) -> bool:
    """True when every chapter 1..ch-1 is ready (safe to advance story state to ch)."""
    if ch <= 1:
        return True
    for c in range(1, ch):
        if not chapter_pipeline_path(ws, book, "ready", c).exists():
            return False
    return True


def best_effort_catch_up_state(ws: Path, book: int, target_ch: int) -> int:
    """Replay state_updater for contiguous ready prefix — never block on gaps."""
    if target_ch <= 1:
        return _state_current_chapter(load_state(ws, book))
    hi = contiguous_ready_prefix(ws, book, target_ch)
    state = load_state(ws, book)
    cur = _state_current_chapter(state)
    if hi <= cur:
        return cur
    for c in range(cur + 1, hi + 1):
        path = chapter_pipeline_path(ws, book, "ready", c)
        text = path.read_text(encoding="utf-8")
        update_state_after_pass(ws, c, text, book=book)
        # Failed updater must not let later chapters advance the counter past a hole.
        if _state_current_chapter(load_state(ws, book)) < c:
            break
    return _state_current_chapter(load_state(ws, book))


def catch_up_state_before_write(ws: Path, book: int, target_ch: int) -> None:
    """Sequential: replay state until target_ch - 1; raise if gap in ready chain."""
    if target_ch <= 1:
        return
    needed = target_ch - 1
    state = load_state(ws, book)
    cur = _state_current_chapter(state)
    if cur >= needed:
        return
    for c in range(cur + 1, needed + 1):
        path = chapter_pipeline_path(ws, book, "ready", c)
        if not path.exists():
            raise WriteBlockedError(
                f"Cannot write ch{target_ch}: state at ch{cur} but ch{c} not in pipeline/ready. "
                f"Fix or approve ch{c} first."
            )
        text = path.read_text(encoding="utf-8")
        update_state_after_pass(ws, c, text, book=book)
        if _state_current_chapter(load_state(ws, book)) < c:
            raise WriteBlockedError(
                f"Cannot write ch{target_ch}: state_updater failed at ch{c} "
                f"(current_chapter still {_state_current_chapter(load_state(ws, book))}). "
                "Fix state update before continuing."
            )


def assert_write_allowed(ws: Path, book: int, ch: int, cfg: dict | None = None) -> None:
    """Parallel (default): plan-driven writes, no prior-chapter gate.

    Sequential: prior chapter must be READY and state caught up.
    """
    cfg = cfg or load_config()
    if not is_sequential_writes(cfg):
        best_effort_catch_up_state(ws, book, ch)
        return
    if ch <= 1:
        return
    prior_ready = chapter_pipeline_path(ws, book, "ready", ch - 1).exists()
    if not prior_ready:
        raise WriteBlockedError(
            f"Cannot write ch{ch}: ch{ch - 1} is not in pipeline/ready. "
            "Write chapters in order; failed chapters must be fixed before continuing."
        )
    catch_up_state_before_write(ws, book, ch)


def format_prior_excerpt_block(excerpt: str, *, lang: str = "en") -> str:
    if not excerpt:
        return ""
    heading = (
        "## PRIOR CHAPTER (canonical — do not contradict)"
        if lang == "en"
        else "## CHƯƠNG TRƯỚC (canonical — không được mâu thuẫn)"
    )
    return f"\n\n---\n{heading}\n```\n{excerpt}\n```\n"
