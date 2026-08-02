"""Hard structural gates for plan claims — unmapped claims are UNRESOLVED (no seal)."""

from __future__ import annotations

import re
from typing import Any

from factory.engine.lib.canonical_ir import entity_names

_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_CLUE_ID_RE = re.compile(r"\b(C\d+)\b")
_PROP_ID_RE = re.compile(r"\b(P\d+)\b")
_REVEAL_ID_RE = re.compile(r"\b(R\d+)\b")
_ACTOR_VERB_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+"
    r"(opens?|closes?|gives?|takes?|plants?|kills?|hires?|reveals?|"
    r"discovers?|creates?|returns?|binds?|admits?|produces?|grants?|"
    r"deletes?|observes?|notes?|recalls?|says?|forces?)\b",
    re.I,
)
_MOTIVE_SWAP_RE = re.compile(
    r"\b(?:worthy\s+partner|test(?:ing)?\s+whether\s+.+\s+partner|"
    r"orchestrated\s+the\s+entire\s+confrontation\s+to\s+test)\b",
    re.I,
)

_COMMON_CAPS = frozenset(
    {
        "The",
        "Chapter",
        "Day",
        "Zero",
        "Crisis",
        "Mutual",
        "Assured",
        "Destruction",
        "Server",
        "Phone",
        "Office",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
)


def _unresolved(
    *,
    field: str,
    claim: str,
    reason: str,
    detail: str = "",
) -> dict[str, Any]:
    row = {
        "field": field,
        "claim": claim[:320],
        "reason": reason,
        "status": "UNRESOLVED",
        "authority": "LLM_PROPOSAL",
        "severity": "block",
    }
    if detail:
        row["detail"] = detail
    return row


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
        "him",
        "was",
        "were",
        "the",
        "and",
        "for",
        "office",
        "knows",
        "knew",
        "entering",
        "leaves",
        "leave",
    }
)


def _content_tokens(text: str, drop: set[str] | None = None) -> set[str]:
    drop = drop or set()
    out = set()
    for w in re.findall(r"[a-z0-9']{4,}", text.casefold()):
        if w in _STOP or w in drop:
            continue
        out.add(w)
    return out


def _token_overlap(a: str, b: str, *, drop: set[str] | None = None) -> float:
    wa = _content_tokens(a, drop)
    wb = _content_tokens(b, drop)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def _shared_phrase(a: str, b: str, *, min_words: int = 3) -> bool:
    """True if a distinctive 3+ word window from b appears in a."""
    b_words = [
        w
        for w in re.findall(r"[a-z0-9']+", b.casefold())
        if w not in _STOP and len(w) >= 4
    ]
    a_cf = f" {a.casefold()} "
    for i in range(0, max(0, len(b_words) - min_words + 1)):
        window = b_words[i : i + min_words]
        if len(window) < min_words:
            continue
        needle = " ".join(window)
        if needle in a_cf:
            return True
    return False


def _fact_stated(text: str, fact: str, *, drop: set[str] | None = None) -> bool:
    if _shared_phrase(text, fact):
        return True
    return _token_overlap(text, fact, drop=drop) >= 0.75 and len(
        _content_tokens(fact, drop) & _content_tokens(text, drop)
    ) >= 3


def _entity_ok(name: str, allowed: set[str]) -> bool:
    if name in allowed:
        return True
    if name.split()[0] in _COMMON_CAPS:
        return True
    if any(name == ent or name in ent.split() for ent in allowed):
        return True
    # Title-ish compounds already in allow set as first tokens
    first = name.split()[0]
    if first in allowed and len(name.split()) == 1:
        return True
    return False


def hard_gate_plan_against_ir(
    plan: dict[str, Any],
    ir: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return UNRESOLVED blockers. Empty list means hard gates pass."""
    chapter = int(plan.get("chapter") or 0)
    allowed = entity_names(ir)
    title = str(ir.get("title") or "")
    for tok in re.findall(r"[A-Z][a-z]+", title):
        allowed.add(tok)
    # World props / places that are named in IR
    for prop in ir.get("props") or []:
        name = str(prop.get("name") or "").strip()
        if name:
            allowed.add(name)
            for part in name.split():
                if part[:1].isupper():
                    allowed.add(part)

    unresolved: list[dict[str, Any]] = []
    true_plot = str((ir.get("plots") or {}).get("true_plot") or "")
    reveals = list(ir.get("reveal_schedule") or [])
    clues = {str(c.get("id") or ""): c for c in (ir.get("clues") or []) if isinstance(c, dict)}
    props = {str(p.get("id") or ""): p for p in (ir.get("props") or []) if isinstance(p, dict)}
    entity_drop = {n.casefold() for n in allowed}
    for name in list(allowed):
        for part in name.casefold().split():
            if len(part) >= 3:
                entity_drop.add(part)

    texts: list[tuple[str, str]] = []
    for field in (
        "title",
        "one_line_summary",
        "beat_summary",
        "opens_with",
        "cliffhanger",
        "chapter_task",
        "signature_detail_hint",
        "carries_to_next",
        "spice_note",
    ):
        val = str(plan.get(field) or "").strip()
        if val:
            texts.append((field, val))
    for i, item in enumerate(plan.get("must_happen") or []):
        texts.append((f"must_happen[{i}]", str(item)))
    for i, item in enumerate(plan.get("must_not") or []):
        texts.append((f"must_not[{i}]", str(item)))

    for field, text in texts:
        # 1) Named-entity membership — every multi-word proper noun must map.
        for m in _PROPER_NOUN_RE.finditer(text):
            name = m.group(1)
            if not _entity_ok(name, allowed):
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=name,
                        reason="named_entity_membership",
                        detail="proper noun not in IR entities/props",
                    )
                )

        # 2) Reveal-chapter timing — stating a future reveal fact / id.
        for m in _REVEAL_ID_RE.finditer(text):
            rid = m.group(1)
            row = next((r for r in reveals if str(r.get("id") or "") == rid), None)
            if row is None:
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=rid,
                        reason="named_entity_membership",
                        detail="reveal id not in IR",
                    )
                )
            else:
                reader_ch = int(row.get("reader_reveal_chapter") or row.get("chapter") or 1)
                if chapter < reader_ch:
                    unresolved.append(
                        _unresolved(
                            field=field,
                            claim=text,
                            reason="reveal_chapter_timing",
                            detail=f"{rid} unlocks at ch{reader_ch}",
                        )
                    )
        for row in reveals:
            fact = str(row.get("fact") or "").strip()
            reader_ch = int(row.get("reader_reveal_chapter") or row.get("chapter") or 1)
            if not fact or chapter >= reader_ch:
                continue
            if _fact_stated(text, fact, drop=entity_drop):
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="reveal_chapter_timing",
                        detail=f"{row.get('id')} fact overlap before unlock",
                    )
                )

        # 3) POV-knowledge timing — claiming POV knows a fact before pov_knows_chapter.
        pov_name = str((ir.get("pov") or {}).get("character") or "").split()[0]
        for row in reveals:
            fact = str(row.get("fact") or "").strip()
            pov_ch = int(row.get("pov_knows_chapter") or 0)
            if not fact or not pov_ch or chapter >= pov_ch:
                continue
            if not _fact_stated(text, fact, drop=entity_drop):
                continue
            # Only flag if text attributes knowledge to POV / first person framing.
            if re.search(
                rf"\b({re.escape(pov_name)}|I|she|he)\b.{{0,40}}\b(knows?|knew|realizes?|realized|discovers?|discovered)\b",
                text,
                re.I,
            ) or re.search(
                rf"\b(knows?|knew|realizes?|realized)\b.{{0,40}}\b({re.escape(pov_name)}|I)\b",
                text,
                re.I,
            ):
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="pov_knowledge_timing",
                        detail=f"{row.get('id')} pov_knows_chapter={pov_ch}",
                    )
                )

        # 4) Clue plant / payoff timing.
        for m in _CLUE_ID_RE.finditer(text):
            cid = m.group(1)
            clue = clues.get(cid)
            if clue is None:
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=cid,
                        reason="named_entity_membership",
                        detail="clue id not in IR",
                    )
                )
                continue
            plant = int(clue.get("plant_chapter") or 0)
            payoff = int(clue.get("payoff_chapter") or 0)
            planting = bool(re.search(r"\b(plant|plants|planting|introduces?)\b", text, re.I))
            paying = bool(re.search(r"\b(pay\s*off|pays\s*off|reveals?\s+true|true\s+meaning)\b", text, re.I))
            if planting and plant and chapter < plant:
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="clue_plant_payoff",
                        detail=f"{cid} plant_chapter={plant}",
                    )
                )
            if paying and payoff and chapter < payoff:
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="clue_plant_payoff",
                        detail=f"{cid} payoff_chapter={payoff}",
                    )
                )
            if chapter < plant and not planting and not paying:
                # Referencing a not-yet-planted clue is unresolved.
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="clue_plant_payoff",
                        detail=f"{cid} not planted until ch{plant}",
                    )
                )

        # 5) Prop holder binding.
        for m in _PROP_ID_RE.finditer(text):
            pid = m.group(1)
            prop = props.get(pid)
            if prop is None:
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=pid,
                        reason="named_entity_membership",
                        detail="prop id not in IR",
                    )
                )
                continue
            owners = prop.get("physical_owner_by_chapter") or {}
            holder = None
            candidates = []
            for k, v in owners.items():
                try:
                    ck = int(k)
                except (TypeError, ValueError):
                    continue
                if ck <= chapter:
                    candidates.append((ck, str(v)))
            if candidates:
                holder = sorted(candidates)[-1][1]
            # "X holds/has/keeps P#" mismatch
            hold_m = re.search(
                rf"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:holds?|has|keeps?|retains?)\s+{pid}\b",
                text,
            )
            if hold_m and holder:
                actor = hold_m.group(1)
                if actor.casefold() not in holder.casefold() and holder.casefold() not in actor.casefold():
                    unresolved.append(
                        _unresolved(
                            field=field,
                            claim=text,
                            reason="prop_holder",
                            detail=f"{pid} holder at ch{chapter} is {holder}, not {actor}",
                        )
                    )

        # 6) Actor–action binding on must_happen.
        if field.startswith("must_happen"):
            actors_found = []
            for m in _ACTOR_VERB_RE.finditer(text):
                actor = m.group(1)
                # Skip leading "The/A" style false positives already filtered by regex.
                if actor.split()[0] in _COMMON_CAPS:
                    continue
                actors_found.append(actor)
                if not _entity_ok(actor, allowed) and actor not in allowed:
                    # First name only: check against entity first tokens
                    if actor not in allowed:
                        unresolved.append(
                            _unresolved(
                                field=field,
                                claim=text,
                                reason="actor_action_binding",
                                detail=f"actor '{actor}' not in IR cast",
                            )
                        )
            # must_happen with a finite verb but no recognizable cast actor → unresolved
            if re.search(
                r"\b(opens?|kills?|hires?|plants?|creates?|reveals?|discovers?)\b",
                text,
                re.I,
            ) and not actors_found:
                # Allow passive / impersonal if no proper-noun actor expected
                if _PROPER_NOUN_RE.search(text) or re.search(r"\b[A-Z][a-z]+\b", text):
                    # Has capitalized tokens that didn't bind as actors
                    caps = [
                        m.group(0)
                        for m in re.finditer(r"\b[A-Z][a-z]+\b", text)
                        if m.group(0) not in _COMMON_CAPS
                    ]
                    if caps and not any(_entity_ok(c, allowed) or c in allowed for c in caps):
                        unresolved.append(
                            _unresolved(
                                field=field,
                                claim=text,
                                reason="actor_action_binding",
                                detail="action verb without IR-bound actor",
                            )
                        )

        # 7) Motive ↔ true_plot actor binding.
        if _MOTIVE_SWAP_RE.search(text):
            if "server" in true_plot.casefold() or "archive" in true_plot.casefold():
                unresolved.append(
                    _unresolved(
                        field=field,
                        claim=text,
                        reason="motive_true_plot_actor_binding",
                        detail="partner-test motive conflicts with true_plot server/archive goal",
                    )
                )
            else:
                # Motive claim that cannot be mapped onto true_plot actors/goals
                if _token_overlap(text, true_plot, drop=entity_drop) < 0.25:
                    unresolved.append(
                        _unresolved(
                            field=field,
                            claim=text,
                            reason="motive_true_plot_actor_binding",
                            detail="motive claim does not map to true_plot",
                        )
                    )

    # Deduplicate
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in unresolved:
        key = f"{row.get('reason')}:{row.get('field')}:{row.get('claim')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
