"""Architect bible generation with validate-and-retry."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.lib.bible_schema import validate_bible
from factory.engine.lib.call_9router import call_9router, parse_json_response
from factory.engine.lib.narrative_schema import load_concept, narrative_dir
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import bible_path, load_config

_LEAK_IDENTITY_RE = re.compile(
    r"\bis the leak\b|"
    r"\bthe leak who\b|"
    r"\bbetrays?\b|"
    r"\bbetrayal\b|"
    r"\bmole\b|"
    r"\binformer\b",
    re.I,
)
_NAMED_BETRAY_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b.{0,40}\bbetrays?\b|"
    r"\bbetrays?\b.{0,40}\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b|"
    r"\bwhen\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+betrays?\b",
)


def concept_defers_leak_identity(concept: dict[str, Any]) -> bool:
    """True when concept leaves leak/betrayer identity to plan time."""
    blob = "\n".join(
        [
            str(concept.get("author_directive") or ""),
            str(concept.get("notes") or ""),
            "\n".join(str(x) for x in (concept.get("must_include") or [])),
        ]
    )
    return bool(
        re.search(
            r"decide\s+which.{0,80}plan|"
            r"decide.{0,40}at\s+plan\s*time|"
            r"leak.{0,120}decide\s+which|"
            r"THE LEAK:.{0,200}decide",
            blob,
            re.I | re.DOTALL,
        )
    )


def scrub_premature_leak_lock(bible: dict[str, Any], concept: dict[str, Any]) -> list[str]:
    """Strip named leak locks when concept deferred the choice to plan.

    Returns list of scrub notes for logging. Mutates bible in place.
    """
    if not concept_defers_leak_identity(concept):
        return []
    notes: list[str] = []
    cast = bible.get("supporting_cast")
    if isinstance(cast, list):
        for row in cast:
            if not isinstance(row, dict):
                continue
            secret = str(row.get("secret") or "")
            if not _LEAK_IDENTITY_RE.search(secret):
                continue
            name = str(row.get("name") or "cast")
            # Keep technical role; drop betrayal lock.
            cleaned = re.split(
                r"[.;]\s*(?:is the leak|betrays?|the leak who)\b",
                secret,
                maxsplit=1,
                flags=re.I,
            )[0].strip(" ;,")
            if not cleaned or _LEAK_IDENTITY_RE.search(cleaned):
                cleaned = "Network member with a sensitive operational role — loyalty unresolved until plan."
            row["secret"] = cleaned
            notes.append(f"scrubbed leak lock from {name}.secret")

    arcs = bible.get("series_arc")
    if isinstance(arcs, list):
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            for key in ("thesis", "ending_hook"):
                text = str(arc.get(key) or "")
                if not text or not _NAMED_BETRAY_RE.search(text):
                    continue
                arc[key] = _NAMED_BETRAY_RE.sub(
                    "a network member betrays",
                    text,
                )
                # Normalize awkward doubles
                arc[key] = re.sub(
                    r"a network member betrays\s+her",
                    "a network member betrays her",
                    str(arc[key]),
                    flags=re.I,
                )
                notes.append(f"scrubbed named betrayer from series_arc.{key}")

    cm = bible.get("central_mystery")
    if isinstance(cm, dict):
        for key in ("question", "answer"):
            text = str(cm.get(key) or "")
            if _NAMED_BETRAY_RE.search(text):
                cm[key] = _NAMED_BETRAY_RE.sub("a network member betrays", text)
                notes.append(f"scrubbed named betrayer from central_mystery.{key}")
    return notes


def _save_bible(ws: Path, bible: dict[str, Any]) -> None:
    path = bible_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bible, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_mystery_ledger(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "mystery_ledger.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def seed_central_mystery_from_ledger(bible: dict[str, Any], ledger: dict[str, Any]) -> bool:
    """Align derived central_mystery with the canonical narrative ledger."""
    if not ledger:
        return False
    question = (ledger.get("main_mystery") or "").strip()
    answer = (ledger.get("truth") or "").strip()
    reveal = ledger.get("canonical_reveal_chapter")
    if not question or not answer:
        return False
    canonical = {
        "question": question,
        "answer": answer,
        "reveal_chapter": int(reveal) if reveal is not None else 1,
    }
    changed = bible.get("central_mystery") != canonical
    bible["central_mystery"] = canonical
    return changed


def lock_bible_lead_names(
    bible: dict[str, Any],
    locked_leads: dict[str, str],
) -> bool:
    """Force Architect output to retain positive concept-declared lead names."""
    if not isinstance(locked_leads, dict):
        return False
    leads = bible.setdefault("leads", {})
    if not isinstance(leads, dict):
        leads = {}
        bible["leads"] = leads

    changed = False
    for side in ("female", "male"):
        canonical = str(locked_leads.get(side) or "").strip()
        if not canonical:
            continue
        block = leads.setdefault(side, {})
        if not isinstance(block, dict):
            block = {}
            leads[side] = block
        if str(block.get("name") or "").strip() != canonical:
            block["name"] = canonical
            changed = True
    return changed


def build_architect_payload(ws: Path, *, cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    direction = load_direction(ws)
    concept = load_concept(ws)
    ledger = _load_mystery_ledger(ws)
    from factory.engine.lib.canon_registry import concept_lead_names

    female_lead, male_lead = concept_lead_names(concept)
    locked_leads = {
        side: name
        for side, name in (("female", female_lead), ("male", male_lead))
        if name
    }
    payload: dict[str, Any] = {
        "genre": direction.get("narrative_profile") or "fiction",
        "sub_niche": direction.get("narrative_profile") or concept.get("title") or "series",
        "spice_level": int(direction.get("spice_level") or cfg.get("spice_level") or 1),
        "planned_books": 5,
        "target_language": direction.get("target_language")
        or concept.get("target_language")
        or "en",
        "total_chapters": int(direction.get("total_chapters") or 0) or None,
        "concept_title": concept.get("title"),
        "concept_logline": concept.get("logline"),
        "author_directive": (concept.get("author_directive") or "")[:4000],
        "ending_book1": concept.get("ending_book1"),
        "must_include": concept.get("must_include") or [],
        "must_avoid": concept.get("must_avoid") or [],
        "concept_pov": concept.get("pov") or {},
        "concept_characters": concept.get("characters") or [],
        "locked_lead_names": locked_leads,
    }
    if ledger:
        payload["mystery_ledger"] = {
            "main_mystery": ledger.get("main_mystery"),
            "truth": ledger.get("truth"),
            "canonical_reveal_chapter": ledger.get("canonical_reveal_chapter"),
        }
        payload["instruction"] = (
            "central_mystery MUST match mystery_ledger "
            "(question=main_mystery, answer=truth, reveal_chapter=canonical_reveal_chapter). "
            "Output COMPLETE JSON including central_mystery + bloodline + series_arc."
        )
    return payload


def generate_bible_with_retry(
    ws: Path,
    *,
    max_attempts: int | None = None,
    max_tokens: int = 12288,
) -> dict[str, Any]:
    """Call architect, validate, retry with error feedback until schema passes or attempts exhausted."""
    cfg = load_config()
    if max_attempts is None:
        max_attempts = int(cfg.get("architect_validate_retries", 3))
    max_attempts = max(1, max_attempts)

    direction = load_direction(ws)
    ledger = _load_mystery_ledger(ws)
    base_payload = build_architect_payload(ws, cfg=cfg)

    last_errors: list[str] = []
    last_bible: dict[str, Any] = {}
    attempts_log: list[dict[str, Any]] = []

    for attempt in range(1, max_attempts + 1):
        payload = dict(base_payload)
        if last_errors:
            payload["previous_validation_errors"] = last_errors
            payload["retry_instruction"] = (
                "Previous bible FAILED validate-bible. Fix ALL listed errors. "
                "Return a COMPLETE series.json — especially central_mystery "
                "{question, answer, reveal_chapter}, bloodline, series_arc."
            )
            # Keep a compact hint of what was missing, not the whole truncated dump
            if last_bible:
                payload["previous_keys_present"] = sorted(last_bible.keys())

        raw, log = call_9router(
            "architect",
            json.dumps(payload, ensure_ascii=False),
            max_tokens=max_tokens,
            direction=direction,
        )
        bible = parse_json_response(raw)
        if not isinstance(bible, dict):
            last_errors = ["architect:response_not_object"]
            attempts_log.append(
                {"attempt": attempt, "errors": last_errors, "usage": log.get("usage")}
            )
            continue

        seeded = seed_central_mystery_from_ledger(bible, ledger)
        names_locked = lock_bible_lead_names(
            bible,
            base_payload.get("locked_lead_names") or {},
        )
        concept = load_concept(ws)
        scrub_notes = scrub_premature_leak_lock(bible, concept)
        # Align genre labels with direction when concept forbids romance.
        profile = str(direction.get("narrative_profile") or "").strip()
        if profile and "romance" not in profile.lower():
            meta = bible.get("meta") if isinstance(bible.get("meta"), dict) else {}
            if str(meta.get("genre") or "").lower().find("romance") >= 0:
                meta["genre"] = profile
                bible["meta"] = meta
            if "romance" in str(bible.get("sub_niche") or "").lower():
                bible["sub_niche"] = profile
        bible["bible_status"] = "draft"
        last_bible = bible
        errors = validate_bible(bible, concept=concept)
        attempts_log.append(
            {
                "attempt": attempt,
                "errors": list(errors),
                "seeded_central_mystery": seeded,
                "locked_lead_names": names_locked,
                "scrub_notes": scrub_notes,
                "usage": log.get("usage"),
            }
        )
        if not errors:
            _save_bible(ws, bible)
            return {
                "ok": True,
                "bible": bible,
                "attempts": attempt,
                "attempts_log": attempts_log,
                "errors": [],
            }

        last_errors = errors

    # Persist best effort so operator can inspect
    if last_bible:
        _save_bible(ws, last_bible)

    return {
        "ok": False,
        "bible": last_bible,
        "attempts": max_attempts,
        "attempts_log": attempts_log,
        "errors": last_errors,
    }
