"""P1 prose settlement — real chapter-N prose drives N+1 memory/custody/strategy."""

from __future__ import annotations

import re
from copy import deepcopy
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


def _entity_names(ir: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for ent in ir.get("entities") or []:
        name = str(ent.get("name") or "").strip()
        if name:
            names.append(name)
    return sorted(names, key=len, reverse=True)


def _pov_name(ir: dict[str, Any]) -> str:
    return str((ir.get("pov") or {}).get("character") or "").strip()


def _append_unique(bucket: list[str], text: str) -> None:
    text = str(text or "").strip()
    if text and text not in bucket:
        bucket.append(text)


def derive_memory_deltas(
    ir: dict[str, Any],
    chapter: int,
    *,
    claims_blob: str,
    moves: dict[str, Any],
    events_realized: list[dict[str, Any]],
) -> dict[str, Any]:
    """What POV now knows/believes because prose N expressed it (verified)."""
    pov = _pov_name(ir)
    knows: list[str] = []
    believes: list[str] = []
    misbeliefs: list[str] = []

    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    for item in entry.get("may_observe") or []:
        text = str(item).strip()
        if text and _event_realized(text, claims_blob):
            _append_unique(knows, text)

    for ev in events_realized:
        action = str(ev.get("action") or "").strip()
        kind = str(ev.get("kind") or "")
        if not action:
            continue
        if kind in {"antagonist_move", "required_event", "countermove"}:
            _append_unique(knows, action)

    observe_items = (moves.get("pov_observation") or {}).get("items") or []
    for item in observe_items:
        text = str(item).strip()
        if text and _event_realized(text, claims_blob):
            _append_unique(knows, text)

    inference = moves.get("inference_or_misbelief") or {}
    for key in ("relationship_turn", "primary_turn"):
        text = str(inference.get(key) or "").strip()
        if text and _event_realized(text, claims_blob):
            _append_unique(believes, text)

    # Cognitive dissonance active for POV if still in psychology and referenced.
    for row in ir.get("character_psychology") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("character") or "").strip() != pov:
            continue
        dissonance = str(row.get("cognitive_dissonance") or "").strip()
        if dissonance and _event_realized(dissonance, claims_blob):
            _append_unique(misbeliefs, dissonance)
        elif dissonance:
            # Still the standing misbelief entering the next chapter unless prose
            # explicitly corrected it (handled by absence of correction claims).
            _append_unique(misbeliefs, dissonance)

    return {
        "character": pov,
        "knows_gained": knows,
        "believes_gained": believes,
        "misbeliefs_active": misbeliefs,
        "source": "prose_settlement",
    }


def derive_prop_custody_deltas(
    ir: dict[str, Any],
    chapter: int,
    *,
    claims_blob: str,
    baseline_props: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Update holders only when verified prose realizes an IR custody action."""
    names = _entity_names(ir)
    out: list[dict[str, Any]] = []
    baseline = {
        str(p.get("prop_id") or ""): deepcopy(p) for p in (baseline_props or [])
    }

    for prop in ir.get("props") or []:
        if not isinstance(prop, dict):
            continue
        pid = str(prop.get("id") or "")
        pname = str(prop.get("name") or "").strip()
        row = deepcopy(baseline.get(pid) or {})
        holder = row.get("holder")
        source = "ir_baseline"
        evidence = None

        # Custody chain rows for this chapter realized in prose.
        for chain in prop.get("custody_chain") or []:
            if not isinstance(chain, dict):
                continue
            if int(chain.get("chapter") or 0) != chapter:
                continue
            action = str(chain.get("action") or chain.get("event") or "").strip()
            new_holder = (
                chain.get("to")
                or chain.get("holder")
                or chain.get("new_holder")
                or chain.get("owner")
            )
            if action and _event_realized(action, claims_blob) and new_holder:
                holder = str(new_holder).strip()
                source = "prose_custody_chain"
                evidence = action
            elif new_holder and pname and pname.casefold() in claims_blob:
                # Prop named in prose + chain row this chapter → accept holder if
                # the holder name also appears near a transfer/retain verb.
                nh = str(new_holder).strip()
                if nh and nh.casefold() in claims_blob:
                    holder = nh
                    source = "prose_custody_chain"
                    evidence = action or f"{pid}@{chapter}"

        # Chapter-map prop_actions realized.
        cmap = ir.get("chapter_map") or {}
        entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
        for pa in entry.get("prop_actions") or []:
            if not isinstance(pa, dict) or str(pa.get("prop_id") or "") != pid:
                continue
            action = str(pa.get("action") or "").strip()
            if action and _event_realized(action, claims_blob):
                # retains / keeps → baseline holder confirmed by prose
                source = "prose_prop_action"
                evidence = action
                if not holder:
                    owners = prop.get("physical_owner_by_chapter") or {}
                    candidates = []
                    for k, v in owners.items():
                        try:
                            ck = int(k)
                        except (TypeError, ValueError):
                            continue
                        if ck <= chapter:
                            candidates.append((ck, v))
                    if candidates:
                        holder = sorted(candidates)[-1][1]

        # Explicit transfer phrasing with IR entities + prop name/id.
        if pname:
            for giver in names:
                for receiver in names:
                    if giver == receiver:
                        continue
                    pat = re.compile(
                        rf"\b{re.escape(giver)}\b.{{0,40}}\b"
                        rf"(?:gives?|hands?|passes?|returns?|delivers?)\b.{{0,40}}"
                        rf"\b{re.escape(pname)}\b.{{0,40}}\b(?:to\s+)?{re.escape(receiver)}\b",
                        re.I,
                    )
                    if pat.search(claims_blob):
                        holder = receiver
                        source = "prose_transfer"
                        evidence = f"{giver}->{receiver}:{pname}"
                    pat2 = re.compile(
                        rf"\b{re.escape(receiver)}\b.{{0,40}}\b"
                        rf"(?:takes?|keeps?|holds?|retains?|has)\b.{{0,40}}"
                        rf"\b{re.escape(pname)}\b",
                        re.I,
                    )
                    if pat2.search(claims_blob):
                        holder = receiver
                        source = "prose_possession"
                        evidence = f"{receiver} holds {pname}"

        out.append(
            {
                "prop_id": pid,
                "name": pname,
                "holder": holder,
                "allowed_actions": row.get("allowed_actions") or [],
                "actions_this_chapter": row.get("actions_this_chapter") or [],
                "source": source,
                "evidence": evidence,
            }
        )
    return out


def derive_strategy_delta(
    *,
    moves: dict[str, Any],
    events_realized: list[dict[str, Any]],
    relationship_delta_target: dict[str, Any] | None,
    claims_blob: str,
) -> dict[str, Any]:
    projected = (moves.get("power_delta") or {}).get("projected")
    realized_actions = [
        str(e.get("action") or "").strip()
        for e in events_realized
        if str(e.get("action") or "").strip()
    ]
    rel = dict(relationship_delta_target or {})
    # Only keep turns that prose actually expressed.
    for key in ("relationship_turn", "primary_turn"):
        text = str(rel.get(key) or "").strip()
        if text and not _event_realized(text, claims_blob):
            rel[key] = None
    return {
        "realized_moves": realized_actions,
        "power_delta": {
            "projected": projected,
            "realized": "gain" if realized_actions else ("hold" if projected else None),
            "source": "prose_settlement",
        },
        "relationship_delta": rel,
        "open_pressure": realized_actions[-1] if realized_actions else None,
        "source": "prose_settlement",
    }


def build_settlement(
    *,
    chapter: int,
    canon_qc: dict[str, Any],
    intelligence: dict[str, Any] | None = None,
    prose_len: int = 0,
    ir: dict[str, Any] | None = None,
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
    full_blob = _claim_blob(list(canon_qc.get("claims") or []))
    match_blob = full_blob or blob

    events_realized: list[dict[str, Any]] = []
    for key in ("countermove", "antagonist_move"):
        branch = moves.get(key) or {}
        action = str(branch.get("action") or "").strip()
        if action and _event_realized(action, match_blob):
            events_realized.append(
                {
                    "kind": key,
                    "action": action,
                    "fact_refs": list(branch.get("fact_refs") or []),
                }
            )
        for item in branch.get("required_events") or []:
            text = str(item).strip()
            if text and _event_realized(text, match_blob):
                events_realized.append(
                    {
                        "kind": "required_event",
                        "action": text,
                        "fact_refs": list(branch.get("fact_refs") or []),
                    }
                )

    memory = (
        derive_memory_deltas(
            ir,
            chapter,
            claims_blob=match_blob,
            moves=moves,
            events_realized=events_realized,
        )
        if ir
        else {
            "character": None,
            "knows_gained": [e.get("action") for e in events_realized],
            "believes_gained": [],
            "misbeliefs_active": [],
            "source": "prose_settlement_no_ir",
        }
    )
    prop_updates = (
        derive_prop_custody_deltas(
            ir,
            chapter,
            claims_blob=match_blob,
            baseline_props=intel.get("prop_state"),
        )
        if ir
        else deepcopy(intel.get("prop_state") or [])
    )
    strategy = derive_strategy_delta(
        moves=moves,
        events_realized=events_realized,
        relationship_delta_target=intel.get("relationship_delta_target"),
        claims_blob=match_blob,
    )

    settlement = {
        "status": "sealed",
        "chapter": chapter,
        "events_realized": events_realized,
        "facts_expressed": expressed,
        "new_claims": [],
        "character_updates": {
            "deltas": memory,
            # Snapshot for audit; N+1 must prefer deltas over raw IR copy.
            "psychology_active": intel.get("psychology_active"),
            "character_cognition_baseline": intel.get("character_cognition")
            or intel.get("character_state"),
            "villain_knowledge": intel.get("villain_knowledge"),
        },
        "prop_updates": prop_updates,
        "honeytoken_state": intel.get("honeytoken_state"),
        "relationship_delta": strategy.get("relationship_delta"),
        "strategy_updates": strategy,
        "power_delta": strategy.get("power_delta"),
        "prose_len": prose_len,
        "texture_excluded_from_state": len(
            canon_qc.get("texture_claims_excluded_from_state") or []
        ),
        "violations": [],
        "continuity_authority": "settlement",
        "authority_note": (
            "Chapter N+1 packet must apply these deltas; "
            "Outliner carries_to_next cannot override them."
        ),
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
    # Also surface memory gained so continuity is not only event list.
    deltas = (prior_settlement.get("character_updates") or {}).get("deltas") or {}
    for text in deltas.get("knows_gained") or []:
        if text and text not in events:
            events.append(text)
    superseded = bool(foresight) and bool(
        events
        or prior_settlement.get("prop_updates")
        or prior_settlement.get("strategy_updates")
    )
    return {
        "source": "settlement",
        "carries_to_next": None if superseded else (foresight or None),
        "events_from_settlement": events,
        "plan_foresight": foresight or None,
        "plan_foresight_superseded": superseded,
        "prior_settlement_digest": prior_settlement.get("settlement_digest"),
        "memory_from_settlement": deltas.get("knows_gained") or [],
        "beliefs_from_settlement": deltas.get("believes_gained") or [],
    }


def apply_settlement_to_intelligence(
    bundle: dict[str, Any],
    prior_settlement: dict[str, Any],
) -> dict[str, Any]:
    """Mutate N+1 intelligence so prose-N deltas become live state (not metadata)."""
    out = deepcopy(bundle)
    deltas = (prior_settlement.get("character_updates") or {}).get("deltas") or {}
    pov = str(deltas.get("character") or "").strip()

    cognition = deepcopy(
        out.get("character_state") or out.get("character_cognition") or []
    )
    for row in cognition:
        if not isinstance(row, dict):
            continue
        name = str(row.get("character") or "").strip()
        if pov and name and name != pov:
            continue
        knows = list(row.get("knows") or [])
        believes = list(row.get("believes") or [])
        misbeliefs = list(row.get("misbeliefs") or [])
        for item in deltas.get("knows_gained") or []:
            _append_unique(knows, str(item))
        for item in deltas.get("believes_gained") or []:
            _append_unique(believes, str(item))
        for item in deltas.get("misbeliefs_active") or []:
            _append_unique(misbeliefs, str(item))
        row["knows"] = knows
        row["believes"] = believes
        row["misbeliefs"] = misbeliefs
        row["continuity_source"] = "settlement"
    out["character_cognition"] = cognition
    out["character_state"] = cognition

    # Prop custody: settlement holders override IR projection when prose-sourced.
    prop_updates = prior_settlement.get("prop_updates") or []
    if prop_updates:
        by_id = {str(p.get("prop_id") or ""): p for p in prop_updates if isinstance(p, dict)}
        merged_props = []
        for prop in out.get("prop_state") or []:
            row = deepcopy(prop)
            pid = str(row.get("prop_id") or "")
            upd = by_id.get(pid)
            if upd and upd.get("holder"):
                # Prefer prose-derived source over pure IR baseline.
                if str(upd.get("source") or "").startswith("prose") or upd.get("evidence"):
                    row["holder"] = upd.get("holder")
                    row["holder_source"] = upd.get("source")
                    row["holder_evidence"] = upd.get("evidence")
                elif not row.get("holder"):
                    row["holder"] = upd.get("holder")
            merged_props.append(row)
        # Include props only present in settlement.
        seen = {str(p.get("prop_id") or "") for p in merged_props}
        for pid, upd in by_id.items():
            if pid and pid not in seen:
                merged_props.append(deepcopy(upd))
        out["prop_state"] = merged_props

    strategy = prior_settlement.get("strategy_updates") or {}
    moves = deepcopy(out.get("moves") or {})
    moves["prior_realized"] = strategy.get("realized_moves") or [
        str(e.get("action") or "")
        for e in (prior_settlement.get("events_realized") or [])
        if isinstance(e, dict)
    ]
    moves["power_delta"] = {
        **(moves.get("power_delta") or {}),
        "incoming": (strategy.get("power_delta") or prior_settlement.get("power_delta")),
        "note": "incoming from chapter N settlement; projected is for this chapter",
    }
    # Carry open pressure into observation context for Writer strategy.
    open_pressure = strategy.get("open_pressure")
    if open_pressure:
        pov_obs = dict(moves.get("pov_observation") or {})
        items = list(pov_obs.get("items") or [])
        _append_unique(items, f"[from ch{prior_settlement.get('chapter')}] {open_pressure}")
        pov_obs["items"] = items
        pov_obs["continuity_source"] = "settlement"
        moves["pov_observation"] = pov_obs
    out["moves"] = moves

    if strategy.get("relationship_delta"):
        out["relationship_delta_target"] = {
            **(out.get("relationship_delta_target") or {}),
            "from_prior_settlement": strategy.get("relationship_delta"),
            "continuity_source": "settlement",
        }

    out["prior_settlement"] = {
        "chapter": prior_settlement.get("chapter"),
        "settlement_digest": prior_settlement.get("settlement_digest"),
        "events_realized": prior_settlement.get("events_realized") or [],
        "character_updates": prior_settlement.get("character_updates"),
        "prop_updates": prior_settlement.get("prop_updates"),
        "strategy_updates": strategy,
        "honeytoken_state": prior_settlement.get("honeytoken_state"),
        "relationship_delta": prior_settlement.get("relationship_delta"),
        "power_delta_realized": prior_settlement.get("power_delta"),
        "continuity_source": "settlement",
        "applied_to_live_state": True,
    }
    out["continuity_authority"] = "settlement"
    return out
