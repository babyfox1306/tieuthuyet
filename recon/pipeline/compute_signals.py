"""Compute review velocity, supply density, and opportunity scores."""

import json
import statistics

from recon.core import db


def _median(vals: list[float]) -> float | None:
    return statistics.median(vals) if vals else None


def _pct_true(flags: list[int | None]) -> float:
    valid = [f for f in flags if f is not None]
    if not valid:
        return 0.0
    return sum(1 for f in valid if f) / len(valid)


def compute_subniche_metrics(conn, subniche_id: int, platform: str | None = None) -> dict:
    """Aggregate metrics for one sub-niche, optionally filtered by platform."""
    q = """
        SELECT s.*, t.spice_level, t.ai_suspicion_mentioned, t.top_3_tropes,
               a.active_6mo
        FROM stories s
        JOIN story_subniches ss ON ss.story_id = s.id
        LEFT JOIN trope_extractions t ON t.story_id = s.id
        LEFT JOIN authors a ON a.platform = s.platform
            AND a.external_id = COALESCE(
                substr(s.author_url, instr(s.author_url, '/e/') + 3),
                s.author_name
            )
        WHERE ss.subniche_id = ?
    """
    params: list = [subniche_id]
    if platform:
        q += " AND s.platform = ?"
        params.append(platform)
    rows = conn.execute(q, params).fetchall()

    if not rows:
        return {"subniche_id": subniche_id, "platform": platform, "count": 0}

    bsr_vals = [r["bsr_overall"] for r in rows if r["bsr_overall"]]
    review_counts = [r["review_count"] for r in rows if r["review_count"]]
    velocities = [r["review_velocity_30d"] for r in rows if r["review_velocity_30d"] is not None]
    series_lens = [
        r["series_total_books"] or r["chapter_count"] or r["episodes_count"]
        for r in rows
        if (r["series_total_books"] or r["chapter_count"] or r["episodes_count"])
    ]
    ku_flags = [r["ku_enrolled"] for r in rows]
    ratings = [r["rating_avg"] for r in rows if r["rating_avg"]]
    active_flags = [r["active_6mo"] for r in rows]
    ai_flags = [r["ai_suspicion_mentioned"] for r in rows if r["ai_suspicion_mentioned"] is not None]

    spice_levels = [r["spice_level"] for r in rows if r["spice_level"]]
    tropes: list[str] = []
    for r in rows:
        if r["top_3_tropes"]:
            try:
                tropes.extend(json.loads(r["top_3_tropes"]))
            except json.JSONDecodeError:
                pass

    median_bsr = _median([float(v) for v in bsr_vals])
    median_reviews = _median([float(v) for v in review_counts])
    median_velocity = _median([float(v) for v in velocities]) if velocities else 0.0
    median_series = _median([float(v) for v in series_lens]) if series_lens else 0.0
    ku_rate = _pct_true(ku_flags)
    supply_density = _pct_true(active_flags)
    ai_rate = _pct_true(ai_flags)
    median_rating = _median([float(v) for v in ratings]) if ratings else None

    # Opportunity score (spec formula, adapted per platform)
    denom = max(supply_density, 0.01) * (1 + ai_rate)
    opportunity = (median_velocity * max(median_series, 1) * max(ku_rate, 0.1)) / denom

    return {
        "subniche_id": subniche_id,
        "platform": platform or "all",
        "count": len(rows),
        "median_bsr": median_bsr,
        "median_review_count": median_reviews,
        "median_review_velocity_30d": median_velocity,
        "median_series_length": median_series,
        "ku_rate": ku_rate,
        "supply_density": supply_density,
        "ai_suspicion_rate": ai_rate,
        "median_rating": median_rating,
        "dominant_tropes": _top_n(tropes, 5),
        "spice_distribution": _spice_dist(spice_levels),
        "opportunity_score": opportunity,
        "disqualified": _is_disqualified(
            supply_density, median_velocity, median_series, ai_rate, median_rating
        ),
    }


def _top_n(items: list[str], n: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.strip().lower()
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])[:n]


def _spice_dist(levels: list[str]) -> dict[str, float]:
    if not levels:
        return {}
    total = len(levels)
    dist: dict[str, int] = {}
    for lv in levels:
        dist[lv] = dist.get(lv, 0) + 1
    return {k: v / total for k, v in dist.items()}


def _is_disqualified(
    supply_density: float,
    median_velocity: float,
    median_series: float,
    ai_rate: float,
    median_rating: float | None,
) -> bool:
    if supply_density > 0.70:
        return True
    if median_velocity < 5:
        return True
    if median_series < 3:
        return True
    if ai_rate > 0.30:
        return True
    if median_rating is not None and median_rating < 4.0:
        return True
    return False
