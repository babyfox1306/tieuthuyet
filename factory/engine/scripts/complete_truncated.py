"""Complete truncated chapter endings via focused LLM continuation, then install catalog."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.engine.lib.call_9router import call_9router  # noqa: E402
from factory.engine.lib.catalog import (  # noqa: E402
    chapter_beat_from_plan,
    chapter_filename,
    ensure_book_yaml,
    export_language,
    load_manifest,
    normalize_catalog_chapter,
    parse_chapter_header,
    slugify_vi,
    sync_series_yaml,
    text_to_catalog_md,
    write_catalog_chapter,
)
from factory.engine.lib.export_gate import check_eg01_truncated  # noqa: E402
from factory.engine.lib.prompt_builder import load_direction  # noqa: E402
from factory.engine.lib.prose_sanitize import sanitize_prose  # noqa: E402
from factory.engine.paths import catalog_archive_dir, load_config, workspace_dir  # noqa: E402

WORKSPACE = "glass-meridian"
BOOK = 1
BOOK_SLUG = "01-the-glass-meridian"
ARCHIVE = catalog_archive_dir(WORKSPACE, BOOK_SLUG) / "chapters"
PIPELINE = ROOT / "factory" / "workspaces" / "glass-meridian" / "books" / "01" / "pipeline"

# needs_fix drafts that already pass EG-01; archive for the rest
PLAN: dict[int, str] = {
    10: "needs_fix",
    11: "archive",
    33: "needs_fix",
    38: "archive",
    40: "archive",
    45: "archive",
}

COMPLETE_WITH_LLM = {11, 38, 40, 45}

SYSTEM = """You complete fiction chapters that were cut off mid-scene.
Output ONLY the continuation prose — no preamble, no markdown, no headers, no **bold**, no T001 markers.
Finish any open dialogue quotes. End on one strong complete sentence suitable as a chapter cliffhanger.
Match the existing voice and POV. English only."""


def load_archive_body(ch: int) -> str:
    for path in ARCHIVE.glob("*.md"):
        raw = path.read_text(encoding="utf-8")
        meta = yaml.safe_load(raw.split("---", 2)[1]) or {}
        if int(meta.get("chapter") or 0) == ch:
            return raw.split("---", 2)[2].strip()
    raise FileNotFoundError(f"archive chapter {ch}")


def load_needs_fix_body(ch: int) -> str:
    path = PIPELINE / "needs_fix" / f"ch_{ch:03d}.txt"
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    _n, _t, body = parse_chapter_header(text)
    return body.strip()


def strip_draft_artifacts(text: str) -> str:
    text = re.sub(r"\n---\s*$", "", text.rstrip())
    text = re.sub(
        r"\n+That's a very rough first pass\..*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"\n+Please confirm so I can deliver.*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return text.strip()


def complete_ending(ch: int, base: str, direction: dict, cfg: dict) -> str:
    beat = chapter_beat_from_plan(WORKSPACE, BOOK, ch) or {}
    title = beat.get("title", f"Chapter {ch}")
    cliff = beat.get("cliffhanger", "")
    tail = base[-1200:]
    prompt = (
        f"CHAPTER {ch}: {title}\n"
        f"TARGET CLIFFHANGER (aim for this beat): {cliff}\n\n"
        f"The chapter text below was CUT OFF. Continue seamlessly from the exact cut point.\n"
        f"Write 3-6 paragraphs (400-700 words).\n\n"
        f"--- CUT TEXT (end is incomplete) ---\n{tail}\n--- END CUT TEXT ---"
    )
    raw, _ = call_9router(
        "writer",
        prompt,
        direction=direction,
        system_override=SYSTEM,
        temperature=0.75,
        max_tokens=2500,
    )
    cont = strip_draft_artifacts(sanitize_prose(raw))
    # If model repeated tail, dedupe
    if cont[:80] in base[-200:]:
        cont = cont.split("\n\n", 1)[-1] if "\n\n" in cont else cont
    merged = base.rstrip() + "\n\n" + cont.strip()
    return strip_draft_artifacts(sanitize_prose(merged))


def install_chapter(ch: int, body: str, cfg: dict) -> None:
    beat = chapter_beat_from_plan(WORKSPACE, BOOK, ch) or {}
    title = str(beat.get("title") or f"Chapter {ch}")
    slug = str(beat.get("slug") or slugify_vi(title))
    spice = int(beat.get("spice") or 1)
    series_id = load_manifest(workspace_dir(WORKSPACE)).get("id", WORKSPACE)
    lang = export_language(WORKSPACE)

    md, meta = text_to_catalog_md(
        body,
        series_id=series_id,
        book=BOOK,
        chapter=ch,
        title=title,
        slug=slug,
        spice=spice,
        needs_fix=[],
        target_lang=lang,
    )
    body_only = md.split("---", 2)[-1].lstrip("\n")
    meta, body_only = normalize_catalog_chapter(
        meta, body_only, lang, workspace_id=WORKSPACE, book=BOOK
    )
    content = f"---\n{yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)}---\n\n{body_only}"
    sync_series_yaml(WORKSPACE)
    ensure_book_yaml(WORKSPACE, BOOK_SLUG)
    fname = chapter_filename(ch, slug)
    write_catalog_chapter(WORKSPACE, BOOK_SLUG, fname, content)
    eg = check_eg01_truncated(body_only, ch)
    print(f"  ch_{ch:03d} -> {fname} ({meta.get('word_count')} words) EG-01={eg['passed']}")


def main() -> int:
    cfg = load_config()
    direction = load_direction(workspace_dir(WORKSPACE))
    failed: list[int] = []

    for ch in sorted(PLAN):
        print(f"\n[complete] ch_{ch:03d}")
        src = PLAN[ch]
        base = load_needs_fix_body(ch) if src == "needs_fix" else load_archive_body(ch)
        base = strip_draft_artifacts(sanitize_prose(base))

        if ch in COMPLETE_WITH_LLM:
            print("  LLM continuation...")
            try:
                body = complete_ending(ch, base, direction, cfg)
            except Exception as exc:
                print(f"  ERROR LLM: {exc}")
                failed.append(ch)
                continue
            time.sleep(cfg.get("throttle_seconds", 4))
        else:
            body = base

        eg = check_eg01_truncated(body, ch)
        if not eg["passed"]:
            print(f"  WARN still truncated: {eg.get('detail')} — retrying LLM once")
            try:
                body = complete_ending(ch, body, direction, cfg)
                time.sleep(cfg.get("throttle_seconds", 4))
            except Exception as exc:
                print(f"  ERROR retry: {exc}")
                failed.append(ch)
                continue
            eg = check_eg01_truncated(body, ch)
            if not eg["passed"]:
                print(f"  FAIL EG-01: {eg.get('detail')}")
                failed.append(ch)
                continue

        install_chapter(ch, body, cfg)
        from factory.engine.lib.catalog import sync_chapter_pipeline_from_catalog

        sync_chapter_pipeline_from_catalog(WORKSPACE, BOOK, ch)

    if failed:
        print(f"\n[complete] FAILED: {failed}")
        return 1
    print("\n[complete] all chapters installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
