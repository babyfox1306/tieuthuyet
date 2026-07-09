"""Build CSV exports and subniche_decision_matrix.md."""

import csv
import json
from pathlib import Path

from recon.config import OUTPUT_DIR, PLATFORMS, SUB_NICHES
from recon.core import db
from recon.pipeline.compute_signals import compute_subniche_metrics


STORY_COLUMNS = [
    "platform",
    "external_id",
    "subniche_id",
    "search_keyword",
    "rank_in_search",
    "title",
    "author_name",
    "story_url",
    "bsr_overall",
    "rating_avg",
    "review_count",
    "review_velocity_30d",
    "ku_enrolled",
    "series_total_books",
    "chapter_count",
    "episodes_count",
    "view_count",
    "follower_count",
    "status",
    "tags",
    "price_usd",
    "scraped_at",
]

AUTHOR_COLUMNS = [
    "platform",
    "external_id",
    "name",
    "profile_url",
    "total_books",
    "total_series",
    "latest_publish_date",
    "active_6mo",
    "has_vella",
    "scraped_at",
]


def export_csvs() -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    books_path = OUTPUT_DIR / "recon_stories.csv"
    authors_path = OUTPUT_DIR / "recon_authors.csv"

    with db.connect() as conn:
        stories = db.get_all_stories(conn)
        authors = conn.execute("SELECT * FROM authors ORDER BY platform, name").fetchall()

    with books_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=STORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in stories:
            w.writerow({k: row[k] for k in STORY_COLUMNS})

    with authors_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=AUTHOR_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for row in authors:
            w.writerow({k: row[k] for k in AUTHOR_COLUMNS})

    return books_path, authors_path


def build_decision_matrix() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "subniche_decision_matrix.md"
    lines: list[str] = [
        "# Sub-niche Decision Matrix",
        "",
        "Multi-platform recon: Amazon KDP + Kindle Vella + Webnovel + GoodNovel + Royal Road.",
        "",
    ]

    all_rankings: list[tuple[str, int, str, float, bool]] = []

    with db.connect() as conn:
        for sid, meta in sorted(SUB_NICHES.items()):
            label = meta["label"]
            lines.append(f"## {sid}. {label}")
            lines.append("")

            for platform in ["all"] + PLATFORMS:
                m = compute_subniche_metrics(conn, sid, platform=None if platform == "all" else platform)
                if m["count"] == 0:
                    continue
                plat_label = "Combined" if platform == "all" else platform.title()
                lines.append(f"### {plat_label}")
                lines.append("")
                lines.append(f"- **Stories sampled**: {m['count']}")
                if m.get("median_bsr"):
                    lines.append(f"- **Demand (median BSR)**: {m['median_bsr']:.0f} (lower = stronger on Amazon)")
                if m.get("median_review_count"):
                    lines.append(f"- **Buyer proof (median reviews)**: {m['median_review_count']:.0f}")
                lines.append(f"- **Heat (median review velocity /30d)**: {m['median_review_velocity_30d']:.1f}")
                lines.append(f"- **Binge potential (median series/chapters)**: {m['median_series_length']:.1f}")
                lines.append(f"- **KU rate**: {m['ku_rate']*100:.0f}%")
                lines.append(f"- **Supply density (active authors 6mo)**: {m['supply_density']*100:.0f}%")
                lines.append(f"- **AI suspicion rate**: {m['ai_suspicion_rate']*100:.0f}%")
                if m.get("median_rating"):
                    lines.append(f"- **Median rating**: {m['median_rating']:.2f}")
                if m.get("dominant_tropes"):
                    tropes_str = ", ".join(f"{t} ({c})" for t, c in m["dominant_tropes"])
                    lines.append(f"- **Dominant tropes**: {tropes_str}")
                if m.get("spice_distribution"):
                    spice_str = ", ".join(f"{k}: {v*100:.0f}%" for k, v in m["spice_distribution"].items())
                    lines.append(f"- **Spice distribution**: {spice_str}")
                lines.append(f"- **Opportunity score**: {m['opportunity_score']:.2f}")
                dq = "**DISQUALIFIED**" if m["disqualified"] else "pass"
                lines.append(f"- **KPI check**: {dq}")
                lines.append("")

                if platform == "all":
                    all_rankings.append((label, sid, "all", m["opportunity_score"], m["disqualified"]))

            lines.append("---")
            lines.append("")

        lines.append("## Ranking (Combined platforms)")
        lines.append("")
        lines.append("| Rank | Sub-niche | Score | Status |")
        lines.append("|------|-----------|-------|--------|")
        ranked = sorted(all_rankings, key=lambda x: -x[3])
        for i, (label, sid, _, score, dq) in enumerate(ranked, 1):
            status = "SKIP" if dq else "GO"
            lines.append(f"| {i} | {sid}. {label} | {score:.2f} | {status} |")

        lines.append("")
        lines.append("## Platform breakdown ranking")
        lines.append("")
        for platform in PLATFORMS:
            lines.append(f"### {platform.title()}")
            lines.append("")
            lines.append("| Rank | Sub-niche | Score |")
            lines.append("|------|-----------|-------|")
            plat_scores: list[tuple[str, int, float]] = []
            for sid, meta in SUB_NICHES.items():
                m = compute_subniche_metrics(conn, sid, platform)
                if m["count"]:
                    plat_scores.append((meta["label"], sid, m["opportunity_score"]))
            for i, (label, sid, score) in enumerate(sorted(plat_scores, key=lambda x: -x[2]), 1):
                lines.append(f"| {i} | {sid}. {label} | {score:.2f} |")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run() -> None:
    export_csvs()
    path = build_decision_matrix()
    print(f"[build_decision_matrix] wrote {path}")
