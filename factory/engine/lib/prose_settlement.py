"""P1 prose settlement — feed verified character/prop updates to next chapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.engine.lib.canon_artifacts import artifact_path, read_json, write_json
from factory.engine.lib.canonical_ir import sha256_obj


def load_settlement(ws: Path, book: int, chapter: int) -> dict[str, Any] | None:
    if chapter <= 0:
        return None
    data = read_json(artifact_path(ws, book, chapter, "settlement.json"))
    if not isinstance(data, dict):
        return None
    return data


def _claim_blob(claims: list[dict[str, Any]]) -> str:
    return "\n".join(str(c.get("claim") or "") for c in claims).casefold()


def _event_realized(text: str, blob: str) -> bool:
    tokens = [w for w in text.casefold().split() if len(w) >= 4]
    if not tokens:
        return False
    hits = sum(1 for w in tokens if w in blob)
    return hits >= max(2, len(tokens) // 3)


def build_settlement(
    *,
    chapter: int,
    canon_qc: dict[str, Any],
    intelligence: dict[str, Any] | None = None,
    prose_len: int = 0,
) -> dict[str, Any]:
    if canon_qc.get("status") != "pass":
        return {
            "status": "blocked",
            "chapter": chapter,
            "reason": "canon_qc_not_pass",
        }
    # Generic texture / ephemeral never enters verified state payload.
    expressed = []
    for c in canon_qc.get("claims") or []:
        if c.get("kind") in {"generic_texture", "ephemeral_texture"}:
            continue
        if c.get("enter_state") is False:
            continue
        expressed.append(
            {
                "claim": c.get("claim"),
                "kind": c.get("kind"),
                "span_type": c.get("span_type"),
            }
        )

    intel = intelligence or {}
    moves = intel.get("moves") or {}
    blob = _claim_blob(expressed)
    # Also search raw claim list including texture for event matching only.
    full_blob = _claim_blob(list(canon_qc.get("claims") or []))

    events_realized: list[dict[str, Any]] = []
    for key in ("countermove", "antagonist_move"):
        branch = moves.get(key) or {}
        action = str(branch.get("action") or "").strip()
        if action and _event_realized(action, full_blob or blob):
            events_realized.append(
                {
                    "kind": key,
                    "action": action,
                    "fact_refs": list(branch.get("fact_refs") or []),
                }
            )
        for item in branch.get("required_events") or []:
            text = str(item).strip()
            if text and _event_realized(text, full_blob or blob):
                events_realized.append(
                    {
                        "kind": "required_event",
                        "action": text,
                        "fact_refs": list(branch.get("fact_refs") or []),
                    }
                )

    projected = (moves.get("power_delta") or {}).get("projected")
    power_delta = {
        "projected": projected,
        "realized": "gain"
        if events_realized
        else ("hold" if projected else None),
        "source": "settlement_from_claims",
    }

    settlement = {
        "status": "sealed",
        "chapter": chapter,
        "events_realized": events_realized,
        "facts_expressed": expressed,
        "new_claims": [],
        "character_updates": {
            "psychology_active": intel.get("psychology_active"),
            "character_cognition": intel.get("character_cognition")
            or intel.get("character_state"),
            "villain_knowledge": intel.get("villain_knowledge"),
        },
        "prop_updates": intel.get("prop_state"),
        "honeytoken_state": intel.get("honeytoken_state"),
        "relationship_delta": intel.get("relationship_delta_target")
        or intel.get("moves"),
        "power_delta": power_delta,
        "prose_len": prose_len,
        "texture_excluded_from_state": len(
            canon_qc.get("texture_claims_excluded_from_state") or []
        ),
        "violations": [],
        "continuity_authority": "settlement",
    }
    settlement["settlement_digest"] = sha256_obj(
        {k: v for k, v in settlement.items() if k != "settlement_digest"}
    )
    return settlement


def write_settlement(ws, book: int, chapter: int, settlement: dict[str, Any]) -> None:
    write_json(artifact_path(ws, book, chapter, "settlement.json"), settlement)


def continuity_from_prior(
    plan: dict[str, Any],
    prior_settlement: dict[str, Any] | None,
) -> dict[str, Any]:
    """Settlement wins over Outliner carries_to_next when both exist."""
    foresight = str(plan.get("carries_to_next") or "").strip()
    if not prior_settlement or prior_settlement.get("status") != "sealed":
        return {
            "source": "plan_foresight" if foresight else "none",
            "carries_to_next": foresight or None,
            "events_from_settlement": [],
            "plan_foresight_superseded": False,
        }
    events = []
    for e in prior_settlement.get("events_realized") or []:
        if isinstance(e, dict):
            text = str(e.get("action") or "").strip()
        else:
            text = str(e or "").strip()
        if text:
            events.append(text)
    superseded = bool(foresight) and bool(events)
    return {
        "source": "settlement",
        "carries_to_next": None if superseded else (foresight or None),
        "events_from_settlement": events,
        "plan_foresight": foresight or None,
        "plan_foresight_superseded": superseded,
        "prior_settlement_digest": prior_settlement.get("settlement_digest"),
    }
