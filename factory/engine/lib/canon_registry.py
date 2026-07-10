"""Canon registry — operator-declared SSOT with machine enforcement at approve-plan."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.bible_schema import lead_names
from factory.engine.lib.master_plan import load_master_plan
from factory.engine.lib.plan_normalize import normalize_chapter_plans
from factory.engine.lib.prompt_builder import load_direction, load_series_bible
from factory.engine.paths import book_catalog_dir, catalog_series_dir

LEAD_ROLES = ("female_lead", "male_lead")

# Common English tokens that look like names in plan prose but are not characters.
_PLAN_NAME_STOPWORDS = frozenset(
    {
        "Chapter",
        "Romance",
        "Spice",
        "Write",
        "Open",
        "End",
        "Must",
        "Forbidden",
        "Plant",
        "Payoff",
        "Reveal",
        "Major",
        "Minor",
        "English",
        "Remember",
        "August",
        "July",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "June",
        "September",
        "October",
        "November",
        "December",
    }
)


@dataclass
class CharacterCanon:
    role: str
    canonical: str
    allowed_aliases: list[str] = field(default_factory=list)
    forbidden_aliases: list[str] = field(default_factory=list)

    def is_allowed(self, name: str) -> bool:
        n = _norm_name(name)
        if not n:
            return True
        if _norm_name(self.canonical) == n:
            return True
        return any(_norm_name(a) == n for a in self.allowed_aliases)

    def register_forbidden(self, name: str) -> None:
        n = _norm_name(name)
        if not n or self.is_allowed(n):
            return
        if n not in {_norm_name(x) for x in self.forbidden_aliases}:
            self.forbidden_aliases.append(name.strip())


@dataclass
class CanonRegistry:
    workspace_id: str
    book: int
    book_slug: str
    chapter_count: int
    target_language: str
    pov_mode: str
    spice_max: int
    characters: dict[str, CharacterCanon]
  # source label -> raw male lead name discovered (for cross-source reporting)
    source_male_lead_names: dict[str, str] = field(default_factory=dict)


class CanonRegistryError(Exception):
    """Raised when approve-plan is blocked by canon registry validation."""

    def __init__(self, conflicts: list[dict[str, Any]]):
        self.conflicts = conflicts
        lines = ["Canon registry blocked approve-plan:"]
        for c in conflicts:
            lines.append(
                f"  [{c.get('code', 'conflict')}] source={c.get('source')!r} "
                f"value={c.get('value')!r} expected={c.get('expected')!r}"
                + (f" — {c['detail']}" if c.get("detail") else "")
            )
        super().__init__("\n".join(lines))


def canon_registry_path(ws: Path) -> Path:
    return ws / "canon_registry.yaml"


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _first_token(name: str) -> str:
    parts = str(name or "").strip().split()
    return parts[0] if parts else ""


def resolve_workspace_book_slug(ws: Path, book: int) -> str:
    """Book slug from direction.yaml or workspace catalog — never global config.json."""
    direction = load_direction(ws)
    slug = str(direction.get("book_slug") or "").strip()
    if slug:
        return slug

    books_dir = catalog_series_dir(ws.name) / "books"
    prefix = f"{book:02d}-"
    if books_dir.exists():
        for p in sorted(books_dir.iterdir()):
            if p.is_dir() and p.name.startswith(prefix):
                return p.name
    return f"{book:02d}-{ws.name}"


def _chapter_count_from_book_yaml(ws: Path, book_slug: str) -> int | None:
    by_path = book_catalog_dir(ws.name, book_slug) / "book.yaml"
    if not by_path.exists():
        return None
    try:
        meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
        tc = meta.get("total_chapters")
        return int(tc) if tc is not None else None
    except (yaml.YAMLError, TypeError, ValueError):
        return None


def _spice_max_from_direction(direction: dict) -> int:
    for key in ("spice_max", "spice_default", "spice_level"):
        val = direction.get(key)
        if val is not None:
            return int(val)
    return 1


def _pov_mode_from_declarations(decl: dict, direction: dict) -> str:
    if decl.get("pov_mode"):
        return str(decl["pov_mode"]).strip()
    return str(direction.get("pov_mode") or "third_person_limited").strip()


def load_canon_registry_declarations(ws: Path) -> dict[str, Any]:
    path = canon_registry_path(ws)
    if not path.exists():
        raise CanonRegistryError(
            [
                {
                    "code": "missing_canon_registry",
                    "source": str(path),
                    "value": "(missing)",
                    "expected": "canon_registry.yaml with operator-declared lead names",
                    "detail": "Create canon_registry.yaml before approve-plan",
                }
            ]
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CanonRegistryError(
            [
                {
                    "code": "invalid_canon_registry",
                    "source": str(path),
                    "value": str(exc),
                    "expected": "valid YAML",
                }
            ]
        ) from exc
    if not isinstance(data, dict):
        raise CanonRegistryError(
            [
                {
                    "code": "invalid_canon_registry",
                    "source": str(path),
                    "value": type(data).__name__,
                    "expected": "mapping",
                }
            ]
        )
    chars = data.get("characters")
    if not isinstance(chars, dict):
        raise CanonRegistryError(
            [
                {
                    "code": "missing_characters",
                    "source": str(path),
                    "value": "(missing characters)",
                    "expected": "characters.female_lead / characters.male_lead",
                }
            ]
        )
    for role in LEAD_ROLES:
        block = chars.get(role)
        if not isinstance(block, dict) or not str(block.get("canonical") or "").strip():
            raise CanonRegistryError(
                [
                    {
                        "code": "missing_canonical",
                        "source": f"{path}:characters.{role}",
                        "value": block,
                        "expected": f"canonical name for {role}",
                    }
                ]
            )
    return data


def _character_canon_from_decl(role: str, block: dict) -> CharacterCanon:
    aliases = block.get("allowed_aliases") or []
    if not isinstance(aliases, list):
        aliases = [aliases]
    return CharacterCanon(
        role=role,
        canonical=str(block["canonical"]).strip(),
        allowed_aliases=[str(a).strip() for a in aliases if str(a).strip()],
    )


def _plan_text_blob(plan: dict) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "one_line_summary",
        "beat_summary",
        "opens_with",
        "cliffhanger",
        "chapter_task",
        "signature_detail_hint",
        "spice_note",
        "carries_to_next",
    ):
        v = plan.get(key, "")
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v)
    for key in ("must_happen", "must_not"):
        v = plan.get(key, [])
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
    return " ".join(parts)


def _all_plans_text(plans: list[dict]) -> str:
    return " ".join(_plan_text_blob(p) for p in plans)


def _supporting_cast_names(bible: dict) -> set[str]:
    names: set[str] = set()
    for cast in bible.get("supporting_cast") or []:
        if isinstance(cast, dict) and cast.get("name"):
            names.add(str(cast["name"]).strip())
            names.add(_first_token(str(cast["name"])))
    return {n for n in names if n}


def _names_from_narrative(ws: Path, female_canonical: str) -> dict[str, set[str]]:
    """Lead-name candidates from structured narrative fields only (no prose regex scan)."""
    nd = ws / "bible" / "narrative"
    male_names: set[str] = set()
    female_names: set[str] = set()
    female_norm = _norm_name(female_canonical)

    arc_path = nd / "book_arc.json"
    if arc_path.exists():
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
            for key in (arc.get("lead_internal_arc") or {}):
                k = str(key).strip()
                if not k:
                    continue
                if _norm_name(k) == female_norm:
                    female_names.add(k)
                else:
                    male_names.add(k)
        except (json.JSONDecodeError, OSError):
            pass

    return {"male_lead": male_names, "female_lead": female_names}


def _extract_master_plan_male_lead(plans: list[dict], female_canonical: str, bible: dict) -> str | None:
    if not plans:
        return None
    blob = _all_plans_text(plans)
    female_first = _first_token(female_canonical)
    cast = _supporting_cast_names(bible)

    named = re.search(
        r"(?:man|neighbor)\s+named\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        blob,
        re.IGNORECASE,
    )
    if named:
        candidate = named.group(1).strip()
        if female_first not in candidate.split():
            return candidate

    full_names: set[str] = set()
    for m in re.finditer(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b", blob):
        name = m.group(1)
        parts = name.split()
        if any(p in _PLAN_NAME_STOPWORDS for p in parts):
            continue
        if female_first in parts:
            continue
        if name in cast or parts[0] in cast:
            continue
        full_names.add(name)

    if full_names:
        ranked = sorted(full_names, key=lambda n: blob.count(n), reverse=True)
        return ranked[0]

    counts: dict[str, int] = {}
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", blob):
        token = m.group(1)
        if token in _PLAN_NAME_STOPWORDS or token == female_first or token in cast:
            continue
        counts[token] = counts.get(token, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _collect_source_lead_names(ws: Path, book: int, registry: CanonRegistry) -> None:
    bible = load_series_bible(ws)
    female_canonical = registry.characters["female_lead"].canonical
    male_canonical = registry.characters["male_lead"].canonical

    fn, mn = lead_names(bible)
    if mn:
        registry.source_male_lead_names["series.json"] = mn
        if not registry.characters["male_lead"].is_allowed(mn):
            registry.characters["male_lead"].register_forbidden(mn)
    if fn and not registry.characters["female_lead"].is_allowed(fn):
        registry.characters["female_lead"].register_forbidden(fn)

    narr = _names_from_narrative(ws, female_canonical)
    male_narr = narr.get("male_lead") or set()
    if male_narr:
        primary_narr = sorted(male_narr, key=len, reverse=True)[0]
        registry.source_male_lead_names["narrative/*.json"] = primary_narr
        for name in male_narr:
            if not registry.characters["male_lead"].is_allowed(name):
                registry.characters["male_lead"].register_forbidden(name)
    for name in narr.get("female_lead") or set():
        if not registry.characters["female_lead"].is_allowed(name):
            registry.characters["female_lead"].register_forbidden(name)

    plan_data = load_master_plan(ws, book)
    plans = normalize_chapter_plans(plan_data.get("chapter_plans", []))
    plan_male = _extract_master_plan_male_lead(plans, female_canonical, bible)
    if plan_male:
        registry.source_male_lead_names["master_plan.json"] = plan_male
        if not registry.characters["male_lead"].is_allowed(plan_male):
            registry.characters["male_lead"].register_forbidden(plan_male)
            first = _first_token(plan_male)
            if first and first != plan_male:
                registry.characters["male_lead"].register_forbidden(first)

    # First-token variants for structured narrative alternates only.
    for name in list(registry.characters["male_lead"].forbidden_aliases):
        if " " in name:
            registry.characters["male_lead"].register_forbidden(_first_token(name))


def build_canon_registry(ws: Path, book: int = 1) -> CanonRegistry:
    """Build registry: operator declarations + auto-discovered forbidden aliases."""
    decl = load_canon_registry_declarations(ws)
    direction = load_direction(ws)
    book_slug = resolve_workspace_book_slug(ws, book)

    direction_chapters = direction.get("total_chapters")
    book_yaml_chapters = _chapter_count_from_book_yaml(ws, book_slug)
    chapter_count = int(direction_chapters or book_yaml_chapters or 0)

    chars_decl = decl.get("characters") or {}
    characters = {
        role: _character_canon_from_decl(role, chars_decl[role]) for role in LEAD_ROLES
    }

    registry = CanonRegistry(
        workspace_id=ws.name,
        book=book,
        book_slug=book_slug,
        chapter_count=chapter_count,
        target_language=str(direction.get("target_language") or "vi").strip().lower(),
        pov_mode=_pov_mode_from_declarations(decl, direction),
        spice_max=_spice_max_from_direction(direction),
        characters=characters,
    )

    _collect_source_lead_names(ws, book, registry)
    return registry


def _forbidden_hits_in_text(text: str, role: str, registry: CanonRegistry) -> list[str]:
    char = registry.characters.get(role)
    if not char:
        return []
    hits: list[str] = []
    lower = text.lower()
    for alias in char.forbidden_aliases:
        a = alias.strip()
        if not a:
            continue
        if len(a.split()) == 1:
            pat = re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
        else:
            pat = re.compile(re.escape(a), re.IGNORECASE)
        if pat.search(lower):
            hits.append(a)
    return sorted(set(hits))


def validate_plan_against_canon_registry(ws: Path, book: int = 1) -> list[dict[str, Any]]:
    """Return structured conflicts. Empty list = pass."""
    registry = build_canon_registry(ws, book)
    conflicts: list[dict[str, Any]] = []
    male_canon = registry.characters["male_lead"]
    expected_male = male_canon.canonical

    # Cross-source male lead agreement vs operator canonical.
    source_values = {
        src: val for src, val in registry.source_male_lead_names.items() if str(val).strip()
    }
    distinct = {_norm_name(v) for v in source_values.values()}
    if len(distinct) > 1:
        for src, val in source_values.items():
            conflicts.append(
                {
                    "code": "male_lead_cross_source_mismatch",
                    "source": src,
                    "value": val,
                    "expected": expected_male,
                    "detail": f"sources disagree: {source_values}",
                }
            )

    for src, val in source_values.items():
        if not male_canon.is_allowed(val):
            conflicts.append(
                {
                    "code": "male_lead_source_mismatch",
                    "source": src,
                    "value": val,
                    "expected": expected_male,
                }
            )

    plan_data = load_master_plan(ws, book)
    plans = normalize_chapter_plans(plan_data.get("chapter_plans", []))

    # Chapter count conflicts.
    direction = load_direction(ws)
    direction_total = int(direction.get("total_chapters") or 0)
    plan_total_field = int(plan_data.get("total_chapters") or 0)
    planned = len(plans)

    if registry.chapter_count and direction_total and registry.chapter_count != direction_total:
        conflicts.append(
            {
                "code": "chapter_count_direction_internal",
                "source": "direction.yaml vs registry",
                "value": direction_total,
                "expected": registry.chapter_count,
            }
        )

    if direction_total and plan_total_field and plan_total_field != direction_total:
        conflicts.append(
            {
                "code": "chapter_count_plan_field",
                "source": "master_plan.json:total_chapters",
                "value": plan_total_field,
                "expected": direction_total,
            }
        )

    if direction_total and planned and planned != direction_total:
        conflicts.append(
            {
                "code": "chapter_count_plan_rows",
                "source": "master_plan.json:chapter_plans",
                "value": planned,
                "expected": direction_total,
            }
        )

    # Per-chapter plan checks: forbidden names + spice (no clamping).
    for plan in plans:
        ch = int(plan.get("chapter") or 0)
        blob = _plan_text_blob(plan)
        for role in LEAD_ROLES:
            for hit in _forbidden_hits_in_text(blob, role, registry):
                conflicts.append(
                    {
                        "code": "forbidden_lead_name_in_plan",
                        "source": f"master_plan.json:ch{ch}",
                        "value": hit,
                        "expected": registry.characters[role].canonical,
                        "detail": f"role={role}",
                    }
                )

        spice = plan.get("spice")
        if spice is None:
            continue
        try:
            spice_val = int(spice)
        except (TypeError, ValueError):
            continue
        if spice_val > registry.spice_max:
            conflicts.append(
                {
                    "code": "spice_exceeds_max",
                    "source": f"master_plan.json:ch{ch}",
                    "value": spice_val,
                    "expected": registry.spice_max,
                    "detail": "plan spice exceeds direction spice_max — fix plan, do not clamp",
                }
            )

    return conflicts


def format_conflicts(conflicts: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for c in conflicts:
        line = (
            f"[{c.get('code', 'conflict')}] source={c.get('source')!r} "
            f"value={c.get('value')!r} expected={c.get('expected')!r}"
        )
        if c.get("detail"):
            line += f" ({c['detail']})"
        lines.append(line)
    return lines


def replacement_patterns(registry: CanonRegistry) -> list[tuple[re.Pattern[str], str]]:
    """(pattern, canonical) pairs for forbidden aliases — longest match first."""
    pairs: list[tuple[re.Pattern[str], str]] = []
    for role in LEAD_ROLES:
        char = registry.characters[role]
        canonical = char.canonical
        for alias in sorted(char.forbidden_aliases, key=len, reverse=True):
            a = alias.strip()
            if not a or char.is_allowed(a):
                continue
            if " " in a:
                pat = re.compile(re.escape(a), re.IGNORECASE)
            else:
                pat = re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
            pairs.append((pat, canonical))
    return pairs


def sanitize_text_for_registry(text: str, registry: CanonRegistry) -> str:
    """Replace forbidden lead aliases with operator-declared canonical names."""
    if not text:
        return text
    out = text
    for pat, canonical in replacement_patterns(registry):
        out = pat.sub(canonical, out)
    return out
