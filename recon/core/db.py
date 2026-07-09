"""SQLite storage for multi-platform recon data."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from recon.config import DATA_DIR, DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS subniche_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subniche_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    keyword TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    subniche_id INTEGER,
    search_keyword TEXT,
    rank_in_search INTEGER,
    title TEXT,
    author_name TEXT,
    author_url TEXT,
    story_url TEXT,
    series_name TEXT,
    series_book_num INTEGER,
    series_total_books INTEGER,
    publish_date TEXT,
    latest_series_publish_date TEXT,
    price_usd REAL,
    page_count INTEGER,
    ku_enrolled INTEGER,
    format_mix TEXT,
    bsr_overall INTEGER,
    bsr_subcategory TEXT,
    bsr_sub_rank INTEGER,
    rating_avg REAL,
    review_count INTEGER,
    rating_pct_5star REAL,
    rating_pct_1star REAL,
    review_velocity_30d INTEGER,
    also_bought TEXT,
    categories TEXT,
    tags TEXT,
    chapter_count INTEGER,
    view_count INTEGER,
    follower_count INTEGER,
    status TEXT,
    last_update TEXT,
    episodes_count INTEGER,
    raw_json TEXT,
    scraped_at TEXT,
    UNIQUE(platform, external_id)
);

CREATE TABLE IF NOT EXISTS story_subniches (
    story_id INTEGER NOT NULL,
    subniche_id INTEGER NOT NULL,
    rank_in_search INTEGER,
    PRIMARY KEY (story_id, subniche_id),
    FOREIGN KEY (story_id) REFERENCES stories(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    reviewer TEXT,
    rating INTEGER,
    title TEXT,
    body TEXT,
    review_date TEXT,
    scraped_at TEXT,
    FOREIGN KEY (story_id) REFERENCES stories(id)
);

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT,
    profile_url TEXT,
    total_books INTEGER,
    total_series INTEGER,
    latest_publish_date TEXT,
    active_6mo INTEGER,
    has_vella INTEGER,
    raw_json TEXT,
    scraped_at TEXT,
    UNIQUE(platform, external_id)
);

CREATE TABLE IF NOT EXISTS trope_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id INTEGER NOT NULL UNIQUE,
    top_3_tropes TEXT,
    spice_level TEXT,
    pov TEXT,
    pacing TEXT,
    top_3_positive TEXT,
    top_3_negative TEXT,
    is_series_strong INTEGER,
    ai_suspicion_mentioned INTEGER,
    raw_json TEXT,
    extracted_at TEXT,
    FOREIGN KEY (story_id) REFERENCES stories(id)
);

CREATE INDEX IF NOT EXISTS idx_stories_platform ON stories(platform);
CREATE INDEX IF NOT EXISTS idx_stories_subniche ON stories(subniche_id);
CREATE INDEX IF NOT EXISTS idx_reviews_story ON reviews(story_id);
"""


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_story(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    data = {k: v for k, v in data.items() if v is not None and k != "id"}
    data.setdefault("scraped_at", _utc_now())
    cols = list(data.keys())
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("platform", "external_id"))
    sql = f"""
        INSERT INTO stories ({col_names}) VALUES ({placeholders})
        ON CONFLICT(platform, external_id) DO UPDATE SET {updates}
    """
    conn.execute(sql, [data[c] for c in cols])
    row = conn.execute(
        "SELECT id FROM stories WHERE platform=? AND external_id=?",
        (data["platform"], data["external_id"]),
    ).fetchone()
    return int(row["id"])


def link_story_subniche(
    conn: sqlite3.Connection, story_id: int, subniche_id: int, rank: int
) -> None:
    conn.execute(
        """
        INSERT INTO story_subniches (story_id, subniche_id, rank_in_search)
        VALUES (?, ?, ?)
        ON CONFLICT(story_id, subniche_id) DO UPDATE SET rank_in_search=excluded.rank_in_search
        """,
        (story_id, subniche_id, rank),
    )


def insert_reviews(conn: sqlite3.Connection, story_id: int, platform: str, reviews: list[dict]) -> None:
    conn.execute("DELETE FROM reviews WHERE story_id=?", (story_id,))
    now = _utc_now()
    for r in reviews:
        conn.execute(
            """
            INSERT INTO reviews (story_id, platform, reviewer, rating, title, body, review_date, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                platform,
                r.get("reviewer"),
                r.get("rating"),
                r.get("title"),
                r.get("body"),
                r.get("review_date"),
                now,
            ),
        )


def upsert_author(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    data.setdefault("scraped_at", _utc_now())
    cols = list(data.keys())
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("platform", "external_id"))
    sql = f"""
        INSERT INTO authors ({col_names}) VALUES ({placeholders})
        ON CONFLICT(platform, external_id) DO UPDATE SET {updates}
    """
    conn.execute(sql, [data[c] for c in cols])
    row = conn.execute(
        "SELECT id FROM authors WHERE platform=? AND external_id=?",
        (data["platform"], data["external_id"]),
    ).fetchone()
    return int(row["id"])


def upsert_tropes(conn: sqlite3.Connection, story_id: int, tropes: dict[str, Any]) -> None:
    def j(v: Any) -> str | None:
        if v is None:
            return None
        return json.dumps(v) if not isinstance(v, str) else v

    conn.execute(
        """
        INSERT INTO trope_extractions (
            story_id, top_3_tropes, spice_level, pov, pacing,
            top_3_positive, top_3_negative, is_series_strong,
            ai_suspicion_mentioned, raw_json, extracted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(story_id) DO UPDATE SET
            top_3_tropes=excluded.top_3_tropes,
            spice_level=excluded.spice_level,
            pov=excluded.pov,
            pacing=excluded.pacing,
            top_3_positive=excluded.top_3_positive,
            top_3_negative=excluded.top_3_negative,
            is_series_strong=excluded.is_series_strong,
            ai_suspicion_mentioned=excluded.ai_suspicion_mentioned,
            raw_json=excluded.raw_json,
            extracted_at=excluded.extracted_at
        """,
        (
            story_id,
            j(tropes.get("top_3_tropes")),
            tropes.get("spice_level"),
            tropes.get("pov"),
            tropes.get("pacing"),
            j(tropes.get("top_3_positive")),
            j(tropes.get("top_3_negative")),
            int(bool(tropes.get("is_series_strong"))),
            int(bool(tropes.get("ai_suspicion_mentioned"))),
            json.dumps(tropes),
            _utc_now(),
        ),
    )


def patch_story(conn: sqlite3.Connection, platform: str, external_id: str, data: dict[str, Any]) -> int:
    """Merge detail fields onto an existing search row without clobbering discovery metadata."""
    payload = {
        k: v
        for k, v in data.items()
        if v is not None and k not in ("id", "platform", "external_id", "subniche_id", "search_keyword", "rank_in_search")
    }
    payload["platform"] = platform
    payload["external_id"] = external_id
    payload["scraped_at"] = _utc_now()
    return upsert_story(conn, payload)


def get_stories_for_platform(conn: sqlite3.Connection, platform: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM stories WHERE platform=? ORDER BY subniche_id, rank_in_search",
        (platform,),
    ).fetchall()


def get_all_stories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM stories ORDER BY platform, subniche_id").fetchall()
