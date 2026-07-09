"""Shared fixtures for factory zone tests — not a test module."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

SAMPLE_LEDGER = {
    "canonical_reveal_chapter": 42,
    "major_reveals": [
        {
            "id": "R001",
            "reveal": "Adrian monitored her work for months",
            "chapter": 8,
            "reveal_weight": "major",
            "required_clues": ["C002", "C005"],
        },
        {
            "id": "R002",
            "reveal": "Small beat reveal",
            "chapter": 15,
            "reveal_weight": "minor",
            "required_clues": ["C008"],
        },
    ],
    "clues": [
        {
            "id": "C001",
            "content": "Thick contract rushed through signing",
            "plant_chapter": 1,
            "payoff_chapter": 47,
            "type": "object",
        },
        {
            "id": "C002",
            "content": "Adrian mentions her article from six months ago",
            "plant_chapter": 3,
            "payoff_chapter": 8,
            "type": "dialogue",
        },
        {
            "id": "C005",
            "content": "Adrian asks about mother's hospital",
            "plant_chapter": 7,
            "payoff_chapter": 8,
            "type": "dialogue",
        },
        {
            "id": "C008",
            "content": "Billing code mismatch in records",
            "plant_chapter": 12,
            "payoff_chapter": 15,
            "type": "document",
        },
    ],
    "red_herrings": [
        {
            "id": "RH001",
            "false_lead": "Random convenience marriage",
            "plant_chapters": [1, 3],
            "dispelled_chapter": 42,
        },
    ],
}

SAMPLE_MATRIX = {
    "milestones": [1, 10, 25, 36, 50],
    "characters": {
        "Lin Wei": {
            "ch1": "Knows: She needs money for treatment. Does not know: Glass Meridian exists.",
            "ch10": "Knows: Adrian has secrets. Does not know: She was chosen deliberately.",
            "must_not_know_before": {
                "Adrian chose her because of mother's file": 42,
                "Glass Meridian exists": 36,
            },
        },
        "Adrian Vale": {
            "ch1": "Knows: Full truth about Phoenix. Does not know: Whether she will forgive him.",
        },
    },
}

SAMPLE_THREADS = {
    "threads": [
        {"id": "T001", "opened_chapter": 1, "must_close_by": 50},
        {"id": "T004", "opened_chapter": 1, "must_close_by": 42},
        {"id": "T099", "opened_chapter": 40, "must_close_by": 50},
    ],
}

SAMPLE_PLAN = {
    "chapter": 1,
    "title": "Test",
    "slug": "test",
    "one_line_summary": "Summary",
    "beat_summary": "Beat",
    "must_happen": [
        "[ROMANCE] A charged glance.",
        "Mother surgery deadline stated.",
        "Contract signed.",
    ],
    "must_not": ["Reveal Glass Meridian", "Adrian explains why he chose her"],
    "opens_with": '"Forty pages," she said.',
    "cliffhanger": "The pen leaves ink on clause twelve.",
    "signature_detail_hint": "odd detail",
    "emotional_beat": "tension",
    "spice": 1,
    "chapter_task": "Write 1600-1900 words.",
    "carries_to_next": "next",
}


def write_test_workspace(
    root: Path,
    *,
    workspace_id: str = "test-thriller",
    narrative_status: str = "approved",
    profile: str = "romance_thriller",
) -> Path:
    ws = root / workspace_id
    nd = ws / "bible" / "narrative"
    nd.mkdir(parents=True, exist_ok=True)
    (nd / "mystery_ledger.json").write_text(json.dumps(SAMPLE_LEDGER, indent=2), encoding="utf-8")
    (nd / "knowledge_matrix.json").write_text(json.dumps(SAMPLE_MATRIX, indent=2), encoding="utf-8")
    (nd / "threads.json").write_text(json.dumps(SAMPLE_THREADS, indent=2), encoding="utf-8")
    direction = {
        "id": workspace_id,
        "narrative_profile": profile,
        "narrative_status": narrative_status,
        "total_chapters": 50,
        "target_language": "en",
    }
    (ws / "direction.yaml").write_text(yaml.dump(direction, allow_unicode=True), encoding="utf-8")
    return ws


def full_plan(ch: int, **extra) -> dict:
    p = dict(SAMPLE_PLAN)
    p["chapter"] = ch
    p["title"] = f"Chapter {ch}"
    p["slug"] = f"ch-{ch}"
    p.update(extra)
    return p
