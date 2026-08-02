"""First-class, reveal-safe character psychology contract.

Character identity is the exact canonical ``concept.characters[].name``.  Stable
cast IDs do not exist yet; introducing them is a separate migration.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Iterable


PSYCHOLOGY_LIST_FIELDS = (
    "core_traits",
    "stress_responses",
    "behavioral_constraints",
)
PSYCHOLOGY_TEXT_FIELDS = (
    "core_need",
    "core_fear",
    "coping_mechanism",
    "cognitive_dissonance",
)
PSYCHOLOGY_FIELDS = (
    "character",
    *PSYCHOLOGY_LIST_FIELDS,
    *PSYCHOLOGY_TEXT_FIELDS,
    "reveal_gated_fields",
)
GATED_FIELDS = (
    "field",
    "value",
    "unlock_reveal_id",
    "reveal_chapter",
)
_UNGATED_SECRET_RE = re.compile(
    r"\b(?:hidden[\s_-]+mastermind|secretly|secret[\s_-]+mastermind|"
    r"true[\s_-]+(?:goal|objective|motive)|"
    r"(?:hired|commissioned).{0,40}(?:kill|murder))\b",
    re.IGNORECASE,
)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return "map"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _cast_names(concept: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for row in concept.get("characters") or []:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                out.append(name)
    return out


def _schedule_by_ref(
    reveal_schedule: Iterable[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in reveal_schedule or []:
        if not isinstance(row, dict):
            continue
        for key in ("ref", "id"):
            token = str(row.get(key) or "").strip()
            if token:
                out[token] = row
    return out


def _reveal_row_chapter(row: dict[str, Any]) -> int:
    for key in ("chapter", "reader_reveal_chapter", "pov_knows_chapter"):
        try:
            ch = int(row.get(key) or 0)
        except (TypeError, ValueError):
            ch = 0
        if ch > 0:
            return ch
    return 0


def psychology_entry_meaningful(entry: dict[str, Any]) -> bool:
    for field in PSYCHOLOGY_LIST_FIELDS:
        if any(str(item).strip() for item in (entry.get(field) or [])):
            return True
    for field in PSYCHOLOGY_TEXT_FIELDS:
        if str(entry.get(field) or "").strip():
            return True
    for row in entry.get("reveal_gated_fields") or []:
        if isinstance(row, dict) and str(row.get("value") or "").strip():
            return True
    return False


def character_psychology_errors(
    concept: dict[str, Any],
    *,
    reveal_schedule: Iterable[dict[str, Any]] | None = None,
    require_meaningful: bool = False,
) -> list[str]:
    raw = concept.get("character_psychology")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [
            "character_psychology: must be a list, "
            f"received {_type_name(raw)}"
        ]

    errors: list[str] = []
    cast = _cast_names(concept)
    cast_set = set(cast)
    schedule = _schedule_by_ref(reveal_schedule)
    has_future_reveal = any(
        _reveal_row_chapter(row) > 1 for row in schedule.values()
    )
    seen: set[str] = set()

    # ``characters[].role`` is an always-visible identity field in SF. Secrets
    # belong in reveal-gated psychology or the reveal schedule, never here.
    if has_future_reveal:
        for index, character in enumerate(concept.get("characters") or []):
            if not isinstance(character, dict):
                continue
            role = str(character.get("role") or "")
            if _UNGATED_SECRET_RE.search(role):
                errors.append(
                    f"characters[{index}].role: future-reveal secret in "
                    "always-visible field; move the secret to "
                    "character_psychology.reveal_gated_fields"
                )

    for index, entry in enumerate(raw):
        path = f"character_psychology[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{path}: must be a map")
            continue

        unknown = sorted(str(key) for key in set(entry) - set(PSYCHOLOGY_FIELDS))
        if unknown:
            errors.append(f"{path}: unknown key(s): {', '.join(unknown)}")

        character = entry.get("character")
        if not isinstance(character, str) or not character.strip():
            errors.append(f"{path}.character: must be a non-empty string")
            character_name = ""
        else:
            character_name = character.strip()
            if character != character_name:
                errors.append(
                    f"{path}.character: must exactly match canonical cast name "
                    f"{character_name!r}"
                )
            if character_name not in cast_set:
                errors.append(
                    f"{path}.character: unknown canonical character "
                    f"{character_name!r}; expected one of {cast!r}"
                )
            if character_name in seen:
                errors.append(
                    f"{path}.character: duplicate psychology entry for "
                    f"{character_name!r}"
                )
            seen.add(character_name)

        for field in PSYCHOLOGY_LIST_FIELDS:
            value = entry.get(field, [])
            if not isinstance(value, list):
                errors.append(
                    f"{path}.{field}: must be a list of strings, "
                    f"received {_type_name(value)}"
                )
            elif any(not isinstance(item, str) for item in value):
                errors.append(f"{path}.{field}: every item must be a string")
            elif has_future_reveal:
                for item_index, item in enumerate(value):
                    if _UNGATED_SECRET_RE.search(str(item)):
                        errors.append(
                            f"{path}.{field}[{item_index}]: future-reveal secret "
                            "in always-visible field; use reveal_gated_fields "
                            "with unlock_reveal_id"
                        )

        for field in PSYCHOLOGY_TEXT_FIELDS:
            value = entry.get(field, "")
            if not isinstance(value, str):
                errors.append(
                    f"{path}.{field}: must be a string, received {_type_name(value)}"
                )
            elif has_future_reveal and _UNGATED_SECRET_RE.search(value):
                errors.append(
                    f"{path}.{field}: future-reveal secret in always-visible "
                    "field; use reveal_gated_fields with unlock_reveal_id"
                )

        gated = entry.get("reveal_gated_fields", [])
        if not isinstance(gated, list):
            errors.append(
                f"{path}.reveal_gated_fields: must be a list, "
                f"received {_type_name(gated)}"
            )
            gated = []
        for gate_index, gate in enumerate(gated):
            gate_path = f"{path}.reveal_gated_fields[{gate_index}]"
            if not isinstance(gate, dict):
                errors.append(f"{gate_path}: must be a map")
                continue
            gate_unknown = sorted(
                str(key) for key in set(gate) - set(GATED_FIELDS)
            )
            if gate_unknown:
                errors.append(
                    f"{gate_path}: unknown key(s): {', '.join(gate_unknown)}"
                )
            for field in ("field", "value"):
                if not isinstance(gate.get(field), str) or not str(
                    gate.get(field) or ""
                ).strip():
                    errors.append(f"{gate_path}.{field}: must be a non-empty string")

            unlock = gate.get("unlock_reveal_id")
            chapter = gate.get("reveal_chapter")
            if unlock is not None and (
                not isinstance(unlock, str) or not unlock.strip()
            ):
                errors.append(
                    f"{gate_path}.unlock_reveal_id: must be a non-empty string"
                )
                unlock = None
            if chapter is not None and (
                isinstance(chapter, bool)
                or not isinstance(chapter, int)
                or chapter <= 0
            ):
                errors.append(
                    f"{gate_path}.reveal_chapter: must be a positive integer"
                )
                chapter = None

            if unlock:
                reveal = schedule.get(unlock)
                if reveal is None:
                    errors.append(
                        f"{gate_path}.unlock_reveal_id: unknown reveal ref "
                        f"{unlock!r}"
                    )
                else:
                    try:
                        scheduled_chapter = int(reveal.get("chapter") or 0)
                    except (TypeError, ValueError):
                        scheduled_chapter = 0
                    if scheduled_chapter <= 0:
                        errors.append(
                            f"{gate_path}.unlock_reveal_id: reveal {unlock!r} "
                            "has no valid scheduled chapter"
                        )
                    elif chapter is not None and chapter != scheduled_chapter:
                        errors.append(
                            f"{gate_path}: reveal_chapter {chapter} conflicts with "
                            f"{unlock}.chapter {scheduled_chapter}"
                        )
            elif chapter is None:
                errors.append(
                    f"{gate_path}: require unlock_reveal_id or reveal_chapter"
                )

        if require_meaningful and not psychology_entry_meaningful(entry):
            label = character_name or f"entry {index}"
            errors.append(
                f"{path}: psychology entry for {label!r} has no meaningful field"
            )

    return errors


def copy_character_psychology(concept: dict[str, Any]) -> list[dict[str, Any]]:
    raw = concept.get("character_psychology")
    return deepcopy(raw) if isinstance(raw, list) else []


def resolve_gate_chapter(
    gate: dict[str, Any],
    reveal_schedule: Iterable[dict[str, Any]] | None,
) -> int:
    """Resolve one gate from the compiled reveal schedule.

    ``required_reveal_schedule[].chapter`` remains the sole persisted reveal
    chapter.  ``reveal_chapter`` is only a standalone gate or a consistency
    check when an unlock ref is present.
    """
    unlock = str(gate.get("unlock_reveal_id") or "").strip()
    explicit = gate.get("reveal_chapter")
    if unlock:
        row = _schedule_by_ref(reveal_schedule).get(unlock)
        if row is None:
            raise ValueError(f"unknown psychology unlock reveal ref: {unlock}")
        chapter = _reveal_row_chapter(row)
        if chapter <= 0:
            raise ValueError(f"psychology unlock reveal {unlock} has no chapter")
        if explicit is not None and int(explicit) != chapter:
            raise ValueError(
                f"psychology gate chapter conflict: {unlock}.chapter={chapter}, "
                f"reveal_chapter={explicit}"
            )
        return chapter
    chapter = int(explicit or 0)
    if chapter <= 0:
        raise ValueError("psychology gate requires unlock_reveal_id or reveal_chapter")
    return chapter


def project_character_psychology(
    entries: Iterable[dict[str, Any]] | None,
    reveal_schedule: Iterable[dict[str, Any]] | None,
    chapter: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        entry = deepcopy(raw)
        entry["reveal_gated_fields"] = [
            deepcopy(gate)
            for gate in raw.get("reveal_gated_fields") or []
            if isinstance(gate, dict)
            and chapter >= resolve_gate_chapter(gate, reveal_schedule)
        ]
        out.append(entry)
    return out


def psychology_gate_chapters(
    entries: Iterable[dict[str, Any]] | None,
    reveal_schedule: Iterable[dict[str, Any]] | None,
) -> list[int]:
    chapters = {
        resolve_gate_chapter(gate, reveal_schedule)
        for entry in entries or []
        if isinstance(entry, dict)
        for gate in entry.get("reveal_gated_fields") or []
        if isinstance(gate, dict)
    }
    return sorted(chapters)


def split_ranges_at_psychology_gates(
    ranges: Iterable[tuple[int, int, str]],
    entries: Iterable[dict[str, Any]] | None,
    reveal_schedule: Iterable[dict[str, Any]] | None,
) -> list[tuple[int, int, str]]:
    gates = psychology_gate_chapters(entries, reveal_schedule)
    out: list[tuple[int, int, str]] = []
    for lo, hi, name in ranges:
        cuts = [gate for gate in gates if lo < gate <= hi]
        start = lo
        for gate in cuts:
            out.append((start, gate - 1, f"{name}:pre-psychology-gate"))
            start = gate
        out.append((start, hi, name if start == lo else f"{name}:psychology-gate"))
    return out


def relevant_character_names(
    entries: Iterable[dict[str, Any]] | None,
    plan: dict[str, Any],
    *,
    pov_character: str,
) -> list[str]:
    names = [
        str(entry.get("character") or "")
        for entry in entries or []
        if isinstance(entry, dict) and str(entry.get("character") or "")
    ]
    fields = (
        "title",
        "one_line_summary",
        "beat_summary",
        "must_happen",
        "must_not",
        "opens_with",
        "cliffhanger",
        "signature_detail_hint",
        "chapter_task",
        "carries_to_next",
    )
    blob = json.dumps(
        {field: plan.get(field) for field in fields},
        ensure_ascii=False,
        default=str,
    )
    selected: list[str] = []
    for name in names:
        if name == pov_character or re.search(
            rf"(?<![\w'-]){re.escape(name)}(?![\w'-])",
            blob,
            flags=re.IGNORECASE,
        ):
            selected.append(name)
    if pov_character in names and pov_character not in selected:
        selected.insert(0, pov_character)
    return selected


def render_character_psychology_block(
    entries: Iterable[dict[str, Any]] | None,
    reveal_schedule: Iterable[dict[str, Any]] | None,
    plan: dict[str, Any],
    *,
    chapter: int,
    pov_character: str,
) -> str:
    projected = project_character_psychology(
        entries,
        reveal_schedule,
        chapter,
    )
    selected = set(
        relevant_character_names(
            projected,
            plan,
            pov_character=pov_character,
        )
    )
    if not selected:
        return ""

    labels = {
        "core_traits": "Core traits",
        "core_need": "Core need",
        "core_fear": "Core fear",
        "coping_mechanism": "Coping mechanism",
        "stress_responses": "Stress responses",
        "cognitive_dissonance": "Cognitive dissonance",
        "behavioral_constraints": "Behavioral constraints",
    }
    lines = [
        "## CHARACTER PSYCHOLOGY — BINDING",
        "Subordinate to LOCKED CANON, the chapter plan, knowledge restrictions, "
        "and clue/reveal timing. Psychology shapes reactions; it does not "
        "authorize new cast, clues, reveals, diagnoses, subplots, or events.",
    ]
    for entry in projected:
        name = str(entry.get("character") or "")
        if name not in selected:
            continue
        lines.extend(["", f"### {name}"])
        for field in PSYCHOLOGY_LIST_FIELDS:
            values = [
                str(value)
                for value in entry.get(field) or []
                if str(value).strip()
            ]
            if values:
                lines.append(f"**{labels[field]}:**")
                lines.extend(f"- {value}" for value in values)
        for field in PSYCHOLOGY_TEXT_FIELDS:
            value = str(entry.get(field) or "")
            if value.strip():
                lines.append(f"**{labels[field]}:** {value}")
        for gate in entry.get("reveal_gated_fields") or []:
            value = str(gate.get("value") or "")
            if value.strip():
                lines.append(f"**{str(gate.get('field') or 'Gated psychology')}:** {value}")
    return "\n".join(lines)


def reconcile_character_psychology(
    entries: Iterable[dict[str, Any]] | None,
    renames: dict[str, str] | None,
) -> list[dict[str, Any]]:
    out = deepcopy(list(entries or []))
    for entry in out:
        if not isinstance(entry, dict):
            continue
        old = str(entry.get("character") or "")
        if old in (renames or {}):
            entry["character"] = str((renames or {})[old])
    return out


def attach_character_psychology_to_bible(
    bible: dict[str, Any],
    entries: Iterable[dict[str, Any]] | None,
) -> list[str]:
    """Preserve the source contract and map safe fields onto existing bible slots.

    Gated fields are deliberately never copied into always-visible lead fields.
    The exact structured source remains at the bible root for validation and
    downstream consumers.
    """
    source = deepcopy(list(entries or []))
    bible["character_psychology"] = source
    by_name = {
        str(entry.get("character") or ""): entry
        for entry in source
        if isinstance(entry, dict) and str(entry.get("character") or "")
    }
    targets: dict[str, dict[str, Any]] = {}
    leads = bible.get("leads")
    if isinstance(leads, dict):
        for lead in leads.values():
            if isinstance(lead, dict) and str(lead.get("name") or "").strip():
                targets[str(lead["name"]).strip()] = lead
    for row in bible.get("supporting_cast") or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            targets[str(row["name"]).strip()] = row

    warnings: list[str] = []
    for name, entry in by_name.items():
        target = targets.get(name)
        if target is None:
            warnings.append(
                f"character_psychology:{name}: no exact-name bible character target"
            )
            continue
        traits = [str(item) for item in entry.get("core_traits") or [] if str(item).strip()]
        stress = [
            str(item) for item in entry.get("stress_responses") or [] if str(item).strip()
        ]
        constraints = [
            str(item)
            for item in entry.get("behavioral_constraints") or []
            if str(item).strip()
        ]
        internal_parts = [
            f"Core need: {entry.get('core_need')}"
            if str(entry.get("core_need") or "").strip()
            else "",
            f"Core fear: {entry.get('core_fear')}"
            if str(entry.get("core_fear") or "").strip()
            else "",
            f"Coping mechanism: {entry.get('coping_mechanism')}"
            if str(entry.get("coping_mechanism") or "").strip()
            else "",
            f"Cognitive dissonance: {entry.get('cognitive_dissonance')}"
            if str(entry.get("cognitive_dissonance") or "").strip()
            else "",
        ]
        if any(internal_parts):
            target["internal_voice"] = " ".join(part for part in internal_parts if part)
        if traits and not str(target.get("voice") or "").strip():
            target["voice"] = "; ".join(traits)
        if stress and not target.get("tics"):
            target["tics"] = stress
        if constraints:
            target["boundary"] = "; ".join(constraints)

    if warnings:
        meta = bible.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["character_psychology_warnings"] = warnings
    return warnings


def bible_character_psychology_errors(bible: dict[str, Any]) -> list[str]:
    raw = bible.get("character_psychology")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return ["character_psychology: must be a list"]
    names: set[str] = set()
    leads = bible.get("leads")
    if isinstance(leads, dict):
        for row in leads.values():
            if isinstance(row, dict) and str(row.get("name") or "").strip():
                names.add(str(row["name"]).strip())
    for row in bible.get("supporting_cast") or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            names.add(str(row["name"]).strip())
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        path = f"character_psychology[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{path}: must be a map")
            continue
        name = str(entry.get("character") or "").strip()
        if name not in names:
            errors.append(f"{path}.character: no exact-name bible character {name!r}")
        if name in seen:
            errors.append(f"{path}.character: duplicate {name!r}")
        seen.add(name)
    return errors


def protected_concept_digest(concept: dict[str, Any]) -> str:
    """Semantic digest of all concept content except character psychology."""
    protected = deepcopy(concept)
    protected.pop("character_psychology", None)
    blob = json.dumps(
        protected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def assert_only_psychology_changed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    if protected_concept_digest(before) != protected_concept_digest(after):
        raise ValueError(
            "protected concept content changed outside character_psychology"
        )
