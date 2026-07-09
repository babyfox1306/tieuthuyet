"""Update catalog chapter titles in place (no new files)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.catalog import (  # noqa: E402
    build_frontmatter,
    find_catalog_chapter_by_number,
    normalize_catalog_chapter,
    parse_markdown,
    sync_chapter_pipeline_from_catalog,
)
from factory.engine.lib.prose_sanitize import sanitize_prose  # noqa: E402

WORKSPACE = "glass-meridian"
BOOK_SLUG = "01-the-glass-meridian"
BOOK = 1

TITLE_RENAMES: dict[int, str] = {
    10: "The Phoenix Fragment",
    11: "The Cipher Deepens",
    12: "After the Ambush",
    16: "Marcus Thorne's Name",
    17: "Files and Obstructions",
    18: "Chen's Confession",
    37: "Thorne's Gambit",
    38: "Petrova's Warning",
    47: "After the Confrontation",
}


def save_inplace(ch: int) -> None:
    path = find_catalog_chapter_by_number(WORKSPACE, BOOK_SLUG, ch)
    if not path:
        raise FileNotFoundError(ch)
    meta, body = parse_markdown(path)
    if ch in TITLE_RENAMES:
        meta["title"] = TITLE_RENAMES[ch]
    meta, body = normalize_catalog_chapter(
        meta, sanitize_prose(body.strip()) + "\n", "en",
        workspace_id=WORKSPACE, book=BOOK,
    )
    path.write_text(build_frontmatter(meta) + "\n\n" + body, encoding="utf-8")
    sync_chapter_pipeline_from_catalog(WORKSPACE, BOOK, ch)
    print(f"ch_{ch:03d} -> {meta.get('title')} ({path.name})")


def fix_ch28_cliffhanger() -> None:
    path = find_catalog_chapter_by_number(WORKSPACE, BOOK_SLUG, 28)
    meta, body = parse_markdown(path)
    body = re.sub(r"Cliffhanger:\s*", "", body)
    path.write_text(
        build_frontmatter(meta) + "\n\n" + sanitize_prose(body.strip()) + "\n",
        encoding="utf-8",
    )
    sync_chapter_pipeline_from_catalog(WORKSPACE, BOOK, 28)
    print("ch_028 cliffhanger stripped")


def main() -> None:
    fix_ch28_cliffhanger()
    for ch in sorted(TITLE_RENAMES):
        save_inplace(ch)
    for ch in (19, 20, 29, 39):
        save_inplace(ch)


if __name__ == "__main__":
    main()
