"""Split The Meridian Spine out of the-kessler-line into its own workspace.

Idempotent-ish: refuses if the-meridian-spine already exists with content.
Does NOT rewrite chapter prose — only paths / ids / book numbers.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WS_ROOT = ROOT / "factory" / "workspaces"
CATALOG = ROOT / "catalog"

SRC_WS = "the-kessler-line"
DST_WS = "the-meridian-spine"
SRC_BOOK = 2
DST_BOOK = 1
SRC_SLUG = "02-the-meridian-spine"
DST_SLUG = "01-the-meridian-spine"


def _dump(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _rewrite_frontmatter_book(md_path: Path, book: int, series: str) -> None:
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    meta = yaml.safe_load(parts[1]) or {}
    meta["book"] = book
    meta["series"] = series
    body = parts[2].lstrip("\n")
    md_path.write_text(
        "---\n"
        + yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n\n"
        + body,
        encoding="utf-8",
    )


def main() -> None:
    src = WS_ROOT / SRC_WS
    dst = WS_ROOT / DST_WS
    if not src.exists():
        raise SystemExit(f"missing source workspace: {src}")
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit(f"destination already exists: {dst}")

    src_book_dir = src / "books" / f"{SRC_BOOK:02d}"
    if not src_book_dir.exists():
        raise SystemExit(f"missing Book 2 folder: {src_book_dir}")

    print(f"[1] create workspace {DST_WS}")
    dst.mkdir(parents=True)
    (dst / "bible").mkdir(parents=True)
    (dst / "books" / f"{DST_BOOK:02d}").mkdir(parents=True)

    # bible (already Meridian)
    if (src / "bible").exists():
        shutil.copytree(src / "bible", dst / "bible", dirs_exist_ok=True)

    # books/02 -> books/01
    print(f"[2] copy books/{SRC_BOOK:02d} -> books/{DST_BOOK:02d}")
    shutil.copytree(src_book_dir, dst / "books" / f"{DST_BOOK:02d}", dirs_exist_ok=True)

    # concept: prefer Book 2 concept as root + books/01
    b2_concept = src_book_dir / "concept.yaml"
    concept_src = b2_concept if b2_concept.exists() else (src / "concept.yaml")
    shutil.copy2(concept_src, dst / "concept.yaml")
    shutil.copy2(concept_src, dst / "books" / f"{DST_BOOK:02d}" / "concept.yaml")

    concept = _load(dst / "concept.yaml")
    blurb = str(concept.get("logline") or concept.get("blurb") or "").strip()
    ending = str(concept.get("ending_book1") or "").strip()

    direction = {
        "id": DST_WS,
        "pen_name": "Nix Vale",
        "target_language": "en",
        "publish_strategy": "kdp_ku_exclusive",
        "narrative_status": "approved",
        "book": DST_BOOK,
        "canon_through": 0,
        "platform": "kdp",
        "audience": "women 18-35, mobile reading, hook-driven serial fiction",
        "goal": "end-of-chapter hooks — institutional conspiracy thriller pace",
        "setting_hub": "The Meridian Spine — primary setting",
        "setting_nodes": [],
        "spice_default": 1,
        "spice_explicit_chapters": [],
        "spice_steamy_chapters": [],
        "book1_ending": ending,
        "blurb": blurb,
        "tropes": [],
        "spice_badge": "sweet",
        "target_platforms": ["kdp"],
        "spice_level": 1,
        "plan_status": "approved",
        "bible_status": "approved",
        "book_slug": DST_SLUG,
        "total_chapters": int(concept.get("chapter_count") or 22),
        "arc": {
            "act1_setup": [1, 6],
            "act2_complications": [7, 12],
            "act3_crisis": [13, 19],
            "act4_resolution": [20, 22],
        },
        "narrative_profile": "conspiracy_thriller",
        "prior_workspace": SRC_WS,
    }
    # preserve digests from kessler direction if present
    src_dir = _load(src / "direction.yaml")
    for k in ("source_concept_digest", "source_narrative_digest"):
        if src_dir.get(k):
            direction[k] = src_dir[k]
    _dump(dst / "direction.yaml", direction)

    manifest = {
        "id": DST_WS,
        "pen_name": "Nix Vale",
        "target_language": "en",
        "spice_level": 1,
        "publish_strategy": "kdp_ku_exclusive",
        "book_slug": DST_SLUG,
        "blurb": blurb,
        "canon_through": 0,
        "plan_status": "approved",
        "bible_status": "approved",
        "total_chapters": direction["total_chapters"],
        "active_book": DST_BOOK,
        "prior_workspace": SRC_WS,
    }
    _dump(dst / "manifest.yaml", manifest)

    # canon_registry with prior_workspace + structured ontology locks
    registry = {
        "characters": {
            "female_lead": {
                "canonical": "Iris Kane",
                "allowed_aliases": ["Iris", "Kane"],
                "forbidden_aliases": [],
            },
            "male_lead": {
                "canonical": "Stellan Marsh",
                "allowed_aliases": ["Stellan", "Marsh"],
                "forbidden_aliases": [],
            },
        },
        "pov_mode": "third_person_limited",
        "spice_max": 0,
        "cast": [
            "Petra Lund",
            "Nadia Okafor",
            "Gerald Halveston",
            "Stellan Marsh",
        ],
        "prior_workspace": SRC_WS,
        "inherited_canon": [
            {
                "id": "kessler_structure",
                "fact": (
                    "The Kessler Line disaster was a TUNNEL collapse "
                    "(eastbound tunnel / liner failure). It was NOT a bridge."
                ),
                "forbid_patterns": [
                    r"\bkessler\s+bridge\b",
                    r"\bthe\s+kessler\s+bridge\b",
                ],
            },
            {
                "id": "kessler_evidence",
                "fact": (
                    "Book-1 central physical proof was a concrete CORE SAMPLE "
                    "from the failed tunnel liner. It is SPENT. Book-1 did NOT "
                    "win on a 'Kessler coupon'."
                ),
                "forbid_patterns": [
                    r"\bkessler\s+coupon\b",
                    r"\bkessler\s+coupon\s+micrograph\b",
                    r"\bcoupon\s+micrograph\b.*\bkessler\b",
                    r"\bkessler\b.*\bcoupon\s+micrograph\b",
                ],
            },
            {
                "id": "renn_status",
                "fact": (
                    "Aldous Renn is convicted and in custody. Prison source only. "
                    "Not Book-2 top, not freed, not active mastermind."
                ),
                "forbid_patterns": [
                    r"\brenn\s+(?:was\s+)?(?:freed|released|exonerated)\b",
                    r"\brenn\s+(?:is|was)\s+the\s+(?:architect|mastermind)\b",
                ],
            },
            {
                "id": "core_sample_spent",
                "fact": (
                    "The Book-1 core sample was published once, irrevocably. "
                    "It cannot be Book-2's winning card again."
                ),
                "forbid_patterns": [],
            },
            {
                "id": "redacted_co_owners",
                "fact": (
                    "Book-1 fast-track page named private co-owners; redacted; "
                    "Iris never recovered the final name. Engine of Book 2."
                ),
                "forbid_patterns": [],
            },
            {
                "id": "iris_public",
                "fact": (
                    "Iris Kane is free and public after Book 1 — the engineer "
                    "who brought down Renn."
                ),
                "forbid_patterns": [],
            },
            {
                "id": "physical_spine_b2",
                "fact": (
                    "Book-2 physical spine is tool-mark signature on Meridian Spine "
                    "certified coupons matching Kessler's override method — "
                    "NOT the Book-1 core sample. Meridian 'coupon' is allowed; "
                    "'Kessler coupon' is not."
                ),
                "forbid_patterns": [],
            },
        ],
    }
    _dump(dst / "canon_registry.yaml", registry)

    # Fix book_arc book_number if present
    arc_path = dst / "bible" / "narrative" / "book_arc.json"
    if arc_path.exists():
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
            if isinstance(arc, dict):
                arc["book_number"] = DST_BOOK
                arc_path.write_text(
                    json.dumps(arc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
        except json.JSONDecodeError:
            pass

    # Catalog move
    src_cat = CATALOG / SRC_WS / "books" / SRC_SLUG
    dst_series = CATALOG / DST_WS
    dst_cat = dst_series / "books" / DST_SLUG
    if not src_cat.exists():
        raise SystemExit(f"missing catalog book: {src_cat}")
    print(f"[3] move catalog {SRC_SLUG} -> {DST_SLUG}")
    dst_series.mkdir(parents=True, exist_ok=True)
    (dst_series / "books").mkdir(exist_ok=True)
    if dst_cat.exists():
        raise SystemExit(f"catalog destination exists: {dst_cat}")
    shutil.move(str(src_cat), str(dst_cat))

    book_yaml = {
        "book": DST_BOOK,
        "slug": DST_SLUG,
        "title": str(concept.get("title") or "The Meridian Spine"),
        "series": DST_WS,
        "language": "en",
        "total_chapters": direction["total_chapters"],
    }
    _dump(dst_cat / "book.yaml", book_yaml)

    series_yaml = {
        "id": DST_WS,
        "pen_name": "Nix Vale",
        "blurb": blurb,
        "tropes": [],
        "spice_badge": "sweet",
        "target_platforms": ["kdp"],
    }
    _dump(dst_series / "series.yaml", series_yaml)

    print("[4] rewrite chapter frontmatter book/series")
    chapters_dir = dst_cat / "chapters"
    for path in sorted(chapters_dir.glob("*.md")):
        _rewrite_frontmatter_book(path, DST_BOOK, DST_WS)

    # Rename epub artifacts if present
    epub_dir = dst_cat / "exports" / "epub"
    if epub_dir.exists():
        for old in list(epub_dir.glob(f"{SRC_SLUG}.*")):
            new = epub_dir / old.name.replace(SRC_SLUG, DST_SLUG, 1)
            if not new.exists():
                old.rename(new)
                print(f"  renamed {old.name} -> {new.name}")

    # Spot-check: copy Meridian chapter files into new series spot_check
    sc_src = CATALOG / SRC_WS / "spot_check"
    sc_dst = dst_series / "spot_check"
    sc_dst.mkdir(exist_ok=True)
    if sc_src.exists():
        meridian_names = {p.name for p in chapters_dir.glob("*.md")}
        for path in sc_src.glob("*.md"):
            if path.name in meridian_names:
                shutil.copy2(path, sc_dst / path.name)
                _rewrite_frontmatter_book(sc_dst / path.name, DST_BOOK, DST_WS)
                path.unlink()

    # Reset Kessler workspace to Book 1 only
    print("[5] reset the-kessler-line to Book 1")
    k_concept = _load(src / "concept.yaml")
    k_blurb = str(k_concept.get("logline") or "").strip()
    k_ending = str(k_concept.get("ending_book1") or "").strip()
    k_dir = {
        "id": SRC_WS,
        "pen_name": "Nix Vale",
        "target_language": "en",
        "publish_strategy": "kdp_ku_exclusive",
        "narrative_status": "approved",
        "book": 1,
        "canon_through": 0,
        "platform": "kdp",
        "audience": "women 18-35, mobile reading, hook-driven serial fiction",
        "goal": "end-of-chapter hooks — institutional conspiracy thriller pace",
        "setting_hub": "The Kessler Line — primary setting",
        "setting_nodes": [],
        "spice_default": 1,
        "spice_explicit_chapters": [],
        "spice_steamy_chapters": [],
        "book1_ending": k_ending,
        "blurb": k_blurb,
        "tropes": [],
        "spice_badge": "sweet",
        "target_platforms": ["kdp"],
        "spice_level": 1,
        "plan_status": "approved",
        "bible_status": "approved",
        "book_slug": "01-the-kessler-line",
        "total_chapters": int(k_concept.get("chapter_count") or 22),
        "arc": {
            "act1_setup": [1, 6],
            "act2_complications": [7, 12],
            "act3_crisis": [13, 19],
            "act4_resolution": [20, 22],
        },
        "narrative_profile": "conspiracy_thriller",
    }
    _dump(src / "direction.yaml", k_dir)
    k_man = {
        "id": SRC_WS,
        "pen_name": "Nix Vale",
        "target_language": "en",
        "spice_level": 1,
        "publish_strategy": "kdp_ku_exclusive",
        "book_slug": "01-the-kessler-line",
        "blurb": k_blurb,
        "canon_through": 0,
        "plan_status": "approved",
        "bible_status": "approved",
        "total_chapters": k_dir["total_chapters"],
        "active_book": 1,
    }
    _dump(src / "manifest.yaml", k_man)

    # Strip Meridian-only inherited_canon from kessler registry; keep Book 1 leads
    k_reg_path = src / "canon_registry.yaml"
    if k_reg_path.exists():
        k_reg = _load(k_reg_path)
        # Book 1 male lead was Aldous Renn historically — but registry may have been
        # overwritten to Marsh for Book 2. Restore from Book 1 concept if needed.
        # Keep whatever characters block exists; remove Book-2-only keys.
        k_reg.pop("book2_cast", None)
        k_reg.pop("inherited_canon", None)
        k_reg.pop("cast", None)
        # Prefer Renn as male_lead for Book 1 workspace if Marsh is set
        ml = (k_reg.get("characters") or {}).get("male_lead") or {}
        if str(ml.get("canonical") or "") == "Stellan Marsh":
            k_reg.setdefault("characters", {})["male_lead"] = {
                "canonical": "Aldous Renn",
                "allowed_aliases": ["Aldous", "Renn", "Commissioner Renn"],
                "forbidden_aliases": [],
            }
        _dump(k_reg_path, k_reg)

    # Remove Book 2 folder from kessler after successful copy
    print(f"[6] remove {src_book_dir}")
    shutil.rmtree(src_book_dir)

    # Update catalog series.yaml for kessler
    k_series = CATALOG / SRC_WS / "series.yaml"
    if k_series.exists():
        _dump(
            k_series,
            {
                "id": SRC_WS,
                "pen_name": "Nix Vale",
                "blurb": k_blurb,
                "tropes": [],
                "spice_badge": "sweet",
                "target_platforms": ["kdp"],
            },
        )

    print("DONE")
    print(f"  workspace: {dst}")
    print(f"  catalog:   {dst_cat}")
    print(f"  prior:     {SRC_WS} (Book 1 only)")


if __name__ == "__main__":
    main()
