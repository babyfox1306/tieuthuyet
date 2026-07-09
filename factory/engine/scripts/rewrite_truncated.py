"""Rewrite chapters that fail EG-01 (truncated endings). One-off runner for glass-meridian."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.engine.paths import (  # noqa: E402
    chapter_pipeline_path,
    load_config,
    promoted_marker,
    workspace_dir,
)
from factory.engine.run_factory import write_one_chapter  # noqa: E402

CHAPTERS = [10, 11, 33, 38, 40, 45]
WORKSPACE = "glass-meridian"
BOOK = 1
CATALOG_DIR = ROOT / "catalog" / WORKSPACE / "books" / "01-the-glass-meridian" / "chapters"


def prep_chapter(ws: Path, book: int, ch: int) -> None:
    ready = chapter_pipeline_path(ws, book, "ready", ch)
    if ready.exists():
        ready.unlink()
        print(f"  ch_{ch:03d} removed ready")
    prom = promoted_marker(ws, book, ch)
    if prom.exists():
        prom.unlink()
        print(f"  ch_{ch:03d} removed promoted marker")
    for path in CATALOG_DIR.glob("*.md"):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            continue
        meta = yaml.safe_load(raw.split("---", 2)[1]) or {}
        if int(meta.get("chapter") or 0) == ch:
            path.unlink()
            print(f"  ch_{ch:03d} removed catalog {path.name}")


def main() -> int:
    cfg = load_config()
    ws = workspace_dir(WORKSPACE)
    print(f"[rewrite] prep {len(CHAPTERS)} chapters")
    for ch in CHAPTERS:
        prep_chapter(ws, BOOK, ch)

    results: dict[int, str] = {}
    for ch in CHAPTERS:
        print(f"\n[rewrite] === ch_{ch:03d} ===")
        try:
            _, status = write_one_chapter(ws, BOOK, ch, cfg, WORKSPACE, force=True)
        except Exception as exc:
            status = f"error: {exc}"
            print(f"  ch_{ch:03d} ERROR: {exc}")
        results[ch] = status

    print("\n[rewrite] summary:")
    for ch, status in results.items():
        print(f"  ch_{ch:03d}: {status}")
    failed = [ch for ch, s in results.items() if s != "ready"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
