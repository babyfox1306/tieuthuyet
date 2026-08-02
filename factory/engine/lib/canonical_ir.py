"""Canonical IR ingest — CE YAML → provenance-bearing fact registry.

IR is the root Source of Truth for the canon pipeline. Intent manifest may
mirror a subset for legacy consumers.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

IMPORTER_VERSION = "1.0.0"
IR_SCHEMA_VERSION = "1.0"

# Top-level keys the importer understands for the current schema_version.
KNOWN_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "concept_status",
        "title",
        "pen_name",
        "romance_mode",
        "spice_level",
        "spice_default",
        "spice_schedule",
        "pov",
        "canonical_reveal_chapter",
        "corpse_reveal_chapter",
        "chapter_count",
        "intentional_early_reveal",
        "author_directive",
        "logline",
        "surface_plot",
        "true_plot",
        "ending_book1",
        "hook_book2",
        "psychological_condition",
        "character_psychology",
        "villain_ledger",
        "characters",
        "cast",
        "reveal_schedule",
        "required_reveal_schedule",
        "clues",
        "props",
        "honeytoken",
        "chapter_map",
        "must_include",
        "must_include_by_chapter",
        "must_avoid",
        "notes",
        "romance_doctrine",
        "threshold_events",
        "arc_shape",
        "setting_graph",
        "final_supernatural_residue",
        "target_language",
        "genre",
        "format",
        "reveal_ladder",
    }
)

# Known keys that must be consumed into IR (blocking if present but dropped).
REQUIRED_CONSUME_IF_PRESENT = frozenset(
    {
        "title",
        "pov",
        "chapter_count",
        "chapter_map",
        "characters",
        "reveal_schedule",
        "clues",
        "props",
        "honeytoken",
        "character_psychology",
        "psychological_condition",
        "villain_ledger",
        "must_include",
        "must_include_by_chapter",
        "must_avoid",
        "surface_plot",
        "true_plot",
        "ending_book1",
        "logline",
    }
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_obj(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return sha256_text(blob)


def ir_paths(ws: Path) -> dict[str, Path]:
    bible = ws / "bible"
    source = ws / "source"
    return {
        "source_concept": source / "concept.yaml",
        "canonical_ir": bible / "canonical_ir.json",
        "ingest_report": bible / "ingest_report.json",
    }


def load_yaml_concept(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("concept.yaml must be a mapping")
    return data, raw


def _coverage_row(
    source_path: str,
    *,
    status: str,
    target_path: str | None = None,
    severity: str | None = None,
    note: str | None = None,
    value_preview: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_path": source_path,
        "status": status,
    }
    if target_path:
        row["target_path"] = target_path
    if severity:
        row["severity"] = severity
    if note:
        row["note"] = note
    if value_preview is not None:
        row["value_preview"] = value_preview[:160]
    return row


def _preview(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)[:160]


def _walk_paths(obj: Any, prefix: str = "") -> list[str]:
    """Enumerate coverage paths (top + one level of list indices / dict keys)."""
    paths: list[str] = []
    if prefix:
        paths.append(prefix)
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.append(child)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                for i, item in enumerate(val):
                    paths.append(f"{child}[{i}]")
                    if isinstance(item, dict):
                        for sk in item.keys():
                            paths.append(f"{child}[{i}].{sk}")
            elif isinstance(val, dict):
                for sk in val.keys():
                    paths.append(f"{child}.{sk}")
    return paths


def _add_fact(
    facts: list[dict[str, Any]],
    *,
    fact_id: str,
    claim: str,
    source_refs: list[str],
    available_from_chapter: int = 1,
    canon_class: str = "source_explicit",
    kind: str = "general",
    meta: dict[str, Any] | None = None,
) -> None:
    claim = str(claim or "").strip()
    if not claim:
        return
    row: dict[str, Any] = {
        "fact_id": fact_id,
        "claim": claim,
        "source_refs": source_refs,
        "available_from_chapter": int(available_from_chapter or 1),
        "canon_class": canon_class,
        "kind": kind,
    }
    if meta:
        row["meta"] = meta
    facts.append(row)


def build_fact_registry(concept: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    for key in (
        "logline",
        "surface_plot",
        "true_plot",
        "ending_book1",
        "hook_book2",
        "author_directive",
        "notes",
    ):
        val = str(concept.get(key) or "").strip()
        if val:
            _add_fact(
                facts,
                fact_id=f"F_PLOT_{key.upper()}",
                claim=val,
                source_refs=[key],
                available_from_chapter=1,
                kind="plot",
            )

    for item in concept.get("must_avoid") or []:
        text = str(item).strip()
        if text:
            _add_fact(
                facts,
                fact_id=f"F_AVOID_{sha256_text(text)[:8]}",
                claim=text,
                source_refs=["must_avoid"],
                kind="constraint",
                meta={"polarity": "forbidden"},
            )

    for item in concept.get("must_include") or []:
        text = str(item).strip()
        if text:
            _add_fact(
                facts,
                fact_id=f"F_MUST_{sha256_text(text)[:8]}",
                claim=text,
                source_refs=["must_include"],
                kind="obligation",
            )

    by_ch = concept.get("must_include_by_chapter") or {}
    if isinstance(by_ch, dict):
        for ch_key, items in by_ch.items():
            try:
                ch = int(ch_key)
            except (TypeError, ValueError):
                continue
            for item in items or []:
                text = str(item).strip()
                if not text:
                    continue
                _add_fact(
                    facts,
                    fact_id=f"F_MUST_CH{ch}_{sha256_text(text)[:8]}",
                    claim=text,
                    source_refs=[f"must_include_by_chapter.{ch_key}"],
                    available_from_chapter=ch,
                    kind="obligation",
                )

    for i, row in enumerate(concept.get("characters") or concept.get("cast") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        role = str(row.get("role") or "").strip()
        _add_fact(
            facts,
            fact_id=f"F_CAST_{sha256_text(name)[:8]}",
            claim=f"{name}" + (f" — {role}" if role else ""),
            source_refs=[f"characters[{i}].name"],
            kind="entity",
            meta={"name": name, "role": role},
        )

    for i, row in enumerate(concept.get("character_psychology") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("character") or "").strip()
        for field in (
            "core_need",
            "core_fear",
            "coping_mechanism",
            "cognitive_dissonance",
        ):
            val = str(row.get(field) or "").strip()
            if val:
                _add_fact(
                    facts,
                    fact_id=f"F_PSY_{i}_{field}",
                    claim=f"{name}: {field}={val}",
                    source_refs=[f"character_psychology[{i}].{field}"],
                    kind="psychology",
                    meta={"character": name, "field": field},
                )
        for field in ("core_traits", "stress_responses", "behavioral_constraints"):
            for j, item in enumerate(row.get(field) or []):
                text = str(item).strip()
                if text:
                    _add_fact(
                        facts,
                        fact_id=f"F_PSY_{i}_{field}_{j}",
                        claim=f"{name}: {text}",
                        source_refs=[f"character_psychology[{i}].{field}[{j}]"],
                        kind="psychology",
                        meta={"character": name, "field": field},
                    )

    cond = concept.get("psychological_condition")
    if isinstance(cond, dict):
        can = str(cond.get("canonical") or "").strip()
        if can:
            _add_fact(
                facts,
                fact_id="F_BODY_CANONICAL",
                claim=can,
                source_refs=["psychological_condition.canonical"],
                kind="body",
            )
        for j, item in enumerate(cond.get("observable_effects") or []):
            text = str(item).strip()
            if text:
                _add_fact(
                    facts,
                    fact_id=f"F_BODY_FX_{j}",
                    claim=text,
                    source_refs=[f"psychological_condition.observable_effects[{j}]"],
                    kind="body",
                )
        for j, item in enumerate(cond.get("must_not_be_described_as") or []):
            text = str(item).strip()
            if text:
                _add_fact(
                    facts,
                    fact_id=f"F_BODY_FORBID_{j}",
                    claim=text,
                    source_refs=[
                        f"psychological_condition.must_not_be_described_as[{j}]"
                    ],
                    kind="constraint",
                    meta={"polarity": "forbidden"},
                )

    for i, row in enumerate(concept.get("villain_ledger") or []):
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").strip()
        if action:
            ch_from = int(row.get("chapter_from") or 1)
            _add_fact(
                facts,
                fact_id=f"F_VILLAIN_{i}",
                claim=action,
                source_refs=[f"villain_ledger[{i}]"],
                available_from_chapter=ch_from,
                kind="villain",
                meta={
                    k: row.get(k)
                    for k in (
                        "phase",
                        "chapter_from",
                        "chapter_to",
                        "knows",
                        "does_not_know",
                        "withholds",
                    )
                    if k in row
                },
            )
        for field in (
            "knows",
            "does_not_know",
            "wants_pov_to_believe",
            "withholds",
            "allowed_moves",
        ):
            for j, item in enumerate(row.get(field) or []):
                text = str(item).strip()
                if text:
                    _add_fact(
                        facts,
                        fact_id=f"F_VILLAIN_{i}_{field}_{j}",
                        claim=text,
                        source_refs=[f"villain_ledger[{i}].{field}[{j}]"],
                        available_from_chapter=int(row.get("chapter_from") or 1),
                        kind="villain",
                    )

    schedule = (
        concept.get("reveal_schedule")
        or concept.get("required_reveal_schedule")
        or []
    )
    for i, row in enumerate(schedule):
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("ref") or f"R{i+1}").strip()
        fact = str(row.get("fact") or row.get("description") or "").strip()
        reader_ch = int(row.get("reader_reveal_chapter") or row.get("chapter") or 1)
        if fact:
            _add_fact(
                facts,
                fact_id=f"F_REVEAL_{rid}",
                claim=fact,
                source_refs=[f"reveal_schedule[{i}]"],
                available_from_chapter=reader_ch,
                kind="reveal",
                meta={
                    "reveal_id": rid,
                    "reader_reveal_chapter": reader_ch,
                    "pov_knows_chapter": row.get("pov_knows_chapter"),
                },
            )

    for i, row in enumerate(concept.get("clues") or []):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or f"C{i+1}").strip()
        desc = str(row.get("description") or row.get("content") or "").strip()
        plant = int(row.get("plant_chapter") or 1)
        if desc:
            _add_fact(
                facts,
                fact_id=f"F_CLUE_{cid}",
                claim=desc,
                source_refs=[f"clues[{i}].description"],
                available_from_chapter=plant,
                kind="clue",
                meta={
                    "clue_id": cid,
                    "plant_chapter": plant,
                    "payoff_chapter": row.get("payoff_chapter"),
                    "interpretation_at_plant": row.get("interpretation_at_plant"),
                    "true_meaning_at_payoff": row.get("true_meaning_at_payoff"),
                },
            )
        surface = str(row.get("interpretation_at_plant") or "").strip()
        if surface:
            _add_fact(
                facts,
                fact_id=f"F_CLUE_{cid}_SURFACE",
                claim=surface,
                source_refs=[f"clues[{i}].interpretation_at_plant"],
                available_from_chapter=plant,
                kind="clue_surface",
                meta={"clue_id": cid},
            )

    for i, row in enumerate(concept.get("props") or []):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or f"P{i+1}").strip()
        name = str(row.get("name") or pid).strip()
        _add_fact(
            facts,
            fact_id=f"F_PROP_{pid}",
            claim=name,
            source_refs=[f"props[{i}]"],
            available_from_chapter=int(row.get("first_appearance_chapter") or 1),
            kind="prop",
            meta={"prop_id": pid, "prop": row},
        )

    honey = concept.get("honeytoken")
    if isinstance(honey, dict) and honey:
        for key in (
            "delivery_method",
            "interception_method",
            "phrase_creator",
            "first_illicit_reuse_by",
        ):
            val = str(honey.get(key) or "").strip()
            if val:
                _add_fact(
                    facts,
                    fact_id=f"F_HONEY_{key.upper()}",
                    claim=val,
                    source_refs=[f"honeytoken.{key}"],
                    available_from_chapter=int(honey.get("reuse_chapter") or 1)
                    if key != "delivery_method"
                    else 1,
                    kind="honeytoken",
                )
        ev = honey.get("evidentiary_value")
        if isinstance(ev, dict):
            for ek, evv in ev.items():
                text = str(evv or "").strip()
                if text:
                    _add_fact(
                        facts,
                        fact_id=f"F_HONEY_EV_{ek}",
                        claim=text,
                        source_refs=[f"honeytoken.evidentiary_value.{ek}"],
                        available_from_chapter=int(honey.get("reuse_chapter") or 1),
                        kind="honeytoken",
                    )

    chapter_map = concept.get("chapter_map") or {}
    if isinstance(chapter_map, dict):
        for ch_key, entry in chapter_map.items():
            try:
                ch = int(ch_key)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            for field in (
                "title",
                "primary_turn",
                "relationship_turn",
                "day_or_time_anchor",
            ):
                val = str(entry.get(field) or "").strip()
                if val:
                    _add_fact(
                        facts,
                        fact_id=f"F_MAP_CH{ch}_{field.upper()}",
                        claim=val,
                        source_refs=[f"chapter_map.{ch_key}.{field}"],
                        available_from_chapter=ch,
                        kind="chapter_map",
                    )
            for field in (
                "must_happen",
                "must_not_happen",
                "may_observe",
                "pov_knows_at_start",
            ):
                for j, item in enumerate(entry.get(field) or []):
                    text = str(item).strip() if not isinstance(item, dict) else json.dumps(
                        item, ensure_ascii=False
                    )
                    text = text.strip()
                    if text:
                        polarity = "forbidden" if field == "must_not_happen" else None
                        _add_fact(
                            facts,
                            fact_id=f"F_MAP_CH{ch}_{field}_{j}",
                            claim=text,
                            source_refs=[f"chapter_map.{ch_key}.{field}[{j}]"],
                            available_from_chapter=ch,
                            kind="chapter_map",
                            meta={"polarity": polarity} if polarity else None,
                        )

    doctrine = concept.get("romance_doctrine")
    if isinstance(doctrine, dict):
        for j, rule in enumerate(doctrine.get("rules") or []):
            text = str(rule).strip()
            if text:
                _add_fact(
                    facts,
                    fact_id=f"F_DOCTRINE_RULE_{j}",
                    claim=text,
                    source_refs=[f"romance_doctrine.rules[{j}]"],
                    kind="doctrine",
                )
        for j, rule in enumerate(doctrine.get("forbidden_framings") or []):
            text = str(rule).strip()
            if text:
                _add_fact(
                    facts,
                    fact_id=f"F_DOCTRINE_FORBID_{j}",
                    claim=text,
                    source_refs=[f"romance_doctrine.forbidden_framings[{j}]"],
                    kind="constraint",
                    meta={"polarity": "forbidden"},
                )

    return facts


_TEXT_REF_RE = re.compile(r"^text_ref:\s*(/[^\s'\"]+)\s*$")
_TEXT_REF_FIND_RE = re.compile(r"text_ref:\s*(/[^\s'\"]+)")

# Paths whose unresolved refs feed chapter contracts / writer packets.
_CONTRACT_AFFECTING_PREFIXES = (
    "/chapter_map",
    "/clues",
    "/props",
    "/reveal_schedule",
    "/required_reveal_schedule",
    "/honeytoken",
    "/must_include",
    "/must_include_by_chapter",
    "/must_avoid",
    "/characters",
    "/cast",
    "/pov",
    "/true_plot",
    "/surface_plot",
    "/villain_ledger",
)


def _json_path_get(root: Any, pointer: str) -> Any:
    """Resolve a slash path like /chapter_map/8/may_observe/2 against a tree."""
    if not pointer.startswith("/"):
        return None
    cur: Any = root
    for raw in pointer.strip("/").split("/"):
        if raw == "":
            continue
        key: Any = raw
        if isinstance(cur, dict):
            if key in cur:
                cur = cur[key]
                continue
            # YAML may load chapter_map keys as ints.
            try:
                ikey = int(key)
            except ValueError:
                return None
            if ikey in cur:
                cur = cur[ikey]
                continue
            if str(ikey) in cur:
                cur = cur[str(ikey)]
                continue
            return None
        if isinstance(cur, list):
            try:
                idx = int(key)
            except ValueError:
                return None
            if 0 <= idx < len(cur):
                cur = cur[idx]
                continue
            return None
        return None
    return cur


def _is_text_ref_value(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    return bool(_TEXT_REF_RE.match(val.strip()))


def _contract_affecting(pointer: str, occurrence_path: str) -> bool:
    paths = (pointer, occurrence_path)
    for p in paths:
        norm = p if p.startswith("/") else f"/{p}"
        for prefix in _CONTRACT_AFFECTING_PREFIXES:
            if norm == prefix or norm.startswith(prefix + "/") or norm.startswith(
                prefix.lstrip("/") + "."
            ):
                return True
            if norm.replace(".", "/").startswith(prefix):
                return True
    # occurrence like chapter_map.9.may_observe[2]
    occ = occurrence_path.replace(".", "/").replace("[", "/").replace("]", "")
    if not occ.startswith("/"):
        occ = "/" + occ
    for prefix in _CONTRACT_AFFECTING_PREFIXES:
        if occ.startswith(prefix):
            return True
    return False


def _walk_text_ref_occurrences(
    node: Any, path: str = ""
) -> list[tuple[str, str]]:
    """Return (occurrence_path, pointer) for every text_ref string value."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{path}.{k}" if path else str(k)
            found.extend(_walk_text_ref_occurrences(v, child))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            child = f"{path}[{i}]"
            found.extend(_walk_text_ref_occurrences(v, child))
    elif isinstance(node, str):
        m = _TEXT_REF_RE.match(node.strip())
        if m:
            found.append((path, m.group(1)))
        else:
            for m2 in _TEXT_REF_FIND_RE.finditer(node):
                found.append((path, m2.group(1)))
    return found


def resolve_text_refs(
    concept: dict[str, Any],
    *,
    max_passes: int = 4,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inline resolvable text_ref values. Return (concept, resolution_rows)."""
    data = deepcopy(concept)
    resolved_rows: list[dict[str, Any]] = []

    for _ in range(max_passes):
        occs = _walk_text_ref_occurrences(data)
        if not occs:
            break
        progressed = False
        for occurrence_path, pointer in occs:
            target = _json_path_get(data, pointer)
            affects = _contract_affecting(pointer, occurrence_path)
            if target is None or _is_text_ref_value(target):
                continue
            if _set_by_occurrence(data, occurrence_path, target):
                progressed = True
                resolved_rows.append(
                    {
                        "source_path": f"text_ref: {pointer}",
                        "occurrence": occurrence_path,
                        "status": "resolved",
                        "severity": "info",
                        "affects_contract": affects,
                        "note": "inlined",
                        "value_preview": _preview(target),
                    }
                )
        if not progressed:
            break

    rows: list[dict[str, Any]] = list(resolved_rows)
    for occurrence_path, pointer in _walk_text_ref_occurrences(data):
        affects = _contract_affecting(pointer, occurrence_path)
        target = _json_path_get(data, pointer)
        if target is None:
            note = "path missing"
        elif _is_text_ref_value(target):
            note = "circular or still-ref target"
        else:
            note = "remaining after resolve passes"
        rows.append(
            {
                "source_path": f"text_ref: {pointer}",
                "occurrence": occurrence_path,
                "status": "unresolved",
                "severity": "blocking" if affects else "warn",
                "affects_contract": affects,
                "note": note,
            }
        )
    return data, rows


def _set_by_occurrence(root: Any, occurrence: str, value: Any) -> bool:
    """Set value at occurrence path like chapter_map.9.may_observe[2]."""
    if not occurrence:
        return False
    tokens: list[Any] = []
    buf = ""
    i = 0
    while i < len(occurrence):
        ch = occurrence[i]
        if ch == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            i += 1
            continue
        if ch == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            j = occurrence.find("]", i)
            if j < 0:
                return False
            tokens.append(int(occurrence[i + 1 : j]))
            i = j + 1
            continue
        buf += ch
        i += 1
    if buf:
        tokens.append(buf)
    cur = root
    for tok in tokens[:-1]:
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok >= len(cur):
                return False
            cur = cur[tok]
        else:
            if not isinstance(cur, dict):
                return False
            if tok in cur:
                cur = cur[tok]
            else:
                try:
                    itok = int(tok)
                except ValueError:
                    return False
                if itok in cur:
                    cur = cur[itok]
                elif str(itok) in cur:
                    cur = cur[str(itok)]
                else:
                    return False
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(cur, list) or last >= len(cur):
            return False
        cur[last] = value
        return True
    if not isinstance(cur, dict):
        return False
    if last in cur:
        cur[last] = value
        return True
    try:
        ilast = int(last)
    except ValueError:
        cur[last] = value
        return True
    if ilast in cur:
        cur[ilast] = value
        return True
    cur[last] = value
    return True


def build_path_coverage(concept: dict[str, Any]) -> dict[str, Any]:
    coverage: list[dict[str, Any]] = []
    unknown: list[str] = []
    blocking: list[str] = []

    for key in sorted(concept.keys()):
        if key not in KNOWN_TOP_LEVEL:
            unknown.append(key)
            coverage.append(
                _coverage_row(
                    key,
                    status="unused_with_reason",
                    severity="warn",
                    note="additionalProperties not in schema_version — ignored",
                    value_preview=_preview(concept.get(key)),
                )
            )
            continue

        val = concept.get(key)
        if val is None or val == "" or val == [] or val == {}:
            coverage.append(
                _coverage_row(
                    key,
                    status="consumed",
                    target_path=f"ir.{key}",
                    note="empty",
                )
            )
            continue

        coverage.append(
            _coverage_row(
                key,
                status="consumed",
                target_path=f"ir.{key}",
                value_preview=_preview(val),
            )
        )
        for path in _walk_paths(val, key)[1:]:
            coverage.append(
                _coverage_row(
                    path,
                    status="consumed",
                    target_path=f"ir.{path}",
                )
            )

    # REQUIRED keys present but somehow not consumed would block — currently
    # all known keys above are marked consumed.
    for key in REQUIRED_CONSUME_IF_PRESENT:
        if key in concept and not any(
            r.get("source_path") == key and r.get("status") == "consumed"
            for r in coverage
        ):
            if concept.get(key) not in (None, "", [], {}):
                blocking.append(f"required key not consumed: {key}")

    return {
        "coverage": coverage,
        "unknown_fields": unknown,
        "blocking_errors": blocking,
        "ok": not blocking,
    }


def build_ingest_report(concept: dict[str, Any]) -> dict[str, Any]:
    """Split report: path_coverage vs reference_resolution.

    Unresolved text_ref that affects contract → blocking (ok=false).
    """
    path_cov = build_path_coverage(concept)
    _resolved, ref_rows = resolve_text_refs(concept)
    # Deduplicate unresolved rows by source_path+occurrence
    uniq: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ref_rows:
        key = f"{row.get('status')}:{row.get('occurrence')}:{row.get('source_path')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)

    ref_blocking = [
        f"{r.get('source_path')} @ {r.get('occurrence')}: {r.get('note')}"
        for r in uniq
        if r.get("status") == "unresolved" and r.get("affects_contract")
    ]
    reference_resolution = {
        "rows": uniq,
        "blocking_errors": ref_blocking,
        "ok": not ref_blocking,
    }

    blocking = list(path_cov["blocking_errors"]) + ref_blocking
    # Flatten: path coverage rows + reference rows into legacy `coverage` for
    # downstream readers, but keep the split fields authoritative.
    coverage = list(path_cov["coverage"])
    for row in uniq:
        coverage.append(
            _coverage_row(
                str(row.get("source_path") or ""),
                status=str(row.get("status") or "unresolved"),
                note=str(row.get("note") or ""),
                severity=str(row.get("severity") or "warn"),
                value_preview=row.get("value_preview"),
            )
        )

    return {
        "importer_version": IMPORTER_VERSION,
        "schema_version": IR_SCHEMA_VERSION,
        "path_coverage": path_cov,
        "reference_resolution": reference_resolution,
        "coverage": coverage,
        "unknown_fields": path_cov["unknown_fields"],
        "blocking_errors": blocking,
        "ok": path_cov["ok"] and reference_resolution["ok"],
    }


def compile_canonical_ir(
    concept: dict[str, Any],
    *,
    source_bytes: bytes | None = None,
    source_path: str = "concept.yaml",
) -> dict[str, Any]:
    raw = source_bytes if source_bytes is not None else yaml.safe_dump(
        concept, allow_unicode=True
    ).encode("utf-8")
    report = build_ingest_report(concept)
    if not report["ok"]:
        raise ValueError(
            "canonical_ir ingest blocked: " + "; ".join(report["blocking_errors"])
        )

    resolved, _ref_rows = resolve_text_refs(concept)
    facts = build_fact_registry(resolved)
    entities = []
    for row in resolved.get("characters") or resolved.get("cast") or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            entities.append(
                {
                    "name": str(row.get("name")).strip(),
                    "role": str(row.get("role") or "").strip(),
                    "aliases": [
                        str(a).strip()
                        for a in (row.get("aliases") or [])
                        if str(a).strip()
                    ],
                }
            )

    ir: dict[str, Any] = {
        "schema_version": IR_SCHEMA_VERSION,
        "importer_version": IMPORTER_VERSION,
        "source_path": source_path,
        "source_sha256": sha256_bytes(raw),
        "concept_status": str(resolved.get("concept_status") or "").strip() or None,
        "title": str(resolved.get("title") or "").strip(),
        "pen_name": str(resolved.get("pen_name") or "").strip(),
        "target_language": str(resolved.get("target_language") or "en").strip(),
        "chapter_count": int(resolved.get("chapter_count") or 0),
        "pov": deepcopy(resolved.get("pov") or {}),
        "romance_mode": resolved.get("romance_mode"),
        "spice_level": resolved.get("spice_level"),
        "spice_default": resolved.get("spice_default"),
        "spice_schedule": deepcopy(resolved.get("spice_schedule") or {}),
        "canonical_reveal_chapter": resolved.get("canonical_reveal_chapter"),
        "corpse_reveal_chapter": resolved.get("corpse_reveal_chapter"),
        "intentional_early_reveal": resolved.get("intentional_early_reveal"),
        "plots": {
            "logline": resolved.get("logline"),
            "surface_plot": resolved.get("surface_plot"),
            "true_plot": resolved.get("true_plot"),
            "ending_book1": resolved.get("ending_book1"),
            "hook_book2": resolved.get("hook_book2"),
            "author_directive": resolved.get("author_directive"),
            "notes": resolved.get("notes"),
        },
        "entities": entities,
        "character_psychology": deepcopy(resolved.get("character_psychology") or []),
        "psychological_condition": deepcopy(
            resolved.get("psychological_condition") or {}
        ),
        "villain_ledger": deepcopy(resolved.get("villain_ledger") or []),
        "reveal_schedule": deepcopy(
            resolved.get("reveal_schedule")
            or resolved.get("required_reveal_schedule")
            or []
        ),
        "clues": deepcopy(resolved.get("clues") or []),
        "props": deepcopy(resolved.get("props") or []),
        "honeytoken": deepcopy(resolved.get("honeytoken") or {}),
        "chapter_map": deepcopy(resolved.get("chapter_map") or {}),
        "must_include": deepcopy(resolved.get("must_include") or []),
        "must_include_by_chapter": deepcopy(
            resolved.get("must_include_by_chapter") or {}
        ),
        "must_avoid": deepcopy(resolved.get("must_avoid") or []),
        "romance_doctrine": deepcopy(resolved.get("romance_doctrine") or {}),
        "threshold_events": deepcopy(resolved.get("threshold_events") or []),
        "arc_shape": deepcopy(resolved.get("arc_shape") or {}),
        "setting_graph": deepcopy(resolved.get("setting_graph") or {}),
        "facts": facts,
        "fact_index": {f["fact_id"]: f for f in facts},
    }
    ir["ir_digest"] = sha256_obj(
        {k: v for k, v in ir.items() if k not in ("ir_digest", "fact_index")}
    )
    return ir


def ingest_concept_to_workspace(
    ws: Path,
    concept_path: Path | None = None,
    *,
    copy_source: bool = True,
) -> dict[str, Any]:
    """Ingest CE/workspace concept into bible/canonical_ir.json + ingest_report."""
    paths = ir_paths(ws)
    src = concept_path or (ws / "concept.yaml")
    if not src.exists():
        raise FileNotFoundError(f"missing concept: {src}")
    concept, raw = load_yaml_concept(src)
    # Allow missing concept_status for transitional CE; prefer ready/released.
    status = str(concept.get("concept_status") or "").strip().lower()
    if status and status not in ("ready", "released"):
        raise ValueError(f"concept_status not ready/released: {status!r}")

    report = build_ingest_report(concept)
    ir = compile_canonical_ir(concept, source_bytes=raw, source_path=str(src))

    paths["canonical_ir"].parent.mkdir(parents=True, exist_ok=True)
    if copy_source:
        paths["source_concept"].parent.mkdir(parents=True, exist_ok=True)
        paths["source_concept"].write_bytes(raw)

    paths["canonical_ir"].write_text(
        json.dumps(ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["ingest_report"].write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ir": ir, "report": report, "paths": {k: str(v) for k, v in paths.items()}}


def load_canonical_ir(ws: Path) -> dict[str, Any] | None:
    path = ir_paths(ws)["canonical_ir"]
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def ensure_canonical_ir(ws: Path) -> dict[str, Any]:
    existing = load_canonical_ir(ws)
    if existing:
        return existing
    result = ingest_concept_to_workspace(ws)
    return result["ir"]


def facts_available_by_chapter(
    ir: dict[str, Any],
    chapter: int,
    *,
    include_kinds: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    kinds = set(include_kinds) if include_kinds else None
    out = []
    for fact in ir.get("facts") or []:
        if int(fact.get("available_from_chapter") or 1) > chapter:
            continue
        if kinds is not None and fact.get("kind") not in kinds:
            continue
        out.append(fact)
    return out


def entity_names(ir: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for ent in ir.get("entities") or []:
        name = str(ent.get("name") or "").strip()
        if name:
            names.add(name)
            names.add(name.split()[0])
            for alias in ent.get("aliases") or []:
                if str(alias).strip():
                    names.add(str(alias).strip())
    return names


def allowed_claim_blob(
    ir: dict[str, Any],
    chapter: int,
    *,
    include_true_plot: bool = False,
    include_future_reveals: bool = False,
) -> str:
    """Lowercased corpus of claims available for matching at chapter."""
    parts = [str(f.get("claim") or "") for f in facts_available_by_chapter(ir, chapter)]
    for ent in ir.get("entities") or []:
        parts.append(str(ent.get("name") or ""))
    for clue in ir.get("clues") or []:
        plant = int(clue.get("plant_chapter") or 1)
        if plant <= chapter:
            parts.append(str(clue.get("id") or ""))
            parts.append(str(clue.get("description") or ""))
        if include_future_reveals or int(clue.get("payoff_chapter") or plant) <= chapter:
            if int(clue.get("payoff_chapter") or 0) <= chapter:
                parts.append(str(clue.get("true_meaning_at_payoff") or ""))
    for rev in ir.get("reveal_schedule") or []:
        reader_ch = int(rev.get("reader_reveal_chapter") or rev.get("chapter") or 1)
        if include_future_reveals or reader_ch <= chapter:
            parts.append(str(rev.get("id") or ""))
            parts.append(str(rev.get("fact") or ""))
    for prop in ir.get("props") or []:
        parts.append(str(prop.get("name") or ""))
        parts.append(str(prop.get("id") or ""))
    surface = str((ir.get("plots") or {}).get("surface_plot") or "")
    parts.append(surface)
    if include_true_plot:
        parts.append(str((ir.get("plots") or {}).get("true_plot") or ""))
    return "\n".join(parts).casefold()


def ephemeral_texture_blob(ir: dict[str, Any]) -> str:
    """Lowercase texture granted only by IR canon_class=ephemeral facts.

    Compiler/IR must set canon_class; the prose gate never invents ephemeral
    proper-noun allowances from this blob.
    """
    parts = []
    for fact in ir.get("facts") or []:
        if str(fact.get("canon_class") or "") != "ephemeral":
            continue
        claim = str(fact.get("claim") or "").strip()
        # Ephemeral is lowercase texture only — drop any Capitalized tokens.
        if not claim:
            continue
        if re.search(r"\b[A-Z][a-z]+\b", claim):
            # Strip proper-noun-looking tokens; keep lowercase words.
            kept = re.findall(r"\b[a-z][a-z0-9']{2,}\b", claim)
            parts.append(" ".join(kept))
        else:
            parts.append(claim.casefold())
    return "\n".join(parts).casefold()


def future_locked_claims(ir: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    """Reveal / true-meaning claims not yet unlocked for the reader at chapter."""
    out: list[dict[str, Any]] = []
    for rev in ir.get("reveal_schedule") or []:
        reader_ch = int(rev.get("reader_reveal_chapter") or rev.get("chapter") or 1)
        if reader_ch <= chapter:
            continue
        fact = str(rev.get("fact") or "").strip()
        if not fact:
            continue
        out.append(
            {
                "fact_id": f"F_REVEAL_{rev.get('id')}",
                "claim": fact,
                "available_from_chapter": reader_ch,
                "kind": "reveal",
            }
        )
    for clue in ir.get("clues") or []:
        payoff = int(clue.get("payoff_chapter") or 0)
        meaning = str(clue.get("true_meaning_at_payoff") or "").strip()
        if meaning and payoff and payoff > chapter:
            out.append(
                {
                    "fact_id": f"F_CLUE_{clue.get('id')}_TRUE",
                    "claim": meaning,
                    "available_from_chapter": payoff,
                    "kind": "clue_true_meaning",
                }
            )
    # true_plot is locked until canonical_reveal_chapter when set.
    unlock = int(ir.get("canonical_reveal_chapter") or 0)
    true_plot = str((ir.get("plots") or {}).get("true_plot") or "").strip()
    if true_plot and unlock and chapter < unlock:
        out.append(
            {
                "fact_id": "F_PLOT_TRUE_PLOT",
                "claim": true_plot,
                "available_from_chapter": unlock,
                "kind": "plot",
            }
        )
    return out
