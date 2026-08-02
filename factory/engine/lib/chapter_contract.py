"""Deterministic chapter contract + writer packet from sealed plan + IR."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from factory.engine.lib.canonical_ir import (
    entity_names,
    facts_available_by_chapter,
    load_canonical_ir,
    sha256_obj,
)
from factory.engine.lib.canon_artifacts import (
    artifact_path,
    is_sealed,
    is_stale,
    make_seal,
    read_json,
    write_json,
)


def _chapter_map_entry(ir: dict[str, Any], chapter: int) -> dict[str, Any]:
    cmap = ir.get("chapter_map") or {}
    if not isinstance(cmap, dict):
        return {}
    for key in (chapter, str(chapter), f"{chapter:02d}"):
        if key in cmap and isinstance(cmap[key], dict):
            return deepcopy(cmap[key])
    return {}


def _excluded_reveals(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    out = []
    for row in ir.get("reveal_schedule") or []:
        if not isinstance(row, dict):
            continue
        reader_ch = int(row.get("reader_reveal_chapter") or row.get("chapter") or 0)
        hidden_before = int(row.get("must_remain_hidden_before") or 0)
        if reader_ch > chapter or (hidden_before and chapter <= hidden_before):
            out.append(
                {
                    "id": row.get("id"),
                    "fact": row.get("fact"),
                    "reader_reveal_chapter": reader_ch,
                }
            )
    return out


def _visible_facts(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    """Facts Writer may use — exclude unrevealed true meanings / future reveals."""
    excluded_ids = {
        f"F_REVEAL_{r.get('id')}"
        for r in _excluded_reveals(ir, chapter)
        if r.get("id")
    }
    # Plot-spine fields that often encode endgame spoilers — Writer gets
    # chapter_map/obligations instead; validators keep full IR.
    writer_blocked_plot = {
        "F_PLOT_LOGLINE",
        "F_PLOT_TRUE_PLOT",
        "F_PLOT_ENDING_BOOK1",
        "F_PLOT_HOOK_BOOK2",
    }
    visible = []
    for fact in facts_available_by_chapter(ir, chapter):
        fid = str(fact.get("fact_id") or "")
        if fid in excluded_ids or fid in writer_blocked_plot:
            continue
        # Villain private knowledge is validator-side only.
        if fid.startswith("F_VILLAIN_"):
            continue
        # Hide true_meaning payloads before payoff
        meta = fact.get("meta") or {}
        if fact.get("kind") == "clue":
            payoff = int(meta.get("payoff_chapter") or 0)
            # description OK at plant; strip true meaning from meta for writer
            row = deepcopy(fact)
            if payoff and chapter < payoff and isinstance(row.get("meta"), dict):
                row["meta"].pop("true_meaning_at_payoff", None)
            visible.append(row)
        elif fact.get("kind") == "plot" and fid == "F_PLOT_TRUE_PLOT":
            continue  # never dump true_plot into writer packet
        elif fact.get("kind") == "entity":
            # Strip role spoilers like "hidden mastermind" from Writer view.
            row = deepcopy(fact)
            name = str((row.get("meta") or {}).get("name") or "").strip()
            if name:
                row["claim"] = name
            visible.append(row)
        elif fact.get("kind") == "psychology":
            claim = str(fact.get("claim") or "").casefold()
            if any(
                tok in claim
                for tok in ("hidden mastermind", "secretly hired", "true goal")
            ):
                # Ungated psychology spoilers stay off Writer packet.
                continue
            visible.append(fact)
        else:
            visible.append(fact)
    # Future-chapter must_include_by_chapter.* stays off Writer packet.
    filtered: list[dict[str, Any]] = []
    for f in visible:
        keep = True
        for ref in f.get("source_refs") or []:
            if str(ref).startswith("must_include_by_chapter."):
                try:
                    ch_key = int(str(ref).split(".")[-1])
                except ValueError:
                    ch_key = 0
                if ch_key > chapter:
                    keep = False
        if keep:
            filtered.append(f)
    return filtered


def _required_events(ir: dict[str, Any], chapter: int, plan: dict[str, Any]) -> list[str]:
    events: list[str] = []
    entry = _chapter_map_entry(ir, chapter)
    for item in entry.get("must_happen") or []:
        events.append(str(item))
    for item in plan.get("must_happen") or []:
        text = str(item)
        if text not in events:
            events.append(text)
    by_ch = ir.get("must_include_by_chapter") or {}
    for item in by_ch.get(str(chapter)) or by_ch.get(chapter) or []:
        text = str(item)
        if text and text not in events:
            events.append(text)
    return events


def compile_chapter_contract(
    ir: dict[str, Any],
    plan: dict[str, Any],
    *,
    chapter: int,
    verified_state: dict[str, Any] | None = None,
    intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = _chapter_map_entry(ir, chapter)
    visible = _visible_facts(ir, chapter)
    excluded = _excluded_reveals(ir, chapter)
    contract: dict[str, Any] = {
        "contract_version": "1.0",
        "chapter": chapter,
        "parent_ir_digest": ir.get("ir_digest"),
        "pov": deepcopy(ir.get("pov") or {}),
        "chapter_map_entry": entry,
        "visible_facts": [
            {
                "fact_id": f.get("fact_id"),
                "claim": f.get("claim"),
                "kind": f.get("kind"),
                "source_refs": f.get("source_refs"),
            }
            for f in visible
        ],
        "excluded_facts": excluded,
        "required_events": _required_events(ir, chapter, plan),
        "must_avoid": deepcopy(ir.get("must_avoid") or []),
        "entities": deepcopy(ir.get("entities") or []),
        "prop_actions": deepcopy(entry.get("prop_actions") or []),
        "clue_ids_planted": deepcopy(entry.get("clue_ids_planted") or []),
        "clue_ids_paid_off": deepcopy(entry.get("clue_ids_paid_off") or []),
        "reveal_ids_opened": deepcopy(entry.get("reveal_ids_opened") or []),
        "relationship_turn": entry.get("relationship_turn"),
        "primary_turn": entry.get("primary_turn"),
        "plan_refs": {
            "title": plan.get("title"),
            "one_line_summary": plan.get("one_line_summary"),
            "must_happen": plan.get("must_happen"),
            "must_not": plan.get("must_not"),
        },
        "allowed_creative_space": {
            "sensory_detail": True,
            "incidental_unnamed_actions": True,
            "new_named_people": False,
            "new_medical_facts": False,
            "new_backstory": False,
            "new_evidence": False,
            "new_locations": False,
            "new_technical_mechanisms": False,
        },
        "verified_state_digest": sha256_obj(verified_state or {}),
    }
    if intelligence:
        contract["intelligence"] = intelligence
    contract["contract_digest"] = sha256_obj(
        {k: v for k, v in contract.items() if k != "contract_digest"}
    )
    return contract


_SPOILER_ROLE_TOKENS = (
    "hidden mastermind",
    "secretly hired",
    "true mastermind",
    "mastermind who hired",
)


def _sanitize_entity_for_writer(ent: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(ent)
    role = str(row.get("role") or "")
    cf = role.casefold()
    if any(tok in cf for tok in _SPOILER_ROLE_TOKENS) or "mastermind" in cf:
        # Keep public function; drop spoiler role tags.
        parts = [p.strip() for p in role.split("/") if p.strip()]
        clean = [p for p in parts if "mastermind" not in p.casefold()]
        row["role"] = " / ".join(clean) if clean else "character"
    return row


def _scrub_psychology_for_writer(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = deepcopy(row)
        traits = item.get("core_traits")
        if isinstance(traits, list):
            item["core_traits"] = [
                t
                for t in traits
                if "mastermind" not in str(t).casefold()
                and "secretly" not in str(t).casefold()
            ]
        out.append(item)
    return out


def compile_writer_packet(
    contract: dict[str, Any],
    *,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Writer-safe packet: locked/future reveals are omitted entirely (not listed as hidden)."""
    chapter = int(contract.get("chapter") or 0)
    # Validator keeps excluded_facts on the contract; Writer must not see ids/text.
    hidden_count = len(contract.get("excluded_facts") or [])
    entities = [
        _sanitize_entity_for_writer(e)
        for e in (contract.get("entities") or [])
        if isinstance(e, dict)
    ]
    packet = {
        "packet_version": "1.0",
        "chapter": chapter,
        "parent_contract_digest": contract.get("contract_digest"),
        "pov": contract.get("pov"),
        "visible_facts": contract.get("visible_facts"),
        # Opaque count only — no reveal ids, no fact text, no spoilers.
        "hidden_future_reveal_count": hidden_count,
        "required_events": contract.get("required_events"),
        "must_avoid": contract.get("must_avoid"),
        "entities": entities,
        "prop_actions": contract.get("prop_actions"),
        "relationship_turn": contract.get("relationship_turn"),
        "primary_turn": contract.get("primary_turn"),
        "plan_refs": contract.get("plan_refs"),
        "allowed_creative_space": contract.get("allowed_creative_space"),
        "intelligence": _writer_safe_intelligence(contract.get("intelligence") or {}),
        "style": style or {},
        "output_contract": {
            "format": "plain_prose",
            "min_words": 1250,
        },
    }
    packet["packet_digest"] = sha256_obj(
        {k: v for k, v in packet.items() if k != "packet_digest"}
    )
    return packet


def _writer_safe_intelligence(intel: dict[str, Any]) -> dict[str, Any]:
    """Drop fields that can re-introduce locked secrets into the Writer view."""
    if not intel:
        return {}
    safe = {
        "prop_state": intel.get("prop_state"),
        "honeytoken_state": intel.get("honeytoken_state"),
        "psychology_active": _scrub_psychology_for_writer(intel.get("psychology_active")),
        "body_condition_active": intel.get("body_condition_active"),
        "romance_doctrine": intel.get("romance_doctrine"),
        "moves": intel.get("moves"),
        # Villain private knowledge stays on contract/validator side only.
    }
    honey = safe.get("honeytoken_state")
    if isinstance(honey, dict) and "hidden" in honey:
        honey = dict(honey)
        honey.pop("hidden", None)
        safe["honeytoken_state"] = honey
    return safe


def render_writer_prompt_from_packet(packet: dict[str, Any]) -> str:
    """Human/debug render — not SoT."""
    lines = [
        f"# CHAPTER {packet.get('chapter')} — WRITER PACKET (machine authority)",
        "",
        "Use ONLY visible_facts, required_events, entities, and allowed_creative_space.",
        "Do NOT invent named people, medical specifics, backstory, locations, or evidence.",
        "Future/locked reveals are omitted from this packet — do not invent them.",
        "",
        "## PACKET JSON",
        "```json",
        json.dumps(packet, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)


def build_and_seal_chapter_artifacts(
    ws: Path,
    book: int,
    chapter: int,
    plan: dict[str, Any],
    *,
    ir: dict[str, Any] | None = None,
    verified_state: dict[str, Any] | None = None,
    intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ir = ir or load_canonical_ir(ws)
    if not ir:
        raise RuntimeError("canonical IR missing")

    approval = read_json(artifact_path(ws, book, chapter, "plan.approval.json"))
    if not is_sealed(approval):
        raise RuntimeError(f"ch{chapter}: plan not sealed")
    if is_stale(approval, str(ir.get("ir_digest") or "")):
        raise RuntimeError(f"ch{chapter}: plan approval stale vs IR")

    repaired = read_json(artifact_path(ws, book, chapter, "plan.repaired.json")) or plan
    contract = compile_chapter_contract(
        ir,
        repaired,
        chapter=chapter,
        verified_state=verified_state,
        intelligence=intelligence,
    )
    packet = compile_writer_packet(contract)
    write_json(artifact_path(ws, book, chapter, "contract.json"), contract)
    write_json(artifact_path(ws, book, chapter, "writer_request.json"), packet)
    prompt = render_writer_prompt_from_packet(packet)
    write_json(
        artifact_path(ws, book, chapter, "contract.approval.json"),
        make_seal(
            status="sealed",
            source_ir_hash=str(ir.get("ir_digest") or ""),
            artifact_hash=str(contract.get("contract_digest") or ""),
            validators={"contract_compiler": "pass"},
        ),
    )
    return {"contract": contract, "packet": packet, "prompt": prompt}


def load_writer_packet(ws: Path, book: int, chapter: int) -> dict[str, Any] | None:
    return read_json(artifact_path(ws, book, chapter, "writer_request.json"))


def assert_writer_artifacts_ready(ws: Path, book: int, chapter: int, ir_digest: str) -> None:
    approval = read_json(artifact_path(ws, book, chapter, "plan.approval.json"))
    if not is_sealed(approval):
        raise RuntimeError(f"Writer blocked: ch{chapter} plan not sealed")
    if is_stale(approval, ir_digest):
        raise RuntimeError(f"Writer blocked: ch{chapter} plan stale")
    packet = load_writer_packet(ws, book, chapter)
    if not packet:
        raise RuntimeError(f"Writer blocked: ch{chapter} missing writer_request.json")
    c_approval = read_json(artifact_path(ws, book, chapter, "contract.approval.json"))
    if c_approval and is_stale(c_approval, ir_digest):
        raise RuntimeError(f"Writer blocked: ch{chapter} contract stale")
