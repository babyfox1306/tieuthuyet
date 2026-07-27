"""Plan-time global choices resolved BEFORE the Outliner runs.

Concepts may defer a decision ("one of the three betrays her — decide at plan
time"). Leaving that open until generation means every chunk re-decides, which
is how a book ends up with three leaks. This module makes the decision once,
deterministically, writes it to ``plan_choices.yaml``, and lets the operator
override it by editing that file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

CHOICES_FILENAME = "plan_choices.yaml"


def plan_choices_path(ws: Path) -> Path:
    return ws / CHOICES_FILENAME


def load_plan_choices(ws: Path) -> dict[str, dict[str, Any]]:
    path = plan_choices_path(ws)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, dict):
        return {}
    return {str(k): v for k, v in choices.items() if isinstance(v, dict)}


def save_plan_choices(ws: Path, choices: dict[str, dict[str, Any]]) -> Path:
    path = plan_choices_path(ws)
    path.write_text(
        yaml.dump(
            {"version": 1, "choices": choices},
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _betrayal_evidence_text(ledger: dict[str, Any]) -> str:
    """Ledger prose tied to the betrayal reveal — used to score candidates."""
    from factory.engine.lib.narrative_compiler import (
        clue_semantic_text,
        reveal_semantic_text,
    )

    clues = [c for c in (ledger.get("clues") or []) if isinstance(c, dict)]
    clue_by_id = {str(c.get("id")): c for c in clues}
    parts: list[str] = []
    for rev in ledger.get("major_reveals") or []:
        if not isinstance(rev, dict):
            continue
        text = reveal_semantic_text(rev)
        if not re.search(r"betray|leak|mole", text, re.IGNORECASE):
            continue
        parts.append(text)
        for cid in rev.get("required_clues") or []:
            clue = clue_by_id.get(str(cid))
            if clue:
                parts.append(clue_semantic_text(clue))
    return "\n".join(parts)


def _pick_candidate(
    candidates: list[str], ledger: dict[str, Any]
) -> tuple[str, str]:
    """Deterministic pick + human-readable rationale."""
    if not candidates:
        return "", "no candidates"
    evidence = _betrayal_evidence_text(ledger)
    scored: list[tuple[int, int, str]] = []
    for idx, name in enumerate(candidates):
        surname = name.split()[-1] if name.split() else name
        hits = len(re.findall(re.escape(name), evidence, re.IGNORECASE))
        hits += len(
            re.findall(rf"\b{re.escape(surname)}\b", evidence, re.IGNORECASE)
        )
        scored.append((-hits, idx, name))
    scored.sort()
    best = scored[0]
    hits = -best[0]
    if hits:
        return best[2], (
            f"named in {hits} betrayal-clue/reveal description(s) "
            "in mystery_ledger"
        )
    return candidates[0], (
        "first candidate in locked cast order (ledger gives no signal)"
    )


def resolve_plan_choices(
    ws: Path,
    *,
    force: bool = False,
    overrides: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve every deferred choice and persist.

    Existing values win unless ``force`` — a decision, once made, must not drift
    between chunks or re-plans.
    """
    from factory.engine.lib.narrative_compiler import (
        deferred_choice_defs,
        load_ledger,
        narrative_compiler_enabled,
    )

    if not narrative_compiler_enabled(ws):
        return load_plan_choices(ws)

    ledger = load_ledger(ws)
    defs = deferred_choice_defs(ws, ledger)
    if not defs:
        return load_plan_choices(ws)

    current = load_plan_choices(ws)
    changed = False
    for spec in defs:
        cid = str(spec.get("id"))
        candidates = [
            str(x).strip() for x in (spec.get("candidates") or []) if str(x).strip()
        ]
        override = (overrides or {}).get(cid, "").strip()
        existing = str((current.get(cid) or {}).get("value") or "").strip()

        if override:
            value, rationale, by = override, "operator override", "operator"
        elif existing and not force:
            continue
        else:
            value, rationale = _pick_candidate(candidates, ledger)
            by = "auto"
        if not value:
            continue
        current[cid] = {
            "value": value,
            "candidates": candidates,
            "not_chosen": [
                c for c in candidates if c.lower() != value.lower()
            ],
            "cardinality": int(spec.get("cardinality") or 1),
            "resolved_by": by,
            "rationale": rationale,
        }
        changed = True

    if changed:
        save_plan_choices(ws, current)
    return current


def resolved_choice_value(ws: Path, choice_id: str) -> str:
    entry = load_plan_choices(ws).get(choice_id) or {}
    return str(entry.get("value") or "").strip()
