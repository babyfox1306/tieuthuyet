"""Chapter-safe projection for ETL threshold arcs and structured settings."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Iterable


THRESHOLD_LIST_FIELDS = (
    "resistance",
    "body_response",
    "immediate_aftermath",
    "downstream_change",
)
THRESHOLD_TEXT_FIELDS = (
    "event_type",
    "hesitation",
    "confidence_shift",
    "control_shift",
    "psychological_cost",
)
SETTING_LIST_FIELDS = (
    "locations",
    "access_control",
    "sightlines",
    "soundpaths",
    "opportunities",
    "locked_fact_ids",
)

_CROSS_LAYER_STOPWORDS = frozenset(
    {
        "that",
        "with",
        "from",
        "this",
        "into",
        "only",
        "before",
        "after",
        "chapter",
        "evidence",
        "system",
        "data",
        "original",
        "plan",
        "creating",
        "created",
    }
)


def _semantic_words(value: Any) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-zÀ-ỹ']{3,}", str(value or "").casefold())
        if word not in _CROSS_LAYER_STOPWORDS
    }


def _semantic_bigrams(value: Any) -> set[tuple[str, str]]:
    words = [
        word
        for word in re.findall(r"[a-zÀ-ỹ']{3,}", str(value or "").casefold())
        if word not in _CROSS_LAYER_STOPWORDS
    ]
    return set(zip(words, words[1:]))


def _substantial_semantic_overlap(candidate: Any, protected: Any) -> bool:
    """Conservative overlap used only for cross-layer future-fact validation."""
    left = _semantic_words(candidate)
    right = _semantic_words(protected)
    if len(left) < 2 or len(right) < 2:
        return False
    shared = left & right
    return (
        bool(_semantic_bigrams(candidate) & _semantic_bigrams(protected))
        or (
            len(shared) >= 2
            and len(shared) / min(len(left), len(right)) >= 0.60
        )
    )


def _within_allowed_foreshadow(candidate: Any, allowed: Any) -> bool:
    """True only when candidate stays inside the reveal's explicit safe wording."""
    candidate_words = _semantic_words(candidate)
    allowed_words = _semantic_words(allowed)
    return bool(candidate_words) and candidate_words <= allowed_words


def _story_context_timing_errors(concept: dict[str, Any]) -> list[str]:
    """Catch advanced fields that bypass the chapter reveal/clue schedule."""
    errors: list[str] = []
    clues = [
        clue
        for clue in concept.get("clues") or []
        if isinstance(clue, dict) and clue.get("id")
    ]
    reveal_rows = concept.get("reveal_schedule") or concept.get(
        "required_reveal_schedule"
    ) or []
    reveals = {
        str(row.get("id") or row.get("ref") or ""): row
        for row in reveal_rows
        if isinstance(row, dict) and (row.get("id") or row.get("ref"))
    }

    # A plant interpretation must not duplicate the semantic of a different
    # clue that is not scheduled to appear until a later chapter.
    for index, clue in enumerate(clues):
        plant_chapter = int(clue.get("plant_chapter") or 0)
        surface = str(clue.get("interpretation_at_plant") or "").strip()
        if plant_chapter <= 0 or not surface:
            continue
        for future in clues:
            future_id = str(future.get("id") or "")
            if future_id == str(clue.get("id") or ""):
                continue
            future_plant = int(future.get("plant_chapter") or 0)
            if future_plant <= plant_chapter:
                continue
            protected = str(
                future.get("description")
                or future.get("content")
                or future.get("interpretation_at_plant")
                or ""
            )
            if _substantial_semantic_overlap(surface, protected):
                errors.append(
                    f"clues[{index}].interpretation_at_plant: leaks later clue "
                    f"{future_id} scheduled ch{future_plant}"
                )

    # Threshold prose reaches Outliner/Writer as binding chapter content.  It
    # may express psychology, but it cannot name a clue's future payoff object
    # or true meaning before that payoff chapter.
    for index, event in enumerate(concept.get("threshold_events") or []):
        if not isinstance(event, dict):
            continue
        chapter = int(event.get("chapter") or 0)
        if chapter <= 0:
            continue
        event_parts: list[str] = []
        for key in (
            *THRESHOLD_LIST_FIELDS,
            *THRESHOLD_TEXT_FIELDS,
        ):
            value = event.get(key)
            if isinstance(value, list):
                event_parts.extend(str(item) for item in value)
            elif value:
                event_parts.append(str(value))
        for clue in clues:
            payoff = int(clue.get("payoff_chapter") or 0)
            if payoff <= chapter:
                continue
            owner = reveals.get(str(clue.get("owner_reveal") or "")) or {}
            allowed = owner.get("allowed_foreshadowing_before")
            protected_values = (
                clue.get("description"),
                clue.get("content"),
                clue.get("true_meaning_at_payoff"),
                clue.get("true_meaning"),
            )
            leaking_parts = [
                part
                for part in event_parts
                if any(
                    _substantial_semantic_overlap(part, protected)
                    for protected in protected_values
                    if protected
                )
                and not _within_allowed_foreshadow(part, allowed)
            ]
            if leaking_parts:
                errors.append(
                    f"threshold_events[{index}]: names future clue "
                    f"{clue.get('id')} payoff scheduled ch{payoff}"
                )
                break
    return errors


def story_context_errors(concept: dict[str, Any]) -> list[str]:
    """Validate only the structural contract SF consumes; never invent defaults."""
    errors: list[str] = []
    thresholds = concept.get("threshold_events")
    if thresholds is not None:
        if not isinstance(thresholds, list):
            errors.append("threshold_events: must be a list")
        else:
            seen_ordinals: set[int] = set()
            for index, event in enumerate(thresholds):
                path = f"threshold_events[{index}]"
                if not isinstance(event, dict):
                    errors.append(f"{path}: must be a map")
                    continue
                for key in ("ordinal", "chapter"):
                    value = event.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        errors.append(f"{path}.{key}: must be a positive integer")
                ordinal = event.get("ordinal")
                if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                    if ordinal in seen_ordinals:
                        errors.append(f"{path}.ordinal: duplicate {ordinal}")
                    seen_ordinals.add(ordinal)
                for key in THRESHOLD_LIST_FIELDS:
                    value = event.get(key)
                    if not isinstance(value, list) or any(
                        not isinstance(item, str) for item in value
                    ):
                        errors.append(f"{path}.{key}: must be a list of strings")
                for key in THRESHOLD_TEXT_FIELDS:
                    if not isinstance(event.get(key), str) or not event.get(key, "").strip():
                        errors.append(f"{path}.{key}: must be a non-empty string")

    arc = concept.get("arc_shape")
    if arc is not None:
        if not isinstance(arc, dict):
            errors.append("arc_shape: must be a map")
        else:
            for key in ("type", "source"):
                if not isinstance(arc.get(key), str) or not arc.get(key, "").strip():
                    errors.append(f"arc_shape.{key}: must be a non-empty string")
            if type(arc.get("monotonic")) is not bool:
                errors.append("arc_shape.monotonic: must be bool")

    graph = concept.get("setting_graph")
    if graph is not None:
        if not isinstance(graph, dict):
            errors.append("setting_graph: must be a map")
        else:
            if not isinstance(graph.get("estate_name"), str):
                errors.append("setting_graph.estate_name: must be a string")
            for key in SETTING_LIST_FIELDS:
                if not isinstance(graph.get(key), list):
                    errors.append(f"setting_graph.{key}: must be a list")
            id_fields = {
                "locations": "id",
                "access_control": "mechanism_id",
                "sightlines": "id",
                "soundpaths": "id",
                "opportunities": "id",
            }
            indexes: dict[str, set[str]] = {}
            for key, id_field in id_fields.items():
                seen: set[str] = set()
                for index, row in enumerate(graph.get(key) or []):
                    path = f"setting_graph.{key}[{index}]"
                    if not isinstance(row, dict):
                        errors.append(f"{path}: must be a map")
                        continue
                    value = row.get(id_field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{path}.{id_field}: must be a non-empty string")
                        continue
                    if value in seen:
                        errors.append(f"{path}.{id_field}: duplicate {value!r}")
                    seen.add(value)
                indexes[key] = seen
            mechanisms = indexes.get("access_control", set())
            setting_enablers = (
                mechanisms
                | indexes.get("sightlines", set())
                | indexes.get("soundpaths", set())
            )
            locations = indexes.get("locations", set())
            for index, row in enumerate(graph.get("opportunities") or []):
                if not isinstance(row, dict):
                    continue
                for mechanism in row.get("enabled_by") or []:
                    if mechanism not in setting_enablers:
                        errors.append(
                            f"setting_graph.opportunities[{index}].enabled_by: "
                            f"unknown setting enabler {mechanism!r}"
                        )
            for index, row in enumerate(graph.get("access_control") or []):
                if not isinstance(row, dict):
                    continue
                for location in row.get("applies_to_location_ids") or []:
                    if location not in locations:
                        errors.append(
                            f"setting_graph.access_control[{index}]."
                            f"applies_to_location_ids: unknown location {location!r}"
                        )
    if not errors:
        errors.extend(_story_context_timing_errors(concept))
    return errors


def copy_story_context(concept: dict[str, Any]) -> dict[str, Any]:
    """Copy the ETL-owned structures without normalization or generated content."""
    return {
        key: deepcopy(concept.get(key))
        for key in ("threshold_events", "arc_shape", "setting_graph")
        if concept.get(key) is not None
    }


def _chapter_text(chapter_entry: dict[str, Any]) -> str:
    return json.dumps(chapter_entry, ensure_ascii=False, default=str)


def _ids_from_text(text: str, prefix: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(
            rf"\b{re.escape(prefix)}\s*:\s*([A-Za-z0-9_-]+)",
            text,
            flags=re.IGNORECASE,
        )
    }


def project_story_context(
    source: dict[str, Any],
    chapter: int,
    chapter_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only the threshold event and setting mechanisms active in a chapter."""
    out: dict[str, Any] = {}
    raw_thresholds = source.get("threshold_events")
    thresholds = [
        deepcopy(event)
        for event in raw_thresholds or []
        if isinstance(event, dict) and int(event.get("chapter") or 0) == chapter
    ]
    if isinstance(raw_thresholds, list):
        # Empty is meaningful: it prevents Outliner from turning a generic
        # psychology stress response into an unscheduled threshold escalation.
        out["threshold_events"] = thresholds
        out["threshold_instruction"] = (
            "Execute only the threshold_events listed for this chapter. "
            "An empty list means no threshold event: do not move, borrow, "
            "number, or invent a threshold/body-response stage here."
        )
    if source.get("arc_shape") is not None:
        out["arc_shape"] = deepcopy(source["arc_shape"])

    graph = source.get("setting_graph")
    if not isinstance(graph, dict):
        return out
    entry_text = _chapter_text(chapter_entry or {})
    opportunity_ids = _ids_from_text(entry_text, "setting_opportunity_ref")
    opportunity_ids.update(
        str(row.get("id") or "")
        for row in graph.get("opportunities") or []
        if isinstance(row, dict)
        and chapter in [int(value) for value in row.get("exploited_in_chapters") or []]
    )
    mechanism_ids = set(
        re.findall(r"\bmechanism_[A-Za-z0-9_-]+\b", entry_text)
    )
    opportunities = [
        deepcopy(row)
        for row in graph.get("opportunities") or []
        if isinstance(row, dict) and str(row.get("id") or "") in opportunity_ids
    ]
    for row in opportunities:
        mechanism_ids.update(str(value) for value in row.get("enabled_by") or [])
    sightline_ids = {
        str(row.get("id") or "")
        for row in graph.get("sightlines") or []
        if isinstance(row, dict)
        and str(row.get("id") or "") in mechanism_ids
    }
    soundpath_ids = {
        str(row.get("id") or "")
        for row in graph.get("soundpaths") or []
        if isinstance(row, dict)
        and str(row.get("id") or "") in mechanism_ids
    }
    mechanisms = [
        {
            key: deepcopy(value)
            for key, value in row.items()
            if key != "can_be_bypassed_by"
        }
        | {
            "can_be_bypassed_by": [
                value
                for value in row.get("can_be_bypassed_by") or []
                if value in mechanism_ids
            ]
        }
        for row in graph.get("access_control") or []
        if isinstance(row, dict)
        and str(row.get("mechanism_id") or "") in mechanism_ids
    ]
    location_ids = {
        str(value)
        for row in mechanisms
        for value in row.get("applies_to_location_ids") or []
    }
    locations = [
        {
            key: deepcopy(value)
            for key, value in row.items()
            if key
            in {
                "id",
                "name",
                "type",
                "normal_function",
                "adjacent_to",
                "floor",
                "derivation",
            }
        }
        | {
            "access_controlled_by": [
                value
                for value in row.get("access_controlled_by") or []
                if value in mechanism_ids
            ]
        }
        for row in graph.get("locations") or []
        if isinstance(row, dict) and str(row.get("id") or "") in location_ids
    ]
    setting = {
        "estate_name": graph.get("estate_name"),
        "locations": locations,
        "access_control": mechanisms,
        "sightlines": [
            deepcopy(row)
            for row in graph.get("sightlines") or []
            if isinstance(row, dict) and str(row.get("id") or "") in sightline_ids
        ],
        "soundpaths": [
            deepcopy(row)
            for row in graph.get("soundpaths") or []
            if isinstance(row, dict) and str(row.get("id") or "") in soundpath_ids
        ],
        "opportunities": opportunities,
    }
    if any(
        setting[key]
        for key in ("locations", "access_control", "sightlines", "soundpaths", "opportunities")
    ):
        out["setting_graph"] = setting
    return out


def project_story_context_range(
    source: dict[str, Any],
    chapters: Iterable[int],
    chapter_entries: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        str(chapter): projected
        for chapter in chapters
        if (
            projected := project_story_context(
                source,
                chapter,
                chapter_entries.get(chapter) or {},
            )
        )
    }
