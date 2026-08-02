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


def _holders_compatible(a: Any, b: Any) -> bool:
    """True when holder names refer to the same person (short vs full name)."""
    sa = str(a or "").strip().casefold()
    sb = str(b or "").strip().casefold()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    return sa in sb or sb in sa


def scheduled_holder_at(prop: dict[str, Any], chapter: int) -> str | None:
    """Resolve physical_owner_by_chapter for prop at chapter."""
    owners = prop.get("physical_owner_by_chapter") or {}
    candidates: list[tuple[int, str]] = []
    for k, v in owners.items():
        try:
            ck = int(k)
        except (TypeError, ValueError):
            continue
        if ck <= chapter:
            candidates.append((ck, str(v).strip()))
    if not candidates:
        return None
    return sorted(candidates)[-1][1] or None


def _prop_by_id(ir: dict[str, Any], prop_id: str) -> dict[str, Any] | None:
    for prop in ir.get("props") or []:
        if isinstance(prop, dict) and str(prop.get("id") or "") == prop_id:
            return prop
    return None


def _allowed_actions_at(
    ir: dict[str, Any], prop: dict[str, Any], chapter: int
) -> list[str]:
    pid = str(prop.get("id") or "")
    allowed: list[str] = []
    for row in prop.get("custody_chain") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("chapter") or 0) != chapter:
            continue
        act = str(row.get("action") or row.get("event") or "").strip()
        if act and act not in allowed:
            allowed.append(act)
    cmap = ir.get("chapter_map") or {}
    entry = cmap.get(chapter) or cmap.get(str(chapter)) or {}
    for row in entry.get("prop_actions") or []:
        if not isinstance(row, dict) or str(row.get("prop_id") or "") != pid:
            continue
        act = str(row.get("action") or "").strip()
        if act and act not in allowed:
            allowed.append(act)
    return allowed


def _chain_holder_at(prop: dict[str, Any], chapter: int) -> str | None:
    for row in prop.get("custody_chain") or []:
        if not isinstance(row, dict):
            continue
        if int(row.get("chapter") or 0) != chapter:
            continue
        holder = (
            row.get("to")
            or row.get("holder")
            or row.get("new_holder")
            or row.get("owner")
        )
        if holder:
            return str(holder).strip()
    return None


def _action_permitted(
    action: str | None, allowed: list[str], *, claims_blob: str = ""
) -> bool:
    """True when action is empty (holder-only confirm) or matches an allowed action.

    Requires verb-level overlap — shared prop/person names alone are not enough.
    """
    act = str(action or "").strip()
    if not act:
        return True
    if not allowed:
        return False
    act_cf = act.casefold()
    verb_re = re.compile(
        r"\b(gives?|hands?|passes?|returns?|delivers?|takes?|keeps?|holds?|"
        r"retains?|analyzes?|maintains?|destroys?|deletes?|wipes?|steals?|"
        r"seizes?|transfers?)\b",
        re.I,
    )
    act_verbs = {m.group(0).casefold().rstrip("s") for m in verb_re.finditer(act)}
    for allowed_act in allowed:
        allowed_cf = allowed_act.casefold()
        if allowed_cf in act_cf or act_cf in allowed_cf:
            return True
        allowed_verbs = {
            m.group(0).casefold().rstrip("s") for m in verb_re.finditer(allowed_act)
        }
        # Shared content tokens excluding ultra-common names is not enough;
        # require at least one shared action verb when both sides have verbs.
        if act_verbs and allowed_verbs:
            if act_verbs & allowed_verbs:
                # Also require a non-verb content token overlap (prop/object).
                drop = {
                    "that",
                    "with",
                    "from",
                    "this",
                    "into",
                    "have",
                    "been",
                    "will",
                    "when",
                    "mara",
                    "adrian",
                    "claire",
                    "thorne",
                    "voss",
                }
                a_toks = {
                    w
                    for w in re.findall(r"[a-z0-9']{4,}", act_cf)
                    if w not in drop and w.rstrip("s") not in act_verbs
                }
                b_toks = {
                    w
                    for w in re.findall(r"[a-z0-9']{4,}", allowed_cf)
                    if w not in drop and w.rstrip("s") not in allowed_verbs
                }
                if a_toks & b_toks:
                    return True
        elif claims_blob and _event_realized(allowed_act, claims_blob):
            if _event_realized(act, claims_blob):
                # Prose realized this allowed chain action.
                return True
    return False


def evaluate_prop_holder_claim(
    *,
    ir: dict[str, Any],
    prop_id: str,
    chapter: int,
    proposed_holder: str | None,
    action: str | None = None,
    source: str = "settlement",
    claims_blob: str = "",
) -> dict[str, Any]:
    """Allow/clamp a proposed prop holder against IR custody schedule.

    Authority: physical_owner_by_chapter + custody_chain / chapter_map prop_actions.
    """
    prop = _prop_by_id(ir, prop_id)
    scheduled = scheduled_holder_at(prop, chapter) if prop else None
    chain_holder = _chain_holder_at(prop, chapter) if prop else None
    allowed = _allowed_actions_at(ir, prop, chapter) if prop else []
    proposed = str(proposed_holder or "").strip() or None

    base = {
        "prop_id": prop_id,
        "proposed_holder": proposed,
        "scheduled_holder": scheduled,
        "chain_holder": chain_holder,
        "allowed_actions": allowed,
        "action": action,
        "source": source,
        "current_chapter": chapter,
        "clock_used": "physical_owner_by_chapter",
    }
    if not prop:
        return {
            **base,
            "decision": "clamped",
            "holder": None,
            "reason": "unknown_prop",
        }
    if not proposed:
        return {
            **base,
            "decision": "allowed",
            "holder": scheduled,
            "reason": "ir_baseline",
        }

    # Wrong holder vs schedule AND vs chain authorization at this chapter.
    schedule_ok = bool(scheduled and _holders_compatible(proposed, scheduled))
    chain_ok = bool(chain_holder and _holders_compatible(proposed, chain_holder))
    if not schedule_ok and not chain_ok:
        return {
            **base,
            "decision": "clamped",
            "holder": scheduled,
            "reason": "holder_not_on_schedule",
        }

    # Right-ish holder but action not permitted this chapter.
    if action and not _action_permitted(action, allowed, claims_blob=claims_blob):
        return {
            **base,
            "decision": "clamped",
            "holder": scheduled,
            "reason": "action_not_allowed",
        }

    # Transfer/possession only stick when schedule OR chain authorizes the holder
    # at this chapter (chain_ok covers verified contract transfer).
    if source.startswith("prose_transfer") or source.startswith("prose_possession"):
        if not (schedule_ok or chain_ok):
            return {
                **base,
                "decision": "clamped",
                "holder": scheduled,
                "reason": "holder_not_on_schedule",
            }
        if allowed and action and not _action_permitted(
            action, allowed, claims_blob=claims_blob
        ):
            return {
                **base,
                "decision": "clamped",
                "holder": scheduled,
                "reason": "action_not_allowed",
            }

    return {
        **base,
        "decision": "allowed",
        "holder": proposed,
        "reason": "schedule_or_chain_match",
    }


def clamp_prop_updates_to_schedule(
    prop_updates: list[dict[str, Any]],
    ir: dict[str, Any],
    chapter: int,
    *,
    source: str = "settlement",
    claims_blob: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-clamp settlement/derived prop holders to IR schedule at chapter."""
    kept: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for upd in prop_updates or []:
        if not isinstance(upd, dict):
            continue
        row = deepcopy(upd)
        pid = str(row.get("prop_id") or "").strip()
        verdict = evaluate_prop_holder_claim(
            ir=ir,
            prop_id=pid,
            chapter=chapter,
            proposed_holder=row.get("holder"),
            action=str(row.get("evidence") or row.get("action") or "") or None,
            source=str(row.get("source") or source),
            claims_blob=claims_blob,
        )
        audit.append(verdict)
        if verdict.get("decision") == "clamped":
            row["holder"] = verdict.get("holder")
            row["holder_clamped"] = True
            row["clamp_reason"] = verdict.get("reason")
            row["source"] = "ir_schedule_clamp"
        else:
            row["holder_clamped"] = False
        kept.append(row)
    return kept, audit


def pov_locked_knowledge_claims(
    ir: dict[str, Any],
    chapter: int,
) -> list[dict[str, Any]]:
    """Facts POV must not gain as *knowledge* before pov_knows_chapter.

    Authority is pov_knows_chapter only. Missing POV clock → unresolved (blocked).
    Never treats reader_reveal_chapter as knowledge authority.
    """
    out: list[dict[str, Any]] = []
    for rev in ir.get("reveal_schedule") or []:
        if not isinstance(rev, dict):
            continue
        fact = str(rev.get("fact") or "").strip()
        if not fact:
            continue
        rid = str(rev.get("id") or "").strip()
        reader_ch = rev.get("reader_reveal_chapter")
        try:
            reader_ch_i = int(reader_ch) if reader_ch is not None else None
        except (TypeError, ValueError):
            reader_ch_i = None
        if "pov_knows_chapter" not in rev or rev.get("pov_knows_chapter") in (None, ""):
            out.append(
                {
                    "fact_id": f"F_REVEAL_{rid}" if rid else None,
                    "reveal_id": rid,
                    "claim": fact,
                    "unlock_chapter": None,
                    "reader_reveal_chapter": reader_ch_i,
                    "pov_knows_chapter": None,
                    "kind": "reveal_missing_pov_clock",
                    "decision_if_matched": "unresolved_clock",
                }
            )
            continue
        pov_ch = int(rev.get("pov_knows_chapter"))
        if pov_ch > chapter:
            out.append(
                {
                    "fact_id": f"F_REVEAL_{rid}" if rid else None,
                    "reveal_id": rid,
                    "claim": fact,
                    "unlock_chapter": pov_ch,
                    "reader_reveal_chapter": reader_ch_i,
                    "pov_knows_chapter": pov_ch,
                    "kind": "reveal_pov_clock",
                    "decision_if_matched": "clamped",
                }
            )
    for clue in ir.get("clues") or []:
        if not isinstance(clue, dict):
            continue
        payoff = int(clue.get("payoff_chapter") or 0)
        meaning = str(clue.get("true_meaning_at_payoff") or "").strip()
        if meaning and payoff and payoff > chapter:
            out.append(
                {
                    "fact_id": f"F_CLUE_{clue.get('id')}_TRUE",
                    "claim": meaning,
                    "unlock_chapter": payoff,
                    "reader_reveal_chapter": None,
                    "pov_knows_chapter": payoff,
                    "kind": "clue_true_meaning",
                    "decision_if_matched": "clamped",
                }
            )
    unlock = int(ir.get("canonical_reveal_chapter") or 0)
    true_plot = str((ir.get("plots") or {}).get("true_plot") or "").strip()
    if true_plot and unlock and chapter < unlock:
        out.append(
            {
                "fact_id": "F_PLOT_TRUE_PLOT",
                "claim": true_plot,
                "unlock_chapter": unlock,
                "reader_reveal_chapter": None,
                "pov_knows_chapter": unlock,
                "kind": "plot",
                "decision_if_matched": "clamped",
            }
        )
    return out


def _all_reveal_rows(ir: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rev in ir.get("reveal_schedule") or []:
        if not isinstance(rev, dict):
            continue
        fact = str(rev.get("fact") or "").strip()
        if not fact:
            continue
        rid = str(rev.get("id") or "").strip()
        reader_raw = rev.get("reader_reveal_chapter")
        try:
            reader_ch = int(reader_raw) if reader_raw is not None else None
        except (TypeError, ValueError):
            reader_ch = None
        has_pov = "pov_knows_chapter" in rev and rev.get("pov_knows_chapter") not in (
            None,
            "",
        )
        pov_ch = int(rev.get("pov_knows_chapter")) if has_pov else None
        rows.append(
            {
                "fact_id": f"F_REVEAL_{rid}" if rid else None,
                "reveal_id": rid,
                "claim": fact,
                "reader_reveal_chapter": reader_ch,
                "pov_knows_chapter": pov_ch,
                "has_pov_clock": has_pov,
            }
        )
    return rows


def _knowledge_matches_locked(text: str, locked: dict[str, Any]) -> bool:
    """True when candidate knowledge states a locked reveal/true-meaning claim."""
    claim = str(locked.get("claim") or "").strip()
    cand = str(text or "").strip()
    if not claim or not cand:
        return False
    cf_claim = claim.casefold()
    cf_cand = cand.casefold()
    if cf_claim in cf_cand or cf_cand in cf_claim:
        return True
    drop = {
        "that",
        "with",
        "from",
        "this",
        "into",
        "have",
        "been",
        "will",
        "when",
        "mara",
        "adrian",
        "claire",
    }
    claim_toks = {
        w for w in re.findall(r"[a-z0-9']{4,}", cf_claim) if w not in drop
    }
    cand_toks = {
        w for w in re.findall(r"[a-z0-9']{4,}", cf_cand) if w not in drop
    }
    if not claim_toks:
        return False
    overlap = claim_toks & cand_toks
    need = 3 if len(claim_toks) >= 5 else max(2, (len(claim_toks) + 1) // 2)
    return len(overlap) >= need


def _audit_entry(
    *,
    fact_id: str | None,
    reveal_id: str | None,
    claim: str,
    decision: str,
    current_chapter: int,
    pov_knows_chapter: int | None,
    reader_reveal_chapter: int | None,
    source: str,
    reason: str,
    target: str = "character_state.knows",
) -> dict[str, Any]:
    return {
        "fact_id": fact_id or reveal_id,
        "reveal_id": reveal_id,
        "claim": claim[:240],
        "target": target,
        "decision": decision,
        "clock_used": "pov_knows_chapter",
        "pov_knows_chapter": pov_knows_chapter,
        "reader_reveal_chapter": reader_reveal_chapter,
        "current_chapter": current_chapter,
        "source": source,
        "reason": reason,
    }


def evaluate_knowledge_against_pov_clocks(
    texts: list[str],
    ir: dict[str, Any],
    chapter: int,
    *,
    source: str = "canonical_ir",
    target: str = "character_state.knows",
) -> tuple[list[str], list[dict[str, Any]]]:
    """Allow/clamp candidate knowledge using pov_knows_chapter only.

    Returns (kept_texts, audit_entries). Every matched reveal is audited
    (allowed | clamped | unresolved_clock). Non-reveal observations pass without
    a reveal audit entry.
    """
    reveals = _all_reveal_rows(ir)
    locked = pov_locked_knowledge_claims(ir, chapter)
    kept: list[str] = []
    audit: list[dict[str, Any]] = []

    for text in texts:
        item = str(text or "").strip()
        if not item:
            continue

        matched_reveal = None
        for row in reveals:
            if _knowledge_matches_locked(item, row):
                matched_reveal = row
                break

        if matched_reveal is not None:
            if not matched_reveal.get("has_pov_clock"):
                audit.append(
                    _audit_entry(
                        fact_id=matched_reveal.get("fact_id"),
                        reveal_id=matched_reveal.get("reveal_id"),
                        claim=item,
                        decision="unresolved_clock",
                        current_chapter=chapter,
                        pov_knows_chapter=None,
                        reader_reveal_chapter=matched_reveal.get(
                            "reader_reveal_chapter"
                        ),
                        source=source,
                        reason="missing_pov_knows_chapter",
                        target=target,
                    )
                )
                continue
            pov_ch = int(matched_reveal["pov_knows_chapter"])
            if pov_ch > chapter:
                audit.append(
                    _audit_entry(
                        fact_id=matched_reveal.get("fact_id"),
                        reveal_id=matched_reveal.get("reveal_id"),
                        claim=item,
                        decision="clamped",
                        current_chapter=chapter,
                        pov_knows_chapter=pov_ch,
                        reader_reveal_chapter=matched_reveal.get(
                            "reader_reveal_chapter"
                        ),
                        source=source,
                        reason="pov_clock_not_reached",
                        target=target,
                    )
                )
                continue
            audit.append(
                _audit_entry(
                    fact_id=matched_reveal.get("fact_id"),
                    reveal_id=matched_reveal.get("reveal_id"),
                    claim=item,
                    decision="allowed",
                    current_chapter=chapter,
                    pov_knows_chapter=pov_ch,
                    reader_reveal_chapter=matched_reveal.get("reader_reveal_chapter"),
                    source=source,
                    reason="pov_clock_reached",
                    target=target,
                )
            )
            _append_unique(kept, item)
            continue

        # Non-reveal text: still block if it matches locked true-meaning/plot.
        hit = None
        for row in locked:
            if row.get("kind") in {"clue_true_meaning", "plot"} and _knowledge_matches_locked(
                item, row
            ):
                hit = row
                break
        if hit:
            audit.append(
                _audit_entry(
                    fact_id=hit.get("fact_id"),
                    reveal_id=hit.get("reveal_id"),
                    claim=item,
                    decision="clamped",
                    current_chapter=chapter,
                    pov_knows_chapter=hit.get("pov_knows_chapter"),
                    reader_reveal_chapter=hit.get("reader_reveal_chapter"),
                    source=source,
                    reason="pov_clock_not_reached",
                    target=target,
                )
            )
            continue
        _append_unique(kept, item)

    return kept, audit


def clamp_knowledge_to_reveal_clocks(
    texts: list[str],
    ir: dict[str, Any],
    chapter: int,
    *,
    source: str = "canonical_ir",
    target: str = "character_state.knows",
) -> tuple[list[str], list[dict[str, Any]]]:
    """Back-compat wrapper: returns kept + clamp/unresolved audit only."""
    kept, audit = evaluate_knowledge_against_pov_clocks(
        texts, ir, chapter, source=source, target=target
    )
    clamped = [a for a in audit if a.get("decision") in {"clamped", "unresolved_clock"}]
    return kept, clamped


def evaluate_knowledge_full_audit(
    texts: list[str],
    ir: dict[str, Any],
    chapter: int,
    *,
    source: str = "canonical_ir",
    target: str = "character_state.knows",
) -> tuple[list[str], list[dict[str, Any]]]:
    """Full allow+clamp audit (preferred for verification)."""
    return evaluate_knowledge_against_pov_clocks(
        texts, ir, chapter, source=source, target=target
    )


def evaluate_belief_provenance(
    entries: list[Any],
    ir: dict[str, Any],
    chapter: int,
    *,
    source: str = "prose_settlement",
    target: str = "character_state.believes",
    default_provenance: str | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Keep beliefs/misbeliefs only when they have provenance OR match a reveal.

    Provenance sources: observation | psychology | settlement | inference | canonical_ir
    Hidden true facts still go through POV-clock evaluate (cannot leak via misbelief).
    Beliefs without provenance and without reveal match → omitted (fail-closed).
    """
    allowed_prov = {
        "observation",
        "psychology",
        "settlement",
        "inference",
        "canonical_ir",
        "prose_settlement",
        "chapter_map",
    }
    raw_texts: list[str] = []
    meta_by_text: dict[str, dict[str, Any]] = {}
    for entry in entries or []:
        if isinstance(entry, dict):
            text = str(entry.get("text") or entry.get("claim") or "").strip()
            prov = str(
                entry.get("provenance")
                or entry.get("source")
                or default_provenance
                or ""
            ).strip().casefold()
            ref = entry.get("ref") or entry.get("evidence")
        else:
            text = str(entry or "").strip()
            prov = str(default_provenance or "").strip().casefold()
            ref = None
        if not text:
            continue
        raw_texts.append(text)
        meta_by_text[text] = {"provenance": prov, "ref": ref}

    # First: POV-clock on reveal-matching claims (blocks hidden truth aliases).
    clock_kept, clock_audit = evaluate_knowledge_full_audit(
        raw_texts, ir, chapter, source=source, target=target
    )
    clock_blocked = {
        str(a.get("claim") or "")
        for a in clock_audit
        if a.get("decision") in {"clamped", "unresolved_clock"}
    }

    kept: list[str] = []
    audit: list[dict[str, Any]] = list(clock_audit)
    for text in raw_texts:
        if text in clock_blocked:
            continue
        meta = meta_by_text.get(text) or {}
        prov = str(meta.get("provenance") or "").casefold()
        matched_reveal = any(
            a.get("claim") == text and a.get("decision") == "allowed"
            for a in clock_audit
        )
        if prov in allowed_prov or matched_reveal:
            kept.append(text)
            if not any(a.get("claim") == text for a in clock_audit):
                audit.append(
                    {
                        "claim": text[:240],
                        "target": target,
                        "decision": "allowed",
                        "provenance": prov or source,
                        "ref": meta.get("ref"),
                        "source": source,
                        "reason": "provenance_ok",
                        "current_chapter": chapter,
                    }
                )
            continue
        audit.append(
            {
                "claim": text[:240],
                "target": target,
                "decision": "omitted",
                "provenance": prov or None,
                "source": source,
                "reason": "missing_provenance",
                "current_chapter": chapter,
            }
        )
    # De-dupe kept
    dedup: list[str] = []
    for t in kept:
        if t not in dedup:
            dedup.append(t)
    return dedup, audit


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
    """What POV now knows/believes because prose N expressed it (verified).

    Reveal-clock clamp: observation may appear in prose, but knows_gained must
    not unlock facts before pov_knows_chapter.
    """
    pov = _pov_name(ir)
    knows: list[str] = []

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
    belief_entries: list[dict[str, Any]] = []
    for key in ("relationship_turn", "primary_turn"):
        text = str(inference.get(key) or "").strip()
        if text and _event_realized(text, claims_blob):
            belief_entries.append(
                {
                    "text": text,
                    "provenance": "observation",
                    "ref": f"inference.{key}",
                }
            )

    # Cognitive dissonance active for POV if still in psychology and referenced.
    misbelief_entries: list[dict[str, Any]] = []
    for row in ir.get("character_psychology") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("character") or "").strip() != pov:
            continue
        dissonance = str(row.get("cognitive_dissonance") or "").strip()
        if not dissonance:
            continue
        misbelief_entries.append(
            {
                "text": dissonance,
                "provenance": "psychology",
                "ref": "cognitive_dissonance",
            }
        )

    knows, knows_audit = evaluate_knowledge_full_audit(
        knows, ir, chapter, source="prose_settlement", target="character_state.knows"
    )
    believes, believes_audit = evaluate_belief_provenance(
        belief_entries,
        ir,
        chapter,
        source="prose_settlement",
        target="character_state.believes",
    )
    # Misbeliefs may be false, but must not alias hidden true facts before POV clock.
    misbeliefs, misbelief_audit = evaluate_belief_provenance(
        misbelief_entries,
        ir,
        chapter,
        source="prose_settlement",
        target="character_state.misbeliefs",
        default_provenance="psychology",
    )

    return {
        "character": pov,
        "knows_gained": knows,
        "believes_gained": believes,
        "misbeliefs_active": misbeliefs,
        "knows_clamped": [
            a for a in knows_audit if a.get("decision") in {"clamped", "unresolved_clock"}
        ],
        "believes_clamped": [
            a
            for a in believes_audit
            if a.get("decision") in {"clamped", "unresolved_clock", "omitted"}
        ],
        "misbeliefs_clamped": [
            a
            for a in misbelief_audit
            if a.get("decision") in {"clamped", "unresolved_clock", "omitted"}
        ],
        "knowledge_audit": knows_audit + believes_audit + misbelief_audit,
        "source": "prose_settlement",
        "authority_note": (
            "knows_gained is clamped by pov_knows_chapter only; "
            "reader_reveal_chapter is never knowledge authority; "
            "believes/misbeliefs require provenance; "
            "settlement cannot mint early knowledge"
        ),
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
                "allowed_actions": row.get("allowed_actions")
                or _allowed_actions_at(ir, prop, chapter),
                "actions_this_chapter": row.get("actions_this_chapter") or [],
                "source": source,
                "evidence": evidence,
            }
        )
    # Hard clamp: prose heuristics cannot invent holders/actions off CE schedule.
    clamped, audit = clamp_prop_updates_to_schedule(
        out, ir, chapter, source="prose_settlement", claims_blob=claims_blob
    )
    for row, verdict in zip(clamped, audit):
        row["custody_audit"] = verdict
    return clamped


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
    *,
    chapter: int | None = None,
    ir: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate N+1 intelligence so prose-N deltas become live state (not metadata).

    Defense in depth: re-clamp knows/believes against pov clocks at target chapter
    so a stale settlement cannot smuggle early knowledge forward.
    """
    out = deepcopy(bundle)
    deltas = (prior_settlement.get("character_updates") or {}).get("deltas") or {}
    pov = str(deltas.get("character") or "").strip()
    target_ch = int(chapter or out.get("chapter") or (prior_settlement.get("chapter") or 0) + 1)

    knows_in = [str(x) for x in (deltas.get("knows_gained") or [])]
    believes_in = [str(x) for x in (deltas.get("believes_gained") or [])]
    misbeliefs_in = [str(x) for x in (deltas.get("misbeliefs_active") or [])]
    apply_audit: list[dict[str, Any]] = []
    if ir is not None:
        knows_in, ka = evaluate_knowledge_full_audit(
            knows_in,
            ir,
            target_ch,
            source="settlement",
            target="character_state.knows",
        )
        believes_in, ba = evaluate_belief_provenance(
            believes_in,
            ir,
            target_ch,
            source="settlement",
            target="character_state.believes",
            default_provenance="settlement",
        )
        misbeliefs_in, ma = evaluate_belief_provenance(
            misbeliefs_in,
            ir,
            target_ch,
            source="settlement",
            target="character_state.misbeliefs",
            default_provenance="settlement",
        )
        apply_audit = ka + ba + ma

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
        for item in knows_in:
            _append_unique(knows, str(item))
        for item in believes_in:
            _append_unique(believes, str(item))
        for item in misbeliefs_in:
            _append_unique(misbeliefs, str(item))
        row["knows"] = knows
        row["believes"] = believes
        row["misbeliefs"] = misbeliefs
        row["continuity_source"] = "settlement"
    out["character_cognition"] = cognition
    out["character_state"] = cognition

    # Prop custody: settlement may update holders only when IR schedule/chain allows.
    prop_updates = prior_settlement.get("prop_updates") or []
    prop_audit: list[dict[str, Any]] = []
    if prop_updates and ir is not None:
        prop_updates, prop_audit = clamp_prop_updates_to_schedule(
            list(prop_updates),
            ir,
            target_ch,
            source="settlement",
        )
    if prop_updates:
        by_id = {
            str(p.get("prop_id") or ""): p for p in prop_updates if isinstance(p, dict)
        }
        merged_props = []
        for prop in out.get("prop_state") or []:
            row = deepcopy(prop)
            pid = str(row.get("prop_id") or "")
            upd = by_id.get(pid)
            if upd and upd.get("holder"):
                if upd.get("holder_clamped"):
                    # Keep IR projected holder; record clamp.
                    row["holder_source"] = "ir_schedule_clamp"
                    row["clamp_reason"] = upd.get("clamp_reason")
                elif str(upd.get("source") or "").startswith("prose") or upd.get(
                    "evidence"
                ):
                    row["holder"] = upd.get("holder")
                    row["holder_source"] = upd.get("source")
                    row["holder_evidence"] = upd.get("evidence")
                elif not row.get("holder"):
                    row["holder"] = upd.get("holder")
            merged_props.append(row)
        seen = {str(p.get("prop_id") or "") for p in merged_props}
        for pid, upd in by_id.items():
            if pid and pid not in seen and not upd.get("holder_clamped"):
                merged_props.append(deepcopy(upd))
        out["prop_state"] = merged_props
        out["prop_custody_audit"] = prop_audit

    strategy = deepcopy(prior_settlement.get("strategy_updates") or {})
    # Clamp continuity channels that are not character_state.knows.
    raw_events = [
        e
        for e in (prior_settlement.get("events_realized") or [])
        if isinstance(e, dict)
    ]
    event_actions = [str(e.get("action") or "").strip() for e in raw_events]
    event_kept, event_audit = (
        evaluate_knowledge_full_audit(
            event_actions,
            ir,
            target_ch,
            source="settlement",
            target="events_realized",
        )
        if ir is not None
        else (event_actions, [])
    )
    apply_audit.extend(event_audit)
    event_kept_set = set(event_kept)
    filtered_events = [
        e for e in raw_events if str(e.get("action") or "").strip() in event_kept_set
    ]

    realized_moves = [
        str(x)
        for x in (
            strategy.get("realized_moves")
            or [str(e.get("action") or "") for e in filtered_events]
        )
        if str(x).strip()
    ]
    if ir is not None:
        realized_moves, rm_audit = evaluate_knowledge_full_audit(
            realized_moves,
            ir,
            target_ch,
            source="settlement",
            target="moves.prior_realized",
        )
        apply_audit.extend(rm_audit)
    strategy["realized_moves"] = realized_moves

    open_pressure = strategy.get("open_pressure")
    if open_pressure and ir is not None:
        op_kept, op_audit = evaluate_knowledge_full_audit(
            [str(open_pressure)],
            ir,
            target_ch,
            source="settlement",
            target="moves.open_pressure",
        )
        apply_audit.extend(op_audit)
        open_pressure = op_kept[0] if op_kept else None
        strategy["open_pressure"] = open_pressure

    apply_clamped = [
        a for a in apply_audit if a.get("decision") in {"clamped", "unresolved_clock"}
    ]
    for row in out.get("character_state") or []:
        if not isinstance(row, dict):
            continue
        if pov and str(row.get("character") or "").strip() not in {"", pov}:
            continue
        if apply_audit:
            row["knowledge_audit_on_apply"] = apply_audit
        if apply_clamped:
            row["knowledge_clamped_on_apply"] = apply_clamped

    moves = deepcopy(out.get("moves") or {})
    moves["prior_realized"] = realized_moves
    moves["power_delta"] = {
        **(moves.get("power_delta") or {}),
        "incoming": (strategy.get("power_delta") or prior_settlement.get("power_delta")),
        "note": "incoming from chapter N settlement; projected is for this chapter",
    }
    if open_pressure:
        pov_obs = dict(moves.get("pov_observation") or {})
        items = list(pov_obs.get("items") or [])
        _append_unique(
            items, f"[from ch{prior_settlement.get('chapter')}] {open_pressure}"
        )
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
        "events_realized": filtered_events,
        "character_updates": {
            "deltas": {
                "character": pov,
                "knows_gained": knows_in,
                "believes_gained": believes_in,
                "misbeliefs_active": misbeliefs_in,
            }
        },
        "prop_updates": prop_updates,
        "strategy_updates": strategy,
        "honeytoken_state": prior_settlement.get("honeytoken_state"),
        "relationship_delta": prior_settlement.get("relationship_delta"),
        "power_delta_realized": prior_settlement.get("power_delta"),
        "continuity_source": "settlement",
        "applied_to_live_state": True,
        "knowledge_audit_on_apply": apply_audit,
        "knowledge_clamped_on_apply": apply_clamped,
        "prop_custody_audit": prop_audit,
        "applied_at_chapter": target_ch,
    }
    out["continuity_authority"] = "settlement"
    return out
