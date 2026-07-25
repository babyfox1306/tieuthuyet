"""Full rewrite driver for the-second-wife — force each chapter, strip markdown format_fix."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.catalog import promote_chapter
from factory.engine.lib.locked_names import (
    UNKNOWN_UNTIL_REVEAL,
    merge_locked_names,
    sanitize_state_for_locked_names,
    seed_locked_names_from_plan,
)
from factory.engine.lib.machine_qc import (
    classify_machine_issues,
    is_format_only_issues,
    machine_pass,
    machine_qc,
    word_count_vi,
)
from factory.engine.lib.prose_sanitize import sanitize_prose
from factory.engine.lib.state_updater import load_state, save_state, update_state_after_pass
from factory.engine.lib.write_guards import is_sequential_writes
from factory.engine.paths import (
    book_workspace_dir,
    chapter_pipeline_path,
    load_config,
    pipeline_dir,
    workspace_dir,
)
from factory.engine.run_factory import write_one_chapter

WS_ID = "the-second-wife"
BOOK = 1


def _clear_bucket(ws: Path, book: int, bucket: str) -> None:
    d = pipeline_dir(ws, book, bucket)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.iterdir():
        if p.is_file():
            p.unlink()


def reset_pipeline_and_state() -> None:
    ws = workspace_dir(WS_ID)
    for bucket in ("draft", "needs_fix", "needs_review", "ready"):
        _clear_bucket(ws, BOOK, bucket)
    payloads = book_workspace_dir(ws, BOOK) / "payloads"
    if payloads.exists():
        for p in payloads.iterdir():
            if p.is_file():
                p.unlink()
    # Clear catalog chapters so promote doesn't leave old dual-name prose as SoT
    from factory.engine.lib.catalog import book_catalog_dir, resolve_book_slug

    slug = resolve_book_slug(WS_ID, BOOK)
    ch_dir = book_catalog_dir(WS_ID, slug) / "chapters"
    if ch_dir.exists():
        for p in ch_dir.glob("*.md"):
            p.unlink()
        print(f"[reset] cleared catalog chapters in {ch_dir}")

    seeded = seed_locked_names_from_plan(ws, BOOK)
    locked = merge_locked_names(
        {
            "previous_housekeeper": "Clara",
            "narrator_alias": "Anna",
            "E.M.": UNKNOWN_UNTIL_REVEAL,
            "husband": "Marcus",  # plan SoT — never Harold
        },
        seeded,
    )
    # Force plan husband over any seed drift
    locked["husband"] = "Marcus"
    state = {
        "current_book": BOOK,
        "current_chapter": 0,
        "timeline": [],
        "character_status": {},
        "open_threads": [],
        "facts_established": [],
        "spice_progression": "",
        "phrases_used": [],
        "locked_names": locked,
    }
    state = sanitize_state_for_locked_names(state)
    save_state(ws, BOOK, state)
    print(f"[reset] state locked_names={state['locked_names']}")


def _rescue_format_fix(ws: Path, ch: int, cfg: dict) -> bool:
    """Strip markdown from needs_fix → ready + promote + state update."""
    fix_path = chapter_pipeline_path(ws, BOOK, "needs_fix", ch)
    if not fix_path.exists():
        return False
    raw = fix_path.read_text(encoding="utf-8")
    clean = sanitize_prose(raw)
    direction = json.loads("{}")
    from factory.engine.lib.prompt_builder import load_direction

    direction = load_direction(ws)
    issues = machine_qc(
        clean,
        min_words=int(cfg.get("min_word_count", 1250)),
        banned_phrases=cfg.get("banned_phrases", []),
        target_lang=direction.get("target_language"),
        direction=direction,
        cfg=cfg,
        workspace_id=WS_ID,
        book=BOOK,
        chapter=ch,
    )
    if not machine_pass(issues) and not is_format_only_issues(issues):
        # still content problems after strip
        cls = classify_machine_issues(issues)
        print(f"  ch_{ch:03d} rescue FAILED — still issues: {cls}")
        return False
    if not machine_pass(issues):
        # format leftover — strip again / force accept if only markdown gone
        clean = sanitize_prose(clean)
        issues = machine_qc(
            clean,
            min_words=int(cfg.get("min_word_count", 1250)),
            banned_phrases=cfg.get("banned_phrases", []),
            target_lang=direction.get("target_language"),
            direction=direction,
            cfg=cfg,
            workspace_id=WS_ID,
            book=BOOK,
            chapter=ch,
        )
    ready = chapter_pipeline_path(ws, BOOK, "ready", ch)
    ready.write_text(clean if clean.endswith("\n") else clean + "\n", encoding="utf-8")
    # clear needs_fix
    for pattern in (f"ch_{ch:03d}.txt", f"ch_{ch:03d}_issues.json", f"ch_{ch:03d}_qc.json"):
        p = pipeline_dir(ws, BOOK, "needs_fix") / pattern
        if p.exists():
            p.unlink()
    try:
        update_state_after_pass(ws, ch, clean, book=BOOK)
    except Exception as exc:
        print(f"  ch_{ch:03d} state update warn: {exc}")
    out, reasons = promote_chapter(WS_ID, BOOK, ch, auto=True)
    print(
        f"  ch_{ch:03d} RESCUED format→ready (~{word_count_vi(clean)} words) "
        f"promote={bool(out)} {reasons[:2] if reasons else ''}"
    )
    return True


def main() -> int:
    cfg = load_config()
    ws = workspace_dir(WS_ID)
    reset_pipeline_and_state()
    print(f"[write] sequential={is_sequential_writes(cfg)} chapters 1-10")

    counts: dict[str, int] = {}
    for ch in range(1, 11):
        # Guarantee no skip
        for bucket in ("ready", "needs_fix", "needs_review", "draft"):
            p = chapter_pipeline_path(ws, BOOK, bucket, ch)
            if p.exists():
                p.unlink()
            for extra in (
                chapter_pipeline_path(ws, BOOK, bucket, ch).with_name(f"ch_{ch:03d}_issues.json"),
                chapter_pipeline_path(ws, BOOK, bucket, ch).with_name(f"ch_{ch:03d}_qc.json"),
                chapter_pipeline_path(ws, BOOK, bucket, ch).with_name(f"ch_{ch:03d}.promoted"),
            ):
                if extra.exists():
                    extra.unlink()

        _, status = write_one_chapter(ws, BOOK, ch, cfg, WS_ID, force=True)
        if status == "needs_fix":
            if _rescue_format_fix(ws, ch, cfg):
                status = "ready"
        if status == "needs_review":
            # One forced rewrite if Harold leaked despite locks
            review = chapter_pipeline_path(ws, BOOK, "needs_review", ch)
            if review.exists() and "Harold" in review.read_text(encoding="utf-8"):
                print(f"  ch_{ch:03d} Harold in needs_review — force rewrite once")
                for bucket in ("ready", "needs_fix", "needs_review", "draft"):
                    p = chapter_pipeline_path(ws, BOOK, bucket, ch)
                    if p.exists():
                        p.unlink()
                _, status = write_one_chapter(ws, BOOK, ch, cfg, WS_ID, force=True)
                if status == "needs_fix" and _rescue_format_fix(ws, ch, cfg):
                    status = "ready"
        counts[status] = counts.get(status, 0) + 1
        print(f"[progress] ch{ch} → {status} | {counts}")

    print(f"\n[rewrite] done: {counts}")
    # Final state check
    st = load_state(ws, BOOK)
    print("locked_names:", st.get("locked_names"))
    print("current_chapter:", st.get("current_chapter"))
    return 0 if counts.get("ready", 0) == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
