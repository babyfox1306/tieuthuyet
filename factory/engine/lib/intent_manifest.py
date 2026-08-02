"""IntentManifest — Lock0 compile from concept (Python only, 0 AI).

Chain: concept.yaml → intent_manifest.json → (narrative pack) → master_plan → prompts.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.narrative_schema import load_concept
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import book_workspace_dir

MANIFEST_VERSION = 1
PLACEHOLDER_LEADS = frozenset(
    {
        "female lead",
        "male lead",
        "female_lead",
        "male_lead",
        "unassigned",
        "unassigned (no male lead)",
        "pov lead",
        "the protagonist",
    }
)

_CH_MAP_RE = re.compile(
    r"(?im)^\s*(?:ch(?:apter)?\.?\s*|ch\s*)(\d+)\s*[:.\-–—]\s*(.+?)(?=^\s*(?:ch(?:apter)?\.?\s*|ch\s*)\d+\s*[:.\-–—]|\Z)",
    re.DOTALL,
)
_CH_INLINE_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:ch(?:apter)?\.?\s*|ch\s*)(\d+)\s*[:.\-–—]\s*([^\n]+)"
)


def intent_manifest_path(ws: Path, book: int = 1) -> Path:
    return book_workspace_dir(ws, book) / "intent_manifest.json"


def concept_digest(concept: dict) -> str:
    blob = json.dumps(concept, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def digest_obj(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _as_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    return [str(val).strip()] if str(val).strip() else []


_CH_RANGE_RE = re.compile(
    r"(?im)^\s*(?:ch(?:apter)?\.?\s*|ch\s*)(\d+)\s*[-–—]\s*(\d+)\s*[:.\-–—]\s*(.+?)(?=^\s*(?:ch(?:apter)?\.?\s*|ch\s*)\d+|\Z)",
    re.DOTALL,
)


def _parse_chapter_map_from_directive(text: str) -> dict[int, dict[str, Any]]:
    """Extract ChN: / ChN-M: beat lines from free-text author_directive."""
    out: dict[int, dict[str, Any]] = {}
    if not text or not str(text).strip():
        return out
    for m in _CH_RANGE_RE.finditer(str(text)):
        lo, hi = int(m.group(1)), int(m.group(2))
        beat = re.sub(r"\s+", " ", m.group(3)).strip()
        if not beat:
            continue
        for ch in range(lo, hi + 1):
            out[ch] = {
                "chapter": ch,
                "beat": beat if ch == lo else f"(continues Ch{lo}-{hi}) {beat}",
                "must_include": [],
                "must_happen": [],
            }
    for m in _CH_MAP_RE.finditer(str(text)):
        ch = int(m.group(1))
        if ch in out:
            continue
        beat = re.sub(r"\s+", " ", m.group(2)).strip()
        if beat:
            out[ch] = {"chapter": ch, "beat": beat, "must_include": [], "must_happen": []}
    if out:
        return out
    for m in _CH_INLINE_RE.finditer(str(text)):
        ch = int(m.group(1))
        beat = m.group(2).strip()
        if beat:
            out[ch] = {"chapter": ch, "beat": beat, "must_include": [], "must_happen": []}
    return out


def _chapter_entry_from_dict(ch: int, v: dict) -> dict[str, Any]:
    """Normalize one structured chapter_map entry (required_beats / ending / title)."""
    required = _as_str_list(
        v.get("required_beats") or v.get("must_happen") or v.get("beats")
    )
    must_include = _as_str_list(v.get("must_include"))
    must_not = _as_str_list(v.get("must_not_reveal") or v.get("must_not"))
    title = str(v.get("title") or "").strip()
    ending = str(v.get("ending") or v.get("chapter_ending") or "").strip()
    final_line = str(v.get("final_line") or "").strip()
    beat = str(v.get("beat") or v.get("summary") or v.get("text") or "").strip()
    if not beat:
        parts: list[str] = []
        if title:
            parts.append(title)
        if required:
            parts.append("; ".join(required))
        if ending:
            parts.append(f"Ending: {ending}")
        if final_line:
            parts.append(f"Final line: {final_line}")
        beat = " | ".join(parts)
    return {
        "chapter": ch,
        "title": title,
        "beat": beat,
        "must_include": must_include,
        "must_happen": required,
        "must_not_reveal": must_not,
        "ending": ending,
        "final_line": final_line,
    }


def _normalize_structured_chapter_map(raw: Any) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                ch = int(str(k).lstrip("chCH"))
            except ValueError:
                continue
            if isinstance(v, str):
                out[ch] = {
                    "chapter": ch,
                    "title": "",
                    "beat": v.strip(),
                    "must_include": [],
                    "must_happen": [],
                    "must_not_reveal": [],
                    "ending": "",
                    "final_line": "",
                }
            elif isinstance(v, dict):
                out[ch] = _chapter_entry_from_dict(ch, v)
        return out
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                ch = int(item.get("chapter") or item.get("ch") or 0)
            except (TypeError, ValueError):
                continue
            if ch <= 0:
                continue
            out[ch] = _chapter_entry_from_dict(ch, item)
    return out


_CANONICAL_REVEAL_MARKERS = (
    "reader learn",
    "reader discovers",
    "reader learns",
    "full control reveal",
    "control reveal",
    "complete method",
    "complete planner",
    "full interpretation",
    "full truth reveal",
    "reveals the full truth",
)


def infer_canonical_reveal_chapter(
    concept: dict[str, Any],
    chapter_map: dict[int, dict[str, Any]] | None = None,
) -> int | None:
    """Derive the reader-facing mystery reveal from the highest intent sources.

    Explicit structured metadata wins. Otherwise, inspect affirmative chapter-map
    beats only; ``must_not_reveal`` and end-of-book payoff language are not
    candidates. This keeps a legal/evidence payoff from being mistaken for the
    first reader reveal.
    """
    for key in ("mystery_reveal_chapter", "canonical_reveal_chapter"):
        value = concept.get(key)
        if value is not None:
            try:
                chapter = int(value)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                return chapter

    normalized = chapter_map
    if normalized is None:
        normalized = _normalize_structured_chapter_map(concept.get("chapter_map"))
    scored: list[tuple[int, int]] = []
    for chapter, entry in (normalized or {}).items():
        affirmative = " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("beat") or ""),
                " ".join(_as_str_list(entry.get("must_happen"))),
                " ".join(_as_str_list(entry.get("must_include"))),
            ]
        ).lower()
        score = sum(1 for marker in _CANONICAL_REVEAL_MARKERS if marker in affirmative)
        if score:
            scored.append((score, int(chapter)))
    if scored:
        best_score = max(score for score, _ in scored)
        return min(chapter for score, chapter in scored if score == best_score)
    return None


def _infer_pov(concept: dict, directive: str) -> str:
    raw = concept.get("pov") or concept.get("point_of_view")
    if isinstance(raw, dict):
        character = str(raw.get("character") or raw.get("name") or "").strip()
        mode = str(raw.get("mode") or "").strip()
        tense = str(raw.get("tense") or "").strip()
        # Prefer a stable lock string: "Clara Vale | first_person | past"
        bits = [b for b in (character, mode, tense) if b]
        if bits:
            return " | ".join(bits)
    elif raw is not None and str(raw).strip() and not str(raw).startswith("{"):
        return str(raw).strip()
    m = re.search(r"(?im)\bPOV\s*:\s*(.+)", directive)
    if m:
        return m.group(1).strip().split("\n")[0].strip()
    return ""


def _infer_cast(concept: dict, directive: str) -> list[str]:
    raw = concept.get("cast") if concept.get("cast") is not None else concept.get("characters")
    names: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    names.append(name)
            elif item is not None and str(item).strip():
                # Skip stringified dicts
                s = str(item).strip()
                if not s.startswith("{") and ":" not in s[:12]:
                    names.append(s)
                elif s.startswith("-"):
                    names.append(s.lstrip("- ").split(":")[0].strip())
    elif isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                name = str(v.get("name") or k).strip()
            else:
                name = str(v or k).strip()
            if name and not name.startswith("{"):
                names.append(name)
    elif raw is not None and str(raw).strip() and not str(raw).startswith("{"):
        names = _as_str_list(raw)
    if names:
        return list(dict.fromkeys(names))
    block = re.search(
        r"(?is)CAST\s*(?:\([^)]*\))?\s*:\s*(.+?)(?=\n\s*POV:|\n\s*SPICE:|\n\s*CHAPTER|\n\s*Ch\d|\Z)",
        directive,
    )
    if not block:
        return []
    for line in block.group(1).splitlines():
        line = line.strip().lstrip("-•*").strip()
        if not line:
            continue
        if re.match(r"(?i)^ch(?:apter)?\.?\s*\d+", line):
            break
        name = re.split(r"[:—(]", line, maxsplit=1)[0].strip()
        if name and len(name) < 80 and not re.match(r"(?i)^ch\d", name):
            names.append(name)
    return list(dict.fromkeys(names))


def _infer_genre(concept: dict, direction: dict) -> str:
    for key in ("genre_profile", "narrative_profile"):
        val = concept.get(key)
        if val is not None and str(val).strip() and not isinstance(val, (dict, list)):
            return str(val).strip()
    genre = concept.get("genre")
    if isinstance(genre, dict):
        primary = str(genre.get("primary") or "").strip()
        secondary = _as_str_list(genre.get("secondary"))
        if primary and secondary:
            return f"{primary}; " + ", ".join(secondary)
        return primary or ", ".join(secondary)
    if genre is not None and str(genre).strip() and not str(genre).startswith("{"):
        return str(genre).strip()
    return str(direction.get("narrative_profile") or "").strip()


def _normalize_reveal_ladder(raw: Any) -> dict[str, Any]:
    """Keep structured reveal_ladder from concept; coerce chapter ints."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        k = str(key).strip()
        if not k:
            continue
        if isinstance(val, dict):
            entry = dict(val)
            try:
                if "chapter" in entry:
                    entry["chapter"] = int(entry["chapter"])
            except (TypeError, ValueError):
                pass
            for text_key in ("exact_text", "meaning", "rule"):
                if text_key in entry and entry[text_key] is not None:
                    entry[text_key] = str(entry[text_key]).strip()
            out[k] = entry
        else:
            try:
                out[k] = int(val)
            except (TypeError, ValueError):
                out[k] = val
    return out


def _build_reveal_ladder(
    chapter_map: dict[int, dict[str, Any]],
    concept_ladder: dict[str, Any] | None = None,
    *,
    cast: list[str] | None = None,
) -> dict[str, Any]:
    """Prefer concept reveal_ladder; only add cast first-appearance ints as extras."""
    ladder: dict[str, Any] = dict(concept_ladder or {})
    cast_keys = {n.lower(): n for n in (cast or []) if n}
    if cast_keys:
        for ch, entry in sorted(chapter_map.items()):
            blob = " ".join(
                [
                    str(entry.get("beat") or ""),
                    " ".join(_as_str_list(entry.get("must_happen"))),
                    str(entry.get("ending") or ""),
                ]
            ).lower()
            for key in cast_keys:
                if key in ladder:
                    continue
                if key in blob:
                    ladder[key] = ch
    return ladder


def derive_required_reveal_schedule(
    concept: dict[str, Any],
) -> list[dict[str, Any]]:
    """Derive stable reveal requirements from an explicit concept schedule.

    A structured ``required_reveal_schedule`` wins.  Legacy CLEAR concepts may
    instead carry the schedule in a ``TIME ANCHOR`` directive sentence such as
    ``Ch3 first detection; Ch7 first proof; ...``.  We intentionally parse only
    a sentence containing at least two chapter anchors: isolated ``ChN``
    references elsewhere are prose context, not a reveal contract.
    """
    raw = concept.get("required_reveal_schedule") or concept.get("reveal_schedule")
    items: list[tuple[int, str, str]] = []
    if isinstance(raw, dict):
        raw = [
            {"chapter": key, "description": value}
            if not isinstance(value, dict)
            else {"chapter": key, **value}
            for key, value in raw.items()
        ]
    if isinstance(raw, list):
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            try:
                chapter = int(item.get("chapter") or 0)
            except (TypeError, ValueError):
                continue
            description = str(
                item.get("description")
                or item.get("beat")
                or item.get("meaning")
                or ""
            ).strip()
            if chapter > 0 and description:
                ref = str(item.get("ref") or item.get("id") or f"RS{index:03d}").strip()
                items.append((chapter, description, ref))

    if not items:
        directive = str(concept.get("author_directive") or "")
        anchor = re.search(
            r"TIME\s+ANCHOR\b(?P<body>.*?)(?=\n\s*P\d+\s*[—-]|\Z)",
            directive,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if anchor:
            sentences = re.split(r"(?<=[.!?])\s+", anchor.group("body"))
            schedule_sentence = max(
                sentences,
                key=lambda sentence: len(
                    re.findall(r"\bCh(?:apter)?\s*\d+\b", sentence, re.I)
                ),
                default="",
            )
            if len(
                re.findall(r"\bCh(?:apter)?\s*\d+\b", schedule_sentence, re.I)
            ) < 2:
                schedule_sentence = ""
            for match in re.finditer(
                r"\bCh(?:apter)?\s*(?P<chapter>\d+)\s+"
                r"(?P<description>[^;,.]+(?:,[^;.]*)?)",
                schedule_sentence,
                flags=re.IGNORECASE,
            ):
                chapter = int(match.group("chapter"))
                description = re.sub(r"\s+", " ", match.group("description")).strip()
                if chapter > 0 and description:
                    items.append((chapter, description, ""))

    chapter_map = _normalize_structured_chapter_map(concept.get("chapter_map"))
    out: list[dict[str, Any]] = []
    for index, (chapter, description, ref) in enumerate(items, start=1):
        requirement = {
            "ref": ref or f"RS{index:03d}",
            "chapter": chapter,
            "description": description,
        }
        source_beat = str((chapter_map.get(chapter) or {}).get("beat") or "").strip()
        if source_beat:
            requirement["source_beat"] = source_beat
        out.append(requirement)
    return out


def _surface_plot(concept: dict) -> str:
    return str(
        concept.get("surface_plot")
        or concept.get("surface_mystery")
        or ""
    ).strip()


def _character_records(concept: dict) -> list[dict[str, Any]]:
    raw = concept.get("characters")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            out.append(item)
    return out


def _must_include_by_chapter(
    concept: dict,
    chapter_map: dict[int, dict[str, Any]],
    chapter_count: int,
) -> dict[str, list[str]]:
    raw = concept.get("must_include_by_chapter") or concept.get("must_include_per_chapter")
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                ch = int(str(k).lstrip("chCH"))
            except ValueError:
                continue
            out[str(ch)] = _as_str_list(v)
    for ch, entry in chapter_map.items():
        key = str(ch)
        local = _as_str_list(entry.get("must_include"))
        if local:
            out[key] = list(dict.fromkeys((out.get(key) or []) + local))
    # Book-level must_include stays book-level only (not dumped into every chapter).
    # Ending obligations attach to final chapter.
    ending = str(concept.get("ending_book1") or "").strip()
    if ending and chapter_count > 0:
        last = str(chapter_count)
        out.setdefault(last, [])
        if ending not in out[last]:
            out[last].append(ending)
    return out


_NUMBERED_CHAPTER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
}


def _chapter_mentions(text: str) -> list[int]:
    chapters: list[int] = []
    word_tokens = "|".join(
        sorted(_NUMBERED_CHAPTER_WORDS, key=len, reverse=True)
    )
    chapter_token = rf"(?:\d{{1,3}}|{word_tokens})"
    separator = r"(?:\s*,\s*(?:and\s+)?|\s+(?:and|&|to|through)\s+|\s*-\s*)"
    for match in re.finditer(
        rf"\bCh(?:apter)?s?\s+(?P<values>{chapter_token}"
        rf"(?:{separator}{chapter_token})*)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        values = re.findall(
            rf"\b(?:\d{{1,3}}|{word_tokens})\b",
            match.group("values").lower(),
        )
        for value in values:
            chapter = int(value) if value.isdigit() else _NUMBERED_CHAPTER_WORDS[value]
            if chapter not in chapters:
                chapters.append(chapter)
    return chapters


def derive_must_include_requirements(
    concept: dict[str, Any],
    chapter_count: int,
) -> list[dict[str, Any]]:
    """Give flat legacy requirements an explicit projection scope.

    Structured objects are authoritative. Legacy strings are split at
    semicolons; explicit chapter annotations and ending language are safe to
    derive, while ambiguous prose remains full-book-audit-only.
    """
    out: list[dict[str, Any]] = []
    raw_items = concept.get("must_include") or []
    if not isinstance(raw_items, list):
        return out
    for raw in raw_items:
        if isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("requirement") or "").strip()
            scope = str(raw.get("scope") or "").strip()
            if not text or scope not in {
                "global_invariant",
                "chapter_specific",
                "chapter_range",
                "chapter_allowlist",
                "ending_only",
                "full_book_audit_only",
            }:
                continue
            item = {"text": text, "scope": scope}
            if scope == "chapter_specific":
                item["chapters"] = [
                    int(ch) for ch in (raw.get("chapters") or []) if int(ch) > 0
                ]
            elif scope == "chapter_allowlist":
                item["chapters"] = [
                    int(ch) for ch in (raw.get("chapters") or []) if int(ch) > 0
                ]
            elif scope == "chapter_range":
                item["start_chapter"] = int(raw.get("start_chapter") or 1)
                item["end_chapter"] = int(
                    raw.get("end_chapter") or chapter_count
                )
            out.append(item)
            continue

        clauses = [
            clause.strip()
            for clause in re.split(r"\s*;\s*", str(raw or ""))
            if clause.strip()
        ]
        for clause in clauses:
            chapters = [
                ch for ch in _chapter_mentions(clause) if ch <= chapter_count
            ]
            if chapters:
                # "Only in" is a placement boundary, not an instruction to
                # force the item into every named chapter.  Preserve the
                # allowlist for whole-book audit without projecting it into
                # chapter prompts or G3's required-occurrence checks.
                allowlist = bool(
                    re.search(
                        r"\b(?:appears?|occurs?|may\s+appear|may\s+occur)\s+only\s+in\b",
                        clause,
                        re.I,
                    )
                )
                out.append(
                    {
                        "text": clause,
                        "scope": "chapter_allowlist" if allowlist else "chapter_specific",
                        "chapters": chapters,
                    }
                )
            elif re.search(r"\b(?:final|ending|aftermath)\b", clause, re.I):
                out.append({"text": clause, "scope": "ending_only"})
            else:
                out.append({"text": clause, "scope": "full_book_audit_only"})
    return out


def compile_intent_manifest(ws: Path, book: int | None = None) -> dict[str, Any]:
    """Python-only compile. Raises ValueError with joined errors if incomplete."""
    concept = load_concept(ws)
    direction = load_direction(ws)
    book_num_early = int(book if book is not None else direction.get("book") or 1)
    # Canonical IR is SoT for provenance pipeline (legacy intent remains a view).
    try:
        from factory.engine.lib.canonical_ir import (
            ingest_concept_to_workspace,
            load_canonical_ir,
        )
        from factory.engine.lib.canon_artifacts import mark_stale_descendants

        prev = None
        try:
            prev = load_canonical_ir(ws)
        except Exception:
            prev = None
        ingested = ingest_concept_to_workspace(ws)
        new_digest = str((ingested.get("ir") or {}).get("ir_digest") or "")
        old_digest = str((prev or {}).get("ir_digest") or "")
        if old_digest and new_digest and old_digest != new_digest:
            mark_stale_descendants(ws, book_num_early, reason="canonical_ir_changed")
    except Exception as exc:
        import sys

        print(f"  [canonical_ir] WARN: {exc}", file=sys.stderr)

    book_num = int(book if book is not None else direction.get("book") or 1)
    errors = validate_intent_inputs(concept, direction, ws=ws, book=book_num)
    if errors:
        raise ValueError("; ".join(errors))

    directive = str(concept.get("author_directive") or "")
    chapter_map = _normalize_structured_chapter_map(concept.get("chapter_map"))
    if not chapter_map:
        chapter_map = _parse_chapter_map_from_directive(directive)

    from factory.engine.lib.book_config import get_total_chapters

    fmt = concept.get("format") if isinstance(concept.get("format"), dict) else {}
    chapter_count = (
        int(direction.get("total_chapters") or 0)
        or int((fmt or {}).get("total_chapters") or 0)
        or get_total_chapters(ws.name, book_num)
    )
    if not chapter_count and chapter_map:
        chapter_count = max(chapter_map.keys())

    must_by_ch = _must_include_by_chapter(concept, chapter_map, chapter_count)
    # Fold required_beats into must_include_by_chapter so G3 can enforce them.
    for ch, entry in chapter_map.items():
        key = str(ch)
        local = _as_str_list(entry.get("must_happen")) + _as_str_list(entry.get("must_include"))
        if local:
            must_by_ch[key] = list(dict.fromkeys((must_by_ch.get(key) or []) + local))

    pov = _infer_pov(concept, directive)
    cast = _infer_cast(concept, directive)
    genre = _infer_genre(concept, direction)
    language = str(
        concept.get("target_language") or direction.get("target_language") or "vi"
    ).strip()
    concept_reveal = _normalize_reveal_ladder(concept.get("reveal_ladder"))

    chapter_map_list = [chapter_map[ch] for ch in sorted(chapter_map.keys())]
    canonical_reveal_chapter = infer_canonical_reveal_chapter(concept, chapter_map)
    from factory.engine.lib.workspace_metadata import (
        infer_spice_default,
        infer_spice_level,
        normalize_spice_schedule,
    )

    spice_level = infer_spice_level(concept)
    spice_default = infer_spice_default(concept, spice_level)
    spice_schedule = normalize_spice_schedule(
        concept,
        chapter_count,
        spice_level,
    )
    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "book": book_num,
        "status": "draft",
        "concept_digest": concept_digest(concept),
        "title": str(concept.get("title") or "").strip(),
        "logline": str(concept.get("logline") or "").strip(),
        "pov": pov,
        "cast": cast,
        "chapter_count": chapter_count,
        "chapter_map": chapter_map_list,
        "must_include_by_chapter": must_by_ch,
        "must_avoid": _as_str_list(concept.get("must_avoid")),
        "must_include_book": _as_str_list(concept.get("must_include")),
        "must_include_requirements": derive_must_include_requirements(
            concept,
            chapter_count,
        ),
        "ending_book1": str(concept.get("ending_book1") or "").strip(),
        "hook_book2": str(concept.get("hook_book2") or "").strip(),
        "surface_plot": _surface_plot(concept),
        "true_plot": str(concept.get("true_plot") or "").strip(),
        "final_supernatural_residue": str(
            concept.get("final_supernatural_residue") or ""
        ).strip(),
        "genre_profile": genre,
        "language": language,
        "spice_level": spice_level,
        "spice_default": spice_default,
        "spice_schedule": spice_schedule,
        "reveal_ladder": _build_reveal_ladder(chapter_map, concept_reveal, cast=cast),
        "required_reveal_schedule": derive_required_reveal_schedule(concept),
        "canonical_reveal_chapter": canonical_reveal_chapter,
    }
    manifest["manifest_digest"] = digest_obj(
        {k: v for k, v in manifest.items() if k not in ("status", "manifest_digest", "approved_at")}
    )
    return manifest


def validate_intent_inputs(
    concept: dict,
    direction: dict,
    *,
    ws: Path | None = None,
    book: int = 1,
) -> list[str]:
    """G0 pre-check before/while compile."""
    errors: list[str] = []
    if not concept:
        return ["intent:missing_concept"]
    if (concept.get("concept_status") or "").strip().lower() != "ready":
        errors.append('intent:concept_status_not_ready')

    directive = str(concept.get("author_directive") or "")
    chapter_map = _normalize_structured_chapter_map(concept.get("chapter_map"))
    if not chapter_map:
        chapter_map = _parse_chapter_map_from_directive(directive)
    if not chapter_map:
        errors.append(
            "intent:chapter_map_missing — thêm concept.chapter_map hoặc các dòng Ch1:/Ch2: trong author_directive"
        )

    from factory.engine.lib.book_config import get_total_chapters

    if ws is not None:
        expected = int(direction.get("total_chapters") or 0) or get_total_chapters(ws.name, book)
    else:
        expected = int(direction.get("total_chapters") or 0)
    if expected and chapter_map:
        # Accept range labels like Ch4-5 / Ch8-9 as coverage for endpoints.
        covered = set(chapter_map.keys())
        for ch, entry in list(chapter_map.items()):
            beat = str(entry.get("beat") or "")
            # If directive used "Ch4-5:" the parser may store ch=4 with beat starting "-5:"
            m_range = re.match(r"^-?\s*(\d+)\s*:", beat)
            if m_range:
                try:
                    covered.add(int(m_range.group(1)))
                except ValueError:
                    pass
        if len(covered) < max(3, (expected + 1) // 2):
            errors.append(
                f"intent:chapter_map_too_sparse (có ~{len(covered)}/{expected} chương)"
            )

    if not str(concept.get("ending_book1") or "").strip():
        # ending may live only in directive for older concepts — soft require if no map last beat
        if not (chapter_map and str(chapter_map.get(max(chapter_map.keys()), {}).get("beat") or "").strip()):
            errors.append("intent:ending_book1_missing")

    pov = _infer_pov(concept, directive)
    if not pov:
        errors.append("intent:pov_missing — ghi POV: trong author_directive hoặc concept.pov")

    # G0b — chapter_map plot family must not contradict directive/true_plot.
    from factory.engine.lib.narrative_schema import concept_map_fidelity_errors

    errors.extend(concept_map_fidelity_errors(concept))

    return errors


def validate_manifest(manifest: dict, *, expected_chapters: int | None = None) -> list[str]:
    """G0 on compiled manifest."""
    errors: list[str] = []
    if not manifest:
        return ["intent:empty_manifest"]
    cmap = manifest.get("chapter_map") or []
    if not cmap:
        errors.append("intent:empty_chapter_map")
    n = int(manifest.get("chapter_count") or 0)
    if expected_chapters:
        n = expected_chapters
    if n and len(cmap) < max(1, n // 2):
        errors.append(f"intent:chapter_map_count {len(cmap)}<<{n}")
    if not str(manifest.get("pov") or "").strip():
        errors.append("intent:pov_empty")
    if not str(manifest.get("concept_digest") or "").strip():
        errors.append("intent:missing_concept_digest")
    # placeholder cast names
    for name in manifest.get("cast") or []:
        if str(name).strip().lower() in PLACEHOLDER_LEADS:
            errors.append(f"intent:placeholder_cast:{name}")
    return errors


def save_intent_manifest(ws: Path, manifest: dict, book: int | None = None) -> Path:
    book_num = int(book if book is not None else manifest.get("book") or 1)
    path = intent_manifest_path(ws, book_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_intent_manifest(ws: Path, book: int | None = None) -> dict[str, Any]:
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    path = intent_manifest_path(ws, book_num)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def intent_is_approved(ws: Path, book: int | None = None, direction: dict | None = None) -> bool:
    direction = direction if direction is not None else load_direction(ws)
    if (direction.get("intent_status") or "").strip() == "approved":
        man = load_intent_manifest(ws, book)
        return bool(man) and (man.get("status") == "approved")
    man = load_intent_manifest(ws, book)
    return bool(man) and (man.get("status") == "approved")


def compile_and_save_intent(ws: Path, book: int | None = None) -> dict[str, Any]:
    manifest = compile_intent_manifest(ws, book=book)
    errs = validate_manifest(manifest)
    if errs:
        raise ValueError("; ".join(errs))
    save_intent_manifest(ws, manifest, book=book)
    return manifest


def approve_intent(ws: Path, book: int | None = None) -> dict[str, Any]:
    """G0 lock: recompile, validate, pin status + direction.intent_status."""
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    concept = load_concept(ws)
    manifest = compile_intent_manifest(ws, book=book_num)
    # Stale check if previous digest exists
    prev = load_intent_manifest(ws, book_num)
    if prev.get("status") == "approved" and prev.get("concept_digest") != concept_digest(concept):
        # Force recompile path — still allow re-approve after concept change
        pass
    errs = validate_manifest(manifest)
    if errs:
        raise ValueError("; ".join(errs))
    manifest["status"] = "approved"
    save_intent_manifest(ws, manifest, book=book_num)

    dir_path = ws / "direction.yaml"
    data = yaml.safe_load(dir_path.read_text(encoding="utf-8")) if dir_path.exists() else {}
    data = data or {}
    data["intent_status"] = "approved"
    data["intent_digest"] = manifest.get("manifest_digest")
    data["intent_concept_digest"] = manifest.get("concept_digest")
    # Sync POV mode from locked intent so plan/prose QC don't default to 3rd person
    pov_l = str(manifest.get("pov") or "").lower().replace("-", "_")
    if "first" in pov_l:
        data["pov_mode"] = "first_person"
    elif "third" in pov_l:
        data["pov_mode"] = "third_person_limited"
    # Sync chapter count / language / spice from concept when present
    if manifest.get("chapter_count"):
        data["total_chapters"] = int(manifest["chapter_count"])
    if manifest.get("language"):
        data["target_language"] = manifest["language"]
    dir_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    # Auto-scaffold canon_registry from locked intent (Python, 0 AI) if missing
    try:
        from factory.engine.lib.canon_registry import scaffold_canon_registry

        scaffold_canon_registry(ws, force=False)
    except Exception:
        pass
    # Intent-only path: write minimal bible/series.json stub so write/QC never hard-crash
    try:
        from factory.engine.lib.master_plan import _bible_stub_from_intent
        from factory.engine.paths import bible_path

        bpath = bible_path(ws)
        if not bpath.exists():
            stub = _bible_stub_from_intent(ws, book_num)
            bpath.parent.mkdir(parents=True, exist_ok=True)
            bpath.write_text(
                json.dumps(stub, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception:
        pass
    return manifest


def chapter_entry(manifest: dict, chapter: int) -> dict[str, Any]:
    for item in manifest.get("chapter_map") or []:
        if int(item.get("chapter") or 0) == chapter:
            return item
    return {"chapter": chapter, "beat": "", "must_include": [], "must_happen": []}


def must_include_for_chapter(manifest: dict, chapter: int) -> list[str]:
    by = manifest.get("must_include_by_chapter") or {}
    out = list(by.get(str(chapter)) or by.get(chapter) or [])
    total = int(manifest.get("chapter_count") or 0)
    for requirement in manifest.get("must_include_requirements") or []:
        if not isinstance(requirement, dict):
            continue
        text = str(requirement.get("text") or "").strip()
        scope = str(requirement.get("scope") or "")
        applies = (
            scope == "global_invariant"
            or (
                scope == "chapter_specific"
                and chapter in [int(ch) for ch in requirement.get("chapters") or []]
            )
            or (
                scope == "chapter_range"
                and int(requirement.get("start_chapter") or 1)
                <= chapter
                <= int(requirement.get("end_chapter") or total)
            )
            or (scope == "ending_only" and total > 0 and chapter == total)
        )
        if applies and text and text not in out:
            out.append(text)
    return out


def locked_pack_for_outliner(ws: Path, book: int, act_from: int, act_to: int) -> dict[str, Any]:
    """Authority package for plan tier: approved intent + optional approved narrative slice."""
    from factory.engine.lib.narrative_schema import narrative_is_approved

    manifest = load_intent_manifest(ws, book)
    if not manifest or manifest.get("status") != "approved":
        raise RuntimeError("Intent chưa approved. Chạy: compile-intent → approve-intent")

    direction = load_direction(ws)
    pack: dict[str, Any] = {
        "intent_manifest": {
            "manifest_digest": manifest.get("manifest_digest"),
            "concept_digest": manifest.get("concept_digest"),
            "pov": manifest.get("pov"),
            "cast": manifest.get("cast"),
            "chapter_count": manifest.get("chapter_count"),
            "genre_profile": manifest.get("genre_profile"),
            "language": manifest.get("language"),
            "must_avoid": manifest.get("must_avoid"),
            "surface_plot": manifest.get("surface_plot"),
            "chapter_map_slice": [
                chapter_entry(manifest, ch) for ch in range(act_from, act_to + 1)
            ],
            "must_include_by_chapter_slice": {
                str(ch): must_include_for_chapter(manifest, ch)
                for ch in range(act_from, act_to + 1)
            },
        }
    }
    # Each Outliner request is a chapter-scoped execution context. Future
    # truth/ending prose is not context for an earlier chapter.
    if act_to >= int(manifest.get("chapter_count") or 0):
        pack["intent_manifest"]["ending_book1"] = manifest.get("ending_book1")
    if narrative_is_approved(direction):
        from factory.engine.lib.narrative_compiler import (
            compile_act_constraints,
            narrative_compiler_enabled,
        )

        if narrative_compiler_enabled(ws, direction):
            constraints = compile_act_constraints(ws, act_from, act_to)
            pack["narrative_lock"] = {
                "status": "approved",
                "constraints": constraints,
                # Surface critical fences at pack root so Outliner cannot miss them
                # when skimming chapter schedules.
                "plot_boundary": constraints.get("plot_boundary"),
                "global_choices": constraints.get("global_choices"),
                "semantic_lock": constraints.get("semantic_lock"),
            }
    return pack
