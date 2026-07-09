"""Fix glass-meridian catalog issues caught by export gate v2 publish scan."""
from __future__ import annotations

import json
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
    build_frontmatter,
    chapter_filename,
    find_catalog_chapter_by_number,
    normalize_catalog_chapter,
    parse_markdown,
    sync_chapter_pipeline_from_catalog,
    write_catalog_chapter,
)
from factory.engine.lib.export_gate import check_eg01_truncated  # noqa: E402
from factory.engine.lib.prose_sanitize import sanitize_prose  # noqa: E402
from factory.engine.lib.prompt_builder import load_direction  # noqa: E402
from factory.engine.paths import load_config, workspace_dir  # noqa: E402

WORKSPACE = "glass-meridian"
BOOK_SLUG = "01-the-glass-meridian"
BOOK = 1

# Later chapter in each dup pair gets a unique title (master_plan had copy-paste titles)
TITLE_RENAMES: dict[int, tuple[str, str]] = {
    10: ("The Phoenix Fragment", "the-phoenix-fragment"),
    11: ("The Cipher Deepens", "the-cipher-deepens"),
    12: ("After the Ambush", "after-the-ambush"),
    16: ("Marcus Thorne's Name", "marcus-thornes-name"),
    17: ("Files and Obstructions", "files-and-obstructions"),
    18: ("Chen's Confession", "chens-confession"),
    37: ("Thorne's Gambit", "thornes-gambit"),
    38: ("Petrova's Warning", "petrovas-warning"),
    47: ("After the Confrontation", "after-the-confrontation"),
}

SYSTEM_CH39 = """You complete fiction chapters cut off mid-dialogue.
Output ONLY the continuation (1-3 paragraphs). No markdown. English only.
Close Adrian/Lin Wei phone call to Professor Chen — she must finish her urgent demand.
End on a complete sentence with proper closing quote punctuation."""


def find_chapter_path(ch: int) -> Path:
    p = find_catalog_chapter_by_number(WORKSPACE, BOOK_SLUG, ch)
    if not p:
        raise FileNotFoundError(f"catalog chapter {ch}")
    return p


def save_chapter(ch: int, meta: dict, body: str) -> None:
    path = find_chapter_path(ch)
    lang = "en"
    meta, body = normalize_catalog_chapter(
        meta, body, lang, workspace_id=WORKSPACE, book=BOOK
    )
    content = build_frontmatter(meta) + "\n\n" + body
    path.write_text(content, encoding="utf-8")
    sync_chapter_pipeline_from_catalog(WORKSPACE, BOOK, ch)
    print(f"  ch_{ch:03d} saved -> {path.name}")


def fix_cliffhanger_lines() -> None:
    for ch in (28, 29):
        path = find_chapter_path(ch)
        meta, body = parse_markdown(path)
        body = re.sub(r"(?im)^Cliffhanger:\s*", "", body)
        body = sanitize_prose(body.strip()) + "\n"
        save_chapter(ch, meta, body)
        print(f"  ch_{ch:03d} stripped Cliffhanger label")


def fix_cjk() -> None:
    fixes = {
        19: ("归档", "archived"),
        20: ("沙龙", "salon"),
    }
    for ch, (bad, good) in fixes.items():
        path = find_chapter_path(ch)
        meta, body = parse_markdown(path)
        body = body.replace(bad, good)
        save_chapter(ch, meta, body)
        print(f"  ch_{ch:03d} CJK replaced")


def fix_ch39(cfg: dict) -> None:
    path = find_chapter_path(39)
    meta, body = parse_markdown(path)
    direction = load_direction(workspace_dir(WORKSPACE))
    tail = body[-800:]
    prompt = (
        "CHAPTER 39: Lin Wei calls Professor Chen about Code White / mother in danger.\n"
        "The text ends mid-dialogue. Continue and close the scene.\n\n"
        f"--- CUT ---\n{tail}\n--- END ---"
    )
    cont, _ = call_9router(
        "writer", prompt, direction=direction, system_override=SYSTEM_CH39, max_tokens=1200
    )
    cont = sanitize_prose(cont.strip())
    merged = body.rstrip() + "\n\n" + cont
    eg = check_eg01_truncated(merged, 39)
    if not eg["passed"]:
        print(f"  ch_039 WARN still EG-01: {eg.get('detail')}")
    save_chapter(39, meta, merged)
    time.sleep(cfg.get("throttle_seconds", 4))


def fix_dup_titles() -> None:
    plan_path = workspace_dir(WORKSPACE) / "books" / "01" / "master_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plans = plan.get("chapter_plans", [])
    by_ch = {int(p["chapter"]): p for p in plans if p.get("chapter")}

    for ch, (title, slug) in TITLE_RENAMES.items():
        path = find_chapter_path(ch)
        meta, body = parse_markdown(path)
        meta["title"] = title
        if ch in by_ch:
            by_ch[ch]["title"] = title
            by_ch[ch]["slug"] = slug
        save_chapter(ch, meta, body)
        print(f"  ch_{ch:03d} title -> {title}")

    plan["chapter_plans"] = [by_ch[i] for i in sorted(by_ch)]
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  master_plan.json titles updated")


def main() -> int:
    cfg = load_config()
    print("[fix-gate] Cliffhanger labels")
    fix_cliffhanger_lines()
    print("[fix-gate] CJK")
    fix_cjk()
    print("[fix-gate] ch39 continuation (LLM)")
    fix_ch39(cfg)
    print("[fix-gate] duplicate titles")
    fix_dup_titles()
    print("[fix-gate] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
