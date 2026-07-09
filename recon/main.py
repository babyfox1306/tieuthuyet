#!/usr/bin/env python3
"""KDP Sub-niche Recon — multi-platform CLI orchestrator."""

import argparse
import sys
from pathlib import Path

# Allow running as `python recon/main.py` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recon.config import PLATFORMS, SUB_NICHES
from recon.core import db
from recon.core.browser import CaptchaDetected, browser_session
from recon.scrapers import (
    goodnovel,
    kdp_author,
    kdp_product,
    kdp_reviews,
    kdp_search,
    royalroad,
    vella,
    webnovel,
)
from recon.pipeline import build_decision_matrix, extract_tropes


def _platforms_arg(value: str) -> list[str]:
    if value == "all":
        return list(PLATFORMS)
    parts = [p.strip().lower() for p in value.split(",")]
    for p in parts:
        if p not in PLATFORMS:
            raise argparse.ArgumentTypeError(f"Unknown platform: {p}")
    return parts


def run_search(platforms: list[str], subniche_ids: list[int] | None, headless: bool) -> None:
    db.init_db()
    ids = subniche_ids or list(SUB_NICHES.keys())

    with browser_session(headless=headless) as (_, context):
        for sid in ids:
            meta = SUB_NICHES[sid]
            print(f"\n=== Sub-niche {sid}: {meta['label']} ===")

            if "amazon" in platforms:
                try:
                    items = kdp_search.search(context, meta["amazon"], sid)
                    _save_search_results(items, sid)
                    print(f"  [amazon] {len(items)} ASINs")
                except CaptchaDetected as e:
                    print(f"  [amazon] CAPTCHA — pause and retry: {e}")

            if "vella" in platforms:
                items = vella.search(context, meta["vella"], sid)
                _save_search_results(items, sid)
                print(f"  [vella] {len(items)} stories")

            if "webnovel" in platforms:
                items = webnovel.search(context, meta["webnovel"], sid)
                _save_search_results(items, sid)
                print(f"  [webnovel] {len(items)} books")

            if "goodnovel" in platforms:
                items = goodnovel.search(context, meta["goodnovel"], sid)
                _save_search_results(items, sid)
                print(f"  [goodnovel] {len(items)} books")

            if "royalroad" in platforms:
                tags = meta.get("royalroad", [])
                items = royalroad.search(context, meta["amazon"].split()[0], sid, tags=tags)
                _save_search_results(items, sid)
                print(f"  [royalroad] {len(items)} fictions")


def _save_search_results(items: list[dict], subniche_id: int) -> None:
    with db.connect() as conn:
        for item in items:
            story_id = db.upsert_story(conn, item)
            db.link_story_subniche(conn, story_id, subniche_id, item.get("rank_in_search", 0))


def run_detail(platforms: list[str], headless: bool) -> None:
    db.init_db()
    with browser_session(headless=headless) as (_, context):
        with db.connect() as conn:
            for platform in platforms:
                rows = db.get_stories_for_platform(conn, platform)
                print(f"\n=== Detail scrape: {platform} ({len(rows)} stories) ===")
                for row in rows:
                    ext_id = row["external_id"]
                    try:
                        if platform == "amazon":
                            data = kdp_product.scrape(context, ext_id)
                            data["subniche_id"] = row["subniche_id"]
                            story_id = db.upsert_story(conn, {**dict(row), **data})
                            reviews, velocity = kdp_reviews.scrape(context, ext_id)
                            data["review_velocity_30d"] = velocity
                            db.upsert_story(conn, {"platform": "amazon", "external_id": ext_id, "review_velocity_30d": velocity})
                            db.insert_reviews(conn, story_id, "amazon", reviews)
                            if data.get("author_url"):
                                author = kdp_author.scrape(context, data["author_url"])
                                db.upsert_author(conn, author)
                            print(f"  [amazon] {ext_id} — {data.get('title', '?')[:50]}")

                        elif platform == "vella":
                            url = row["story_url"]
                            data = vella.scrape_detail(context, ext_id, url)
                            story_id = db.upsert_story(conn, {**dict(row), **data})
                            print(f"  [vella] {ext_id} — {data.get('title', '?')[:50]}")

                        elif platform == "webnovel":
                            data = webnovel.scrape_detail(context, ext_id)
                            db.upsert_story(conn, {**dict(row), **data})
                            print(f"  [webnovel] {ext_id} — {data.get('title', '?')[:50]}")

                        elif platform == "goodnovel":
                            data = goodnovel.scrape_detail(context, ext_id)
                            db.upsert_story(conn, {**dict(row), **data})
                            print(f"  [goodnovel] {ext_id} — {data.get('title', '?')[:50]}")

                        elif platform == "royalroad":
                            data = royalroad.scrape_detail(context, ext_id)
                            story_id = db.patch_story(conn, "royalroad", ext_id, data)
                            reviews = royalroad.scrape_reviews(context, ext_id)
                            if reviews:
                                db.insert_reviews(conn, story_id, "royalroad", reviews)
                            print(f"  [royalroad] {ext_id} — {data.get('title', '?')[:50]} | rating={data.get('rating_avg')}")

                    except CaptchaDetected as e:
                        print(f"  [{platform}] CAPTCHA on {ext_id}: {e}")
                    except Exception as exc:
                        print(f"  [{platform}] {ext_id} error: {exc}")

    # Handoff: export CSV immediately after detail scrape
    from recon.pipeline.build_decision_matrix import export_csvs

    books_path, authors_path = export_csvs()
    print(f"\n[detail] Exported {books_path}")
    print(f"[detail] Exported {authors_path}")


def run_reparse(platforms: list[str]) -> None:
    """Re-parse cached HTML into DB (no network). Useful after parser fixes."""
    from recon.pipeline.build_decision_matrix import export_csvs

    db.init_db()
    patched = 0
    missing = 0
    with db.connect() as conn:
        for platform in platforms:
            rows = db.get_stories_for_platform(conn, platform)
            print(f"\n=== Reparse cached HTML: {platform} ({len(rows)} stories) ===")
            for row in rows:
                ext_id = row["external_id"]
                data = None
                if platform == "royalroad":
                    data = royalroad.reparse_cached(ext_id)
                if not data:
                    print(f"  [{platform}] {ext_id} — no cached HTML, run detail")
                    missing += 1
                    continue
                db.patch_story(conn, platform, ext_id, data)
                patched += 1
                print(
                    f"  [{platform}] {ext_id} — {data.get('title', '?')[:40]} "
                    f"| rating={data.get('rating_avg')} views={data.get('view_count')}"
                )

    books_path, authors_path = export_csvs()
    print(f"\n[reparse] Patched {patched}, missing cache {missing}")
    print(f"[reparse] Exported {books_path}")
    print(f"[reparse] Exported {authors_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KDP Sub-niche Recon (multi-platform)")
    parser.add_argument(
        "command",
        choices=["init", "search", "detail", "reparse", "tropes", "matrix", "full"],
        help="Pipeline stage to run",
    )
    parser.add_argument(
        "--platforms",
        type=_platforms_arg,
        default="all",
        help="Comma-separated: amazon,vella,webnovel,goodnovel,royalroad or 'all'",
    )
    parser.add_argument("--subniches", type=str, default=None, help="Comma-separated sub-niche IDs, e.g. 1,2,3")
    parser.add_argument("--headed", action="store_true", help="Show browser (non-headless)")
    args = parser.parse_args()

    platforms: list[str] = args.platforms if isinstance(args.platforms, list) else _platforms_arg(args.platforms)
    subniche_ids = None
    if args.subniches:
        subniche_ids = [int(x.strip()) for x in args.subniches.split(",")]

    headless = not args.headed

    if args.command == "init":
        db.init_db()
        print("Database initialized.")
    elif args.command == "search":
        run_search(platforms, subniche_ids, headless)
    elif args.command == "detail":
        run_detail(platforms, headless)
    elif args.command == "reparse":
        run_reparse(platforms)
    elif args.command == "tropes":
        n = extract_tropes.run_all()
        print(f"Trope extraction complete: {n} stories")
    elif args.command == "matrix":
        build_decision_matrix.run()
    elif args.command == "full":
        db.init_db()
        run_search(platforms, subniche_ids, headless)
        run_detail(platforms, headless)
        extract_tropes.run_all()
        build_decision_matrix.run()


if __name__ == "__main__":
    main()
