"""P1 story intelligence graphs — deterministic projections from Canonical IR."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from factory.engine.lib.canonical_ir import facts_available_by_chapter


def _phase_for_chapter(chapter: int, chapter_count: int) -> str:
    if chapter_count <= 0:
        return "opening"
    third = max(1, chapter_count // 3)
    if chapter <= third:
        return "opening"
    if chapter <= 2 * third:
        return "middle"
    return "final"


_PHASE_ORDER = {"opening": 0, "middle": 1, "final": 2}
_STOP = frozenset(
    {
        "that",
        "with",
        "from",
        "this",
        "into",
        "have",
        "been",
        "will",
        "when",
        "while",
        "chapter",
        "must",
        "does",
        "not",
        "after",
        "before",
        "about",
        "their",
        "they",
        "them",
        "then",
        "than",
        "also",
        "only",
        "over",
        "under",
        "her",
        "his",
        "she",
        "the",
        "and",
        "for",
        "was",
        "were",
        "are",
        "is",
    }
)


def project_villain_knowledge(ir: dict[str, Any], chapter: int) -> dict[str, Any]:
    """Phase-/clock-scoped villain knowledge. Structured keys beat text heuristics."""
    ledger = ir.get("villain_ledger") or []
    chapter_count = int(ir.get("chapter_count") or 12)
    phase = _phase_for_chapter(chapter, chapter_count)
    selected: dict[str, Any] = {
        "phase": phase,
        "chapter": chapter,
        "knows": [],
        "does_not_know": [],
        "wants_pov_to_believe": [],
        "withholds": [],
        "allowed_moves": [],
        "actions": [],
    }
    for i, row in enumerate(ledger):
        if not isinstance(row, dict):
            continue
        ch_from = int(row.get("chapter_from") or 0)
        ch_to = int(row.get("chapter_to") or 0)
        row_phase = str(row.get("phase") or "").strip().lower()

        if ch_from or ch_to:
            lo = ch_from or 1
            hi = ch_to or chapter_count
            if not (lo <= chapter <= hi):
                continue
        elif row_phase in _PHASE_ORDER:
            # Knowledge accumulates: include current and prior phases only.
            if _PHASE_ORDER[row_phase] > _PHASE_ORDER[phase]:
                continue
        else:
            n = len(ledger)
            expected = (
                "opening"
                if i < max(1, n // 3)
                else "middle"
                if i < max(2, (2 * n) // 3)
                else "final"
            )
            if _PHASE_ORDER.get(expected, 0) > _PHASE_ORDER.get(phase, 0):
                continue

        # Prefer structured fields; heuristics only fill gaps.
        structured_hit = False
        for key in (
            "knows",
            "does_not_know",
            "wants_pov_to_believe",
            "withholds",
            "allowed_moves",
        ):
            for item in row.get(key) or []:
                text = str(item).strip()
                if text and text not in selected[key]:
                    selected[key].append(text)
                    structured_hit = True

        action = str(row.get("action") or "").strip()
        if action:
            selected["actions"].append(action)
            if not structured_hit:
                knows_m = re.search(
                    r"knows?\s+(.+?)(?:\s+but\s+does\s+not\s+know\s+(.+))?$",
                    action,
                    re.I,
                )
                if knows_m:
                    selected["knows"].append(knows_m.group(1).strip(" ."))
                    if knows_m.group(2):
                        selected["does_not_know"].append(knows_m.group(2).strip(" ."))
                if re.search(r"withhold", action, re.I):
                    selected["withholds"].append(action)
    return selected


def project_prop_state(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    out = []
    for prop in ir.get("props") or []:
        if not isinstance(prop, dict):
            continue
        pid = str(prop.get("id") or "")
        owners = prop.get("physical_owner_by_chapter") or {}
        holder = None
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
        actions = [
            row
            for row in (prop.get("custody_chain") or [])
            if isinstance(row, dict) and int(row.get("chapter") or 0) == chapter
        ]
        # Chapter-map prop_actions for this prop at N.
        cmap = ir.get("chapter_map") or {}
        entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
        map_actions = [
            row
            for row in (entry.get("prop_actions") or [])
            if isinstance(row, dict) and str(row.get("prop_id") or "") == pid
        ]
        allowed = []
        for row in actions + map_actions:
            act = str(row.get("action") or "").strip()
            if act and act not in allowed:
                allowed.append(act)
        out.append(
            {
                "prop_id": pid,
                "name": prop.get("name"),
                "holder": holder,
                "actions_this_chapter": actions,
                "allowed_actions": allowed,
            }
        )
    return out


def project_honeytoken_state(ir: dict[str, Any], chapter: int) -> dict[str, Any]:
    honey = ir.get("honeytoken") or {}
    if not isinstance(honey, dict) or not honey:
        return {}
    reuse = int(honey.get("reuse_chapter") or 0)
    state = {
        "phrase_creator": honey.get("phrase_creator"),
        "reuse_chapter": reuse,
        "phase": "pre_reuse" if (reuse and chapter < reuse) else "at_or_after_reuse",
    }
    if reuse and chapter < reuse:
        state["visible"] = {
            "delivery_method": honey.get("delivery_method"),
            "people_who_know_before_delivery": honey.get(
                "people_who_know_before_delivery"
            ),
        }
        state["hidden"] = {
            "evidentiary_value": honey.get("evidentiary_value"),
            "first_illicit_reuse_by": honey.get("first_illicit_reuse_by"),
        }
    else:
        state["visible"] = {
            "delivery_method": honey.get("delivery_method"),
            "first_illicit_reuse_by": honey.get("first_illicit_reuse_by"),
            "evidentiary_value": honey.get("evidentiary_value"),
            "proof_sequence": honey.get("proof_sequence"),
        }
        state["hidden"] = {}
    return state


def project_psychology_active(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    from factory.engine.lib.character_psychology import project_character_psychology

    return project_character_psychology(
        ir.get("character_psychology") or [],
        ir.get("reveal_schedule") or [],
        chapter,
    )


def project_character_cognition(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    """Per-character cognition unlocked at chapter (reveal clocks respected)."""
    out: list[dict[str, Any]] = []
    for entry in project_psychology_active(ir, chapter):
        if not isinstance(entry, dict):
            continue
        knows: list[str] = []
        believes: list[str] = []
        misbeliefs: list[str] = []
        model_of_opponent: list[str] = []

        dissonance = str(entry.get("cognitive_dissonance") or "").strip()
        if dissonance:
            misbeliefs.append(dissonance)
            # "Believes X while …" → rough believe extract
            m = re.match(r"Believes?\s+(.+?)(?:\s+while\b|\s+but\b|$)", dissonance, re.I)
            if m:
                believes.append(m.group(1).strip(" ."))

        for gate in entry.get("reveal_gated_fields") or []:
            if not isinstance(gate, dict):
                continue
            field = str(gate.get("field") or "").strip().casefold()
            value = str(gate.get("value") or "").strip()
            if not value:
                continue
            if field in {"knows", "knowledge", "know"}:
                knows.append(value)
            elif field in {"believes", "belief"}:
                believes.append(value)
            elif field in {"misbelief", "misbeliefs", "cognitive_dissonance"}:
                misbeliefs.append(value)
            elif field in {"model_of_opponent", "opponent_model", "model"}:
                model_of_opponent.append(value)
            elif field in {"goal", "goal_now", "core_need"}:
                pass  # handled below via active fields
            else:
                # Generic unlocked secret becomes knowledge.
                knows.append(f"{field}={value}" if field else value)

        # Chapter-map pov_knows_at_start for matching POV character.
        cmap = ir.get("chapter_map") or {}
        centry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
        pov_name = str((ir.get("pov") or {}).get("character") or "").strip()
        char_name = str(entry.get("character") or "").strip()
        if char_name and pov_name and char_name == pov_name:
            for item in centry.get("pov_knows_at_start") or []:
                text = str(item).strip()
                if text and text not in knows:
                    knows.append(text)

        out.append(
            {
                "character": char_name,
                "knows": knows,
                "believes": believes,
                "misbeliefs": misbeliefs,
                "goal_now": str(entry.get("core_need") or "").strip() or None,
                "fear_active": str(entry.get("core_fear") or "").strip() or None,
                "coping_active": str(entry.get("coping_mechanism") or "").strip() or None,
                "model_of_opponent": model_of_opponent,
                "stress_responses": list(entry.get("stress_responses") or []),
                "behavioral_constraints": list(entry.get("behavioral_constraints") or []),
            }
        )
    return out


def project_body_condition(ir: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(ir.get("psychological_condition") or {})


def project_romance_doctrine(ir: dict[str, Any]) -> dict[str, Any]:
    doctrine = ir.get("romance_doctrine") or {}
    if doctrine:
        return deepcopy(doctrine)
    notes = str((ir.get("plots") or {}).get("notes") or "")
    rules = []
    forbidden = []
    if "Zero-Trust" in notes or "zero-trust" in notes.casefold():
        rules.append("Zero-Trust Romance")
    if "Mutual Assured Destruction" in notes or "Mutual Digital Predation" in notes:
        rules.append("Mutual Assured Destruction / Mutual Digital Predation")
    if "Competence" in notes:
        rules.append("Competence over confession")
    cond = ir.get("psychological_condition") or {}
    for item in cond.get("must_not_be_described_as") or []:
        forbidden.append(str(item))
    if not rules and not forbidden:
        return {}
    return {"rules": rules, "forbidden_framings": forbidden, "source": "compiled_notes"}


def project_relationship_delta_target(ir: dict[str, Any], chapter: int) -> dict[str, Any]:
    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    if not isinstance(entry, dict):
        entry = {}
    true_plot = str((ir.get("plots") or {}).get("true_plot") or "")
    return {
        "relationship_turn": entry.get("relationship_turn"),
        "primary_turn": entry.get("primary_turn"),
        "constraints_from_true_plot": bool(true_plot),
        "source": "chapter_map+true_plot",
    }


def project_setting_threshold(ir: dict[str, Any], chapter: int) -> dict[str, Any]:
    """Optional setting/threshold projection; omit quietly when CE lacks blocks."""
    if not ir.get("setting_graph") and not ir.get("threshold_events"):
        return {}
    from factory.engine.lib.story_context import project_story_context

    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    projected = project_story_context(ir, chapter, entry if isinstance(entry, dict) else {})
    if not projected:
        return {"omitted": True, "reason": "no_active_setting_or_threshold"}
    return projected


def _tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9']{4,}", (text or "").casefold())
        if w not in _STOP
    }


def resolve_fact_refs(
    ir: dict[str, Any],
    chapter: int,
    texts: list[str],
    *,
    extra_ids: list[str] | None = None,
) -> list[str]:
    """Map free text / ids onto IR fact_ids available at chapter."""
    refs: list[str] = []
    seen: set[str] = set()

    def _add(fid: str) -> None:
        fid = str(fid or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            refs.append(fid)

    for eid in extra_ids or []:
        _add(eid)

    blob_ids = re.findall(r"\b(?:C|R|P|F_)[A-Za-z0-9_]+\b", " ".join(texts))
    for eid in blob_ids:
        if eid.startswith(("C", "R", "P")) and not eid.startswith("F_"):
            # Map clue/reveal/prop ids to fact registry ids when present.
            for fact in ir.get("facts") or []:
                meta = fact.get("meta") or {}
                fid = str(fact.get("fact_id") or "")
                if eid == str(meta.get("clue_id") or meta.get("id") or ""):
                    _add(fid)
                if eid == str(meta.get("reveal_id") or ""):
                    _add(fid)
                if eid == str(meta.get("prop_id") or ""):
                    _add(fid)
                if fid == f"F_CLUE_{eid}" or fid == f"F_REVEAL_{eid}" or fid == f"F_PROP_{eid}":
                    _add(fid)
        else:
            _add(eid)

    available = facts_available_by_chapter(ir, chapter)
    text_tokens = _tokens(" ".join(texts))
    if text_tokens:
        scored: list[tuple[int, str]] = []
        for fact in available:
            fid = str(fact.get("fact_id") or "")
            claim_toks = _tokens(str(fact.get("claim") or ""))
            overlap = len(text_tokens & claim_toks)
            if overlap >= 2 or (overlap >= 1 and len(claim_toks) <= 4):
                scored.append((overlap, fid))
        for _score, fid in sorted(scored, reverse=True)[:8]:
            _add(fid)

    # Always attach chapter-local obligations / clue-payoff / prop facts.
    for fact in available:
        fid = str(fact.get("fact_id") or "")
        refs_src = " ".join(str(r) for r in (fact.get("source_refs") or []))
        if f"must_include_by_chapter.{chapter}" in refs_src or fid.startswith(
            f"F_MUST_CH{chapter}_"
        ):
            _add(fid)
        meta = fact.get("meta") or {}
        if int(meta.get("plant_chapter") or 0) == chapter:
            _add(fid)
        if int(meta.get("payoff_chapter") or 0) == chapter:
            _add(fid)

    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    for cid in entry.get("clue_ids_planted") or []:
        _add(f"F_CLUE_{cid}")
    for cid in entry.get("clue_ids_paid_off") or []:
        _add(f"F_CLUE_{cid}")
    for rid in entry.get("reveal_ids_opened") or []:
        _add(f"F_REVEAL_{rid}")
    for row in entry.get("prop_actions") or []:
        if isinstance(row, dict) and row.get("prop_id"):
            _add(f"F_PROP_{row['prop_id']}")

    # Drop refs that do not exist in registry (avoid inventing ids).
    known = {str(f.get("fact_id") or "") for f in ir.get("facts") or []}
    return [r for r in refs if r in known]


def _branch(
    *,
    action: str | None,
    items: list[str] | None = None,
    fact_refs: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    has_content = bool((action or "").strip() or (items or []))
    row: dict[str, Any] = {
        "action": action,
        "fact_refs": list(fact_refs),
    }
    if items is not None:
        row["items"] = items
    if extra:
        row.update(extra)
    if has_content and not fact_refs:
        row["ephemeral_safe"] = False
        row["fact_refs_incomplete"] = True
    elif not has_content:
        row["ephemeral_safe"] = True
        row["fact_refs"] = []
    else:
        row["ephemeral_safe"] = False
    return row


def build_move_countermove(
    ir: dict[str, Any],
    chapter: int,
) -> dict[str, Any]:
    """Typed move chain with fact_refs resolved from IR (not Outliner)."""
    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    if not isinstance(entry, dict):
        entry = {}
    must = [str(x) for x in (entry.get("must_happen") or []) if str(x).strip()]
    observe = [str(x) for x in (entry.get("may_observe") or []) if str(x).strip()]

    observe_refs = resolve_fact_refs(ir, chapter, observe)
    must_refs = resolve_fact_refs(ir, chapter, must)
    turn_text = " ".join(
        str(x)
        for x in (entry.get("relationship_turn"), entry.get("primary_turn"))
        if x
    )
    turn_refs = resolve_fact_refs(ir, chapter, [turn_text] if turn_text else [])

    leverage = "gain" if chapter >= int(ir.get("chapter_count") or 12) // 2 else "pressure"
    return {
        "chapter": chapter,
        "antagonist_move": _branch(
            action=observe[0] if observe else None,
            fact_refs=observe_refs,
        ),
        "pov_observation": _branch(
            action=None,
            items=observe,
            fact_refs=observe_refs,
        ),
        "inference_or_misbelief": {
            "relationship_turn": entry.get("relationship_turn"),
            "primary_turn": entry.get("primary_turn"),
            "fact_refs": turn_refs,
            "ephemeral_safe": not bool(turn_text),
            **(
                {"fact_refs_incomplete": True}
                if turn_text and not turn_refs
                else {}
            ),
        },
        "countermove": _branch(
            action=must[0] if must else None,
            fact_refs=must_refs,
            extra={"required_events": must},
        ),
        "cost": {
            "description": entry.get("primary_turn") or entry.get("relationship_turn"),
            "fact_refs": turn_refs,
            "ephemeral_safe": not bool(turn_text),
        },
        "power_delta": {
            "projected": leverage,
            "source": "chapter_map_phase",
            "realized": None,
            "note": "realized filled by settlement after canon_qc pass",
        },
    }


# Back-compat alias used by older call sites / tests.
def build_move_countermove_skeleton(
    ir: dict[str, Any],
    chapter: int,
) -> dict[str, Any]:
    return build_move_countermove(ir, chapter)


def move_fact_ref_errors(moves: dict[str, Any] | None) -> list[dict[str, Any]]:
    """STOP rows when a non-empty move branch lacks fact_refs and is not ephemeral_safe."""
    if not isinstance(moves, dict):
        return []
    errors: list[dict[str, Any]] = []
    for key in (
        "antagonist_move",
        "pov_observation",
        "inference_or_misbelief",
        "countermove",
        "cost",
    ):
        branch = moves.get(key)
        if not isinstance(branch, dict):
            continue
        if branch.get("ephemeral_safe"):
            continue
        refs = branch.get("fact_refs") or []
        has_content = bool(
            str(branch.get("action") or "").strip()
            or branch.get("items")
            or branch.get("relationship_turn")
            or branch.get("primary_turn")
            or branch.get("description")
            or branch.get("required_events")
        )
        if has_content and not refs:
            errors.append(
                {
                    "field": f"moves.{key}",
                    "claim": str(
                        branch.get("action")
                        or branch.get("relationship_turn")
                        or branch.get("description")
                        or (branch.get("items") or [""])[0]
                        or key
                    )[:320],
                    "reason": "move_missing_fact_refs",
                    "status": "UNRESOLVED",
                    "authority": "IR_COMPILER",
                    "severity": "block",
                }
            )
    return errors


def compile_chapter_intelligence(
    ir: dict[str, Any],
    chapter: int,
    *,
    prior_settlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cognition = project_character_cognition(ir, chapter)
    psychology = project_psychology_active(ir, chapter)
    setting = project_setting_threshold(ir, chapter)
    bundle: dict[str, Any] = {
        "character_cognition": cognition,
        "character_state": cognition,  # alias for packet contract
        "villain_knowledge": project_villain_knowledge(ir, chapter),
        "prop_state": project_prop_state(ir, chapter),
        "honeytoken_state": project_honeytoken_state(ir, chapter),
        "psychology_active": psychology,
        "body_condition_active": project_body_condition(ir),
        "romance_doctrine": project_romance_doctrine(ir),
        "relationship_delta_target": project_relationship_delta_target(ir, chapter),
        "moves": build_move_countermove(ir, chapter),
    }
    if setting:
        bundle["setting_threshold"] = setting
    if prior_settlement and prior_settlement.get("status") == "sealed":
        bundle["prior_settlement"] = {
            "chapter": prior_settlement.get("chapter"),
            "settlement_digest": prior_settlement.get("settlement_digest"),
            "events_realized": prior_settlement.get("events_realized") or [],
            "character_updates": prior_settlement.get("character_updates"),
            "prop_updates": prior_settlement.get("prop_updates"),
            "honeytoken_state": prior_settlement.get("honeytoken_state"),
            "relationship_delta": prior_settlement.get("relationship_delta"),
            "power_delta_realized": prior_settlement.get("power_delta"),
            "continuity_source": "settlement",
        }
    else:
        bundle["prior_settlement"] = None
    return bundle
