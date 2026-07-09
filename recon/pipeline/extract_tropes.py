"""Send review batches to 9router for trope/spice extraction."""

import json
import re

from openai import OpenAI

from recon.config import NINEROUTER_BASE_URL, NINEROUTER_MODEL
from recon.core import db

PROMPT_TEMPLATE = """You are analyzing up to 20 reader reviews of a single fiction book/story.

Extract and output JSON ONLY (no preamble):

{{
  "top_3_tropes": [],
  "spice_level": "clean" | "sweet" | "steamy" | "explicit" | "very_explicit",
  "pov": "first_person" | "third_person" | "dual" | "multiple",
  "pacing": "slow_burn" | "moderate" | "fast",
  "top_3_positive": [],
  "top_3_negative": [],
  "is_series_strong": boolean,
  "ai_suspicion_mentioned": boolean
}}

Reviews:
{reviews}
"""


def _format_reviews(reviews: list) -> str:
    parts = []
    for i, r in enumerate(reviews[:20], 1):
        body = r["body"] if isinstance(r, dict) else r["body"]
        rating = r["rating"] if isinstance(r, dict) else None
        parts.append(f"--- Review {i} (rating={rating}) ---\n{body}")
    return "\n\n".join(parts)


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(text)


def extract_for_story(story_id: int, reviews: list, client: OpenAI | None = None) -> dict | None:
    if not reviews:
        return None
    client = client or OpenAI(base_url=NINEROUTER_BASE_URL, api_key="local")
    prompt = PROMPT_TEMPLATE.format(reviews=_format_reviews(reviews))
    try:
        resp = client.chat.completions.create(
            model=NINEROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        return _parse_json_response(content)
    except Exception as exc:
        print(f"[extract_tropes] story_id={story_id} failed: {exc}")
        return None


def run_all() -> int:
    """Extract tropes for all stories that have reviews but no extraction yet."""
    count = 0
    client = None
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.platform, s.title
            FROM stories s
            LEFT JOIN trope_extractions t ON t.story_id = s.id
            WHERE t.id IS NULL
            """
        ).fetchall()
        for row in rows:
            reviews = conn.execute(
                "SELECT body, rating FROM reviews WHERE story_id=? LIMIT 20",
                (row["id"],),
            ).fetchall()
            if not reviews:
                continue
            if client is None:
                try:
                    client = OpenAI(base_url=NINEROUTER_BASE_URL, api_key="local")
                except Exception:
                    print("[extract_tropes] 9router unavailable — skipping LLM extraction")
                    return count
            tropes = extract_for_story(row["id"], reviews, client)
            if tropes:
                db.upsert_tropes(conn, row["id"], tropes)
                count += 1
    return count
