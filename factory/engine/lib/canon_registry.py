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
from factory.engine.paths import book_catalog_dir, book_workspace_dir, catalog_series_dir

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
        # Title / atmosphere words (The Blue Hour, girl in blue, etc.)
        "Blue",
        "Hour",
        "Girl",
        "Child",
        "House",
        "Lake",
        "Water",
        "Attic",
        "Diary",
        "Mirror",
        "Ghost",
        "Bear",
        "Key",
        "Door",
        "Night",
        "Dawn",
        "Dusk",
        "Truth",
        "Memory",
        "Shadow",
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




def _parse_lead_from_concept_text(text: str, *, side: str) -> str | None:
    """Pull 'Female lead: Name' / 'Male lead: Name' from author_directive."""
    if side == "female":
        patterns = (
            r"(?<![A-Za-z])Female\s+lead:\s*([A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+)?)",
            r"(?<![A-Za-z])female_lead\s*[:=]\s*([A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+)?)",
        )
    else:
        patterns = (
            r"(?<![A-Za-z])Male\s+lead:\s*([A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+)?)",
            r"(?<![A-Za-z])male_lead\s*[:=]\s*([A-Z][a-zA-Z'.\-]+(?:\s+[A-Z][a-zA-Z'.\-]+)?)",
        )
    skip = {"none", "n/a", "na", "tbd", "unknown", "n.a."}
    for pat in patterns:
        m = re.search(pat, text)  # case-sensitive so Name stays Title Case
        if not m:
            m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip().rstrip(".,;")
            if name.lower() in skip or not name[0].isupper():
                continue
            return name
    return None


def resolve_lead_names_for_registry(ws: Path) -> tuple[str, str]:
    """Female/male canonical names: concept directive → bible → placeholders."""
    from factory.engine.lib.narrative_schema import load_concept

    concept = load_concept(ws)
    blob = "\n".join(
        str(concept.get(k) or "")
        for k in ("author_directive", "notes", "must_include", "title", "logline")
    )
    female = _parse_lead_from_concept_text(blob, side="female") or ""
    male = _parse_lead_from_concept_text(blob, side="male") or ""

    try:
        bible = load_series_bible(ws)
        bf, bm = lead_names(bible)
        # Concept wins when present; bible fills gaps (gothic books often omit male in concept).
        female = female or bf
        male = male or bm
    except FileNotFoundError:
        pass

    if not female:
        female = "Female Lead"
    if not male:
        male = "Male Lead"
    return female.strip(), male.strip()


def scaffold_canon_registry(
    ws: Path,
    *,
    force: bool = False,
    female: str | None = None,
    male: str | None = None,
) -> dict[str, Any]:
    """Create canon_registry.yaml from concept + bible if missing (pipeline step)."""
    path = canon_registry_path(ws)
    if path.exists() and not force:
        return {
            "ok": True,
            "created": False,
            "path": str(path),
            "message": "canon_registry.yaml already exists — not overwritten",
        }

    f_name, m_name = resolve_lead_names_for_registry(ws)
    if female:
        f_name = female.strip()
    if male:
        m_name = male.strip()

    direction = load_direction(ws)
    spice = int(direction.get("spice_level") or direction.get("spice_default") or 1)
    pov = str(direction.get("pov_mode") or "third_person_limited").strip()

    f_first = _first_token(f_name)
    m_first = _first_token(m_name)
    data: dict[str, Any] = {
        "characters": {
            "female_lead": {
                "canonical": f_name,
                "allowed_aliases": [f_first] if f_first and f_first != f_name else [],
                "forbidden_aliases": [],
            },
            "male_lead": {
                "canonical": m_name,
                "allowed_aliases": [m_first] if m_first and m_first != m_name else [],
                "forbidden_aliases": [],
            },
        },
        "pov_mode": pov,
        "spice_max": spice,
    }

    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "created": True,
        "path": str(path),
        "female_lead": f_name,
        "male_lead": m_name,
        "message": f"Created canon_registry.yaml — {f_name} / {m_name}",
    }


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


def _first_token(name: str) -> str:
    parts = str(name or "").strip().split()
    return parts[0] if parts else ""


# Placeholder / absent male-lead markers (gothic, no-ML books).
_ABSENT_MALE_LEAD_NAMES = frozenset(
    {
        "m.i.a.",
        "m.i.a",
        "mia",
        "n/a",
        "n.a.",
        "n.a",
        "na",
        "none",
        "absent",
        "tbd",
        "unknown",
        "no male lead",
        "male lead",
        "unassigned",
        "-",
        "—",
        "–",
    }
)


def is_absent_male_lead(name: str) -> bool:
    """True when male lead is intentionally missing (M.I.A. / Unassigned / none)."""
    n = _norm_name(name)
    if not n:
        return True
    if n in _ABSENT_MALE_LEAD_NAMES:
        return True
    # "M.I.A." / "M I A" variants
    if re.sub(r"[.\s]", "", n) == "mia":
        return True
    # "Unassigned (no male lead)", "no male lead — gothic", etc.
    if "no male lead" in n or n.startswith("unassigned"):
        return True
    return False


# Doctors / titled persons invented outside concept+bible cast.
_DR_NAME_RE = re.compile(
    r"\bDr\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)


def _name_tokens_for_allowlist(raw: str) -> set[str]:
    """Expand 'Dr. Ovid' / 'Lena (patient…)' into matchable tokens."""
    text = str(raw or "").strip()
    if not text:
        return set()
    # Drop parenthetical descriptors
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    out: set[str] = {text}
    # Without title
    bare = re.sub(r"^(?:Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", text, flags=re.I).strip()
    if bare:
        out.add(bare)
    for tok in bare.split():
        if len(tok) >= 2 and tok[0].isupper():
            out.add(tok)
    return {t for t in out if t}


def collect_allowed_cast_names(ws: Path, book: int = 1) -> set[str]:
    """Names declared in concept + bible supporting_cast + canon_registry leads."""
    allowed: set[str] = set()
    try:
        registry = build_canon_registry(ws, book)
        for role in LEAD_ROLES:
            char = registry.characters[role]
            allowed |= _name_tokens_for_allowlist(char.canonical)
            for a in char.allowed_aliases:
                allowed |= _name_tokens_for_allowlist(a)
    except Exception:
        pass

    try:
        from factory.engine.lib.prompt_builder import load_series_bible

        bible = load_series_bible(ws)
        for cast in bible.get("supporting_cast") or []:
            if isinstance(cast, dict):
                allowed |= _name_tokens_for_allowlist(str(cast.get("name") or ""))
    except Exception:
        pass

    try:
        from factory.engine.lib.narrative_schema import load_concept

        concept = load_concept(ws)
        blob = "\n".join(
            [
                str(concept.get("author_directive") or ""),
                str(concept.get("notes") or ""),
                "\n".join(str(x) for x in (concept.get("must_include") or [])),
                "\n".join(str(x) for x in (concept.get("must_avoid") or [])),
            ]
        )
        for m in _DR_NAME_RE.finditer(blob):
            allowed |= _name_tokens_for_allowlist(f"Dr. {m.group(1)}")
        # Bullet cast lines: "- Name:" or "- Name —"
        for m in re.finditer(
            r"^\s*[-*]\s+([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+)?)",
            blob,
            re.M,
        ):
            allowed |= _name_tokens_for_allowlist(m.group(1))
    except Exception:
        pass

    return {a for a in allowed if a and not is_absent_male_lead(a)}


def _name_allowed(name: str, allowed: set[str]) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return True
    if is_absent_male_lead(raw):
        return True
    tokens = _name_tokens_for_allowlist(raw)
    allowed_norm = {_norm_name(a) for a in allowed}
    for t in tokens:
        if _norm_name(t) in allowed_norm:
            return True
    return False


def find_invented_doctors(text: str, allowed: set[str]) -> list[str]:
    """Return Dr. X mentions not in the concept/bible allowlist."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _DR_NAME_RE.finditer(str(text or "")):
        full = f"Dr. {m.group(1)}"
        key = _norm_name(full)
        if key in seen:
            continue
        seen.add(key)
        if not _name_allowed(full, allowed):
            found.append(full)
    return found


def phone_only_cast_constraints(ws: Path) -> list[str]:
    """Hard lines for supporting cast marked phone-only / never romantic in bible."""
    lines: list[str] = []
    try:
        from factory.engine.lib.prompt_builder import load_series_bible

        bible = load_series_bible(ws)
    except Exception:
        return lines
    for cast in bible.get("supporting_cast") or []:
        if not isinstance(cast, dict):
            continue
        name = str(cast.get("name") or "").strip()
        secret = str(cast.get("secret") or "")
        blob = f"{secret} {cast.get('relation_type') or ''}".lower()
        if not name:
            continue
        if "phone" in blob and ("only" in blob or "never" in blob or "present only" in blob):
            lines.append(
                f"{name} = phone contact ONLY — never physically present on-page, "
                "not a romantic figure, not a love interest."
            )
        elif "never romantic" in blob or "not romantic" in blob:
            lines.append(f"{name} is never a romantic figure or love interest.")
    return lines


def validate_story_state_cast(ws: Path, state: dict, book: int = 1) -> list[dict[str, Any]]:
    """Flag invented doctors / undeclared cast keys in story_state."""
    allowed = collect_allowed_cast_names(ws, book)
    conflicts: list[dict[str, Any]] = []
    timeline = state.get("timeline") or []
    if isinstance(timeline, list):
        blob = "\n".join(str(x) for x in timeline)
        for doc in find_invented_doctors(blob, allowed):
            conflicts.append(
                {
                    "code": "invented_doctor_in_story_state",
                    "source": "state.json:timeline",
                    "value": doc,
                    "expected": "concept/bible cast only (e.g. Dr. Ovid phone-only)",
                }
            )
    status = state.get("character_status") or {}
    if isinstance(status, dict):
        for key, val in status.items():
            if not _name_allowed(str(key), allowed):
                # Ephemeral patients may appear; still block undeclared doctors.
                if re.search(r"\bDr\.?\b", str(key), re.I) or find_invented_doctors(
                    str(key), allowed
                ):
                    conflicts.append(
                        {
                            "code": "invented_cast_in_story_state",
                            "source": "state.json:character_status",
                            "value": key,
                            "expected": "name declared in concept/bible/canon_registry",
                        }
                    )
            rel = ""
            if isinstance(val, dict):
                rel = str(val.get("relationship_other") or "")
            for doc in find_invented_doctors(f"{key} {rel}", allowed):
                conflicts.append(
                    {
                        "code": "invented_doctor_in_story_state",
                        "source": "state.json:character_status",
                        "value": doc,
                        "expected": "concept/bible cast only (e.g. Dr. Ovid phone-only)",
                    }
                )
    return conflicts


def validate_narrative_cast(ws: Path, book: int = 1) -> list[dict[str, Any]]:
    """Flag invented doctors in narrative JSON files."""
    from factory.engine.lib.narrative_schema import narrative_dir

    allowed = collect_allowed_cast_names(ws, book)
    conflicts: list[dict[str, Any]] = []
    nd = narrative_dir(ws)
    if not nd.exists():
        return conflicts
    for path in sorted(nd.glob("*.json")):
        try:
            blob = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for doc in find_invented_doctors(blob, allowed):
            conflicts.append(
                {
                    "code": "invented_doctor_in_narrative",
                    "source": f"bible/narrative/{path.name}",
                    "value": doc,
                    "expected": "concept/bible cast only",
                }
            )
    return conflicts


def _is_plausible_lead_name(name: str) -> bool:
    """Skip descriptor phrases (e.g. 'The Girl in Blue') from narrative arc auto-forbid."""
    n = str(name or "").strip()
    if not n or len(n) > 48:
        return False
    if is_absent_male_lead(n):
        return False
    lower = n.lower()
    if lower.startswith(("the ", "a ", "an ")) and " " in n:
        return False
    return True


def _name_in_cast(name: str, cast: set[str]) -> bool:
    """True if full name or first token matches supporting-cast name set."""
    raw = str(name or "").strip()
    if not raw:
        return False
    if raw in cast or _first_token(raw) in cast:
        return True
    cast_norm = {_norm_name(c) for c in cast}
    return _norm_name(raw) in cast_norm or _norm_name(_first_token(raw)) in cast_norm


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
    forbidden = block.get("forbidden_aliases") or []
    if not isinstance(forbidden, list):
        forbidden = [forbidden]
    return CharacterCanon(
        role=role,
        canonical=str(block["canonical"]).strip(),
        allowed_aliases=[str(a).strip() for a in aliases if str(a).strip()],
        forbidden_aliases=[str(a).strip() for a in forbidden if str(a).strip()],
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


def _names_from_narrative(
    ws: Path,
    female_canonical: str,
    *,
    supporting_cast: set[str] | None = None,
    male_absent: bool = False,
) -> dict[str, set[str]]:
    """Lead-name candidates from structured narrative fields only (no prose regex scan).

    When male_absent, skip male candidates entirely (gothic / no-ML books).
    Supporting-cast names are never treated as male lead.
    """
    nd = ws / "bible" / "narrative"
    male_names: set[str] = set()
    female_names: set[str] = set()
    female_norm = _norm_name(female_canonical)
    cast = supporting_cast or set()

    arc_path = nd / "book_arc.json"
    if arc_path.exists():
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
            lia = arc.get("lead_internal_arc") or {}
            keys: list[str] = []
            if isinstance(lia, list):
                for item in lia:
                    if not isinstance(item, dict):
                        continue
                    raw = str(item.get("character") or "").strip()
                    if not raw:
                        continue
                    keys.append(re.sub(r"\s*\(.*", "", raw).strip())
            elif isinstance(lia, dict):
                keys = [str(k).strip() for k in lia if str(k).strip()]
            for k in keys:
                if not k or not _is_plausible_lead_name(k):
                    continue
                if _norm_name(k) == female_norm:
                    female_names.add(k)
                elif male_absent or _name_in_cast(k, cast):
                    # Twin / supporting / secondary arcs — not male lead.
                    continue
                else:
                    male_names.add(k)
        except (json.JSONDecodeError, OSError):
            pass

    return {"male_lead": male_names, "female_lead": female_names}


def _extract_invented_male_when_absent(
    blob: str,
    female_first: str,
    cast: set[str],
) -> str | None:
    """Strict person-name extraction for no-ML books (avoid place names like 'Sea Crest')."""
    # Prefixes may be case-insensitive; captured names stay Title-Case sensitive.
    patterns = (
        r"(?i:(?:man|neighbor|stranger|volunteer)\s+named\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"['\"]([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)['\"]\s*[—\-–].{0,60}(?i:\bman\b)",
        r"(?i:\b(?:meets|met)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        r"(?i:\blove interest\b[^.!]{0,40}\b)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        r"(?i:\bfather\b[^.!]{0,80}\b)([A-Z][a-z]+\s+[A-Z][a-z]+)\b",
        r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b[^.!]{0,40}(?i:\bfather\b)",
        r"(?i:\bthe name\b[^.!]{0,40}\b)([A-Z][a-z]+\s+[A-Z][a-z]+)\b",
        r"(?i:\bnames?\s+)([A-Z][a-z]+\s+[A-Z][a-z]+)(?i:\s+as\s+(?:her\s+)?father\b)",
    )
    hits: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, blob):
            candidate = m.group(1).strip()
            if not candidate or female_first in candidate.split():
                continue
            if candidate[0].islower() or any(p and p[0].islower() for p in candidate.split()):
                continue
            if _name_in_cast(candidate, cast):
                continue
            if not _is_plausible_lead_name(candidate):
                continue
            hits.append(candidate)
    if not hits:
        return None
    hits.sort(key=lambda n: (0 if " " in n else 1, -blob.count(n), -len(n)))
    return hits[0]


def _extract_master_plan_male_lead(
    plans: list[dict],
    female_canonical: str,
    bible: dict,
    male_canonical: str | None = None,
) -> str | None:
    if not plans:
        return None
    blob = _all_plans_text(plans)
    female_first = _first_token(female_canonical)
    cast = _supporting_cast_names(bible)
    male_absent = is_absent_male_lead(male_canonical or "")

    if male_absent:
        return _extract_invented_male_when_absent(blob, female_first, cast)

    # Prefer operator-declared male lead when it already appears in the plan.
    if male_canonical:
        male_full = str(male_canonical).strip()
        male_first = _first_token(male_full)
        if male_full and re.search(rf"\b{re.escape(male_full)}\b", blob):
            return male_full
        if male_first and male_first not in _PLAN_NAME_STOPWORDS:
            if len(re.findall(rf"\b{re.escape(male_first)}\b", blob)) >= 2:
                return male_full

    named = re.search(
        r"(?:man|neighbor)\s+named\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        blob,
        re.IGNORECASE,
    )
    if named:
        candidate = named.group(1).strip()
        if (
            female_first not in candidate.split()
            and not _name_in_cast(candidate, cast)
            and _is_plausible_lead_name(candidate)
        ):
            return candidate

    full_names: set[str] = set()
    for m in re.finditer(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b", blob):
        name = m.group(1)
        parts = name.split()
        if any(p in _PLAN_NAME_STOPWORDS for p in parts):
            continue
        if female_first in parts:
            continue
        if _name_in_cast(name, cast):
            continue
        if not _is_plausible_lead_name(name):
            continue
        full_names.add(name)

    if full_names:
        ranked = sorted(full_names, key=lambda n: blob.count(n), reverse=True)
        return ranked[0]

    counts: dict[str, int] = {}
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", blob):
        token = m.group(1)
        if token in _PLAN_NAME_STOPWORDS or token == female_first or _name_in_cast(token, cast):
            continue
        counts[token] = counts.get(token, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _collect_source_lead_names(ws: Path, book: int, registry: CanonRegistry) -> None:
    bible = load_series_bible(ws)
    female_canonical = registry.characters["female_lead"].canonical
    male_canonical = registry.characters["male_lead"].canonical
    male_absent = is_absent_male_lead(male_canonical)
    cast = _supporting_cast_names(bible)

    fn, mn = lead_names(bible)
    if mn:
        registry.source_male_lead_names["series.json"] = mn
        if not male_absent and not registry.characters["male_lead"].is_allowed(mn):
            registry.characters["male_lead"].register_forbidden(mn)
    if fn and not registry.characters["female_lead"].is_allowed(fn):
        registry.characters["female_lead"].register_forbidden(fn)

    narr = _names_from_narrative(
        ws,
        female_canonical,
        supporting_cast=cast,
        male_absent=male_absent,
    )
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
    _SKIP_FIRST_TOKENS = frozenset({"the", "a", "an"})
    plan_male = _extract_master_plan_male_lead(
        plans, female_canonical, bible, male_canonical=male_canonical
    )
    if plan_male:
        # When male is absent, an invented plan name is still recorded so approve-plan
        # can fail closed — but supporting-cast names are never extracted above.
        registry.source_male_lead_names["master_plan.json"] = plan_male
        if not registry.characters["male_lead"].is_allowed(plan_male):
            registry.characters["male_lead"].register_forbidden(plan_male)
            first = _first_token(plan_male)
            if (
                first
                and first != plan_male
                and first not in _PLAN_NAME_STOPWORDS
                and first.lower() not in _SKIP_FIRST_TOKENS
            ):
                registry.characters["male_lead"].register_forbidden(first)

    # First-token variants for structured narrative alternates only.
    # Do not expand absent-male placeholders into forbidden tokens.
    if not male_absent:
        for name in list(registry.characters["male_lead"].forbidden_aliases):
            if " " in name:
                first = _first_token(name)
                if (
                    first
                    and first.lower() not in _SKIP_FIRST_TOKENS
                    and first not in _PLAN_NAME_STOPWORDS
                ):
                    registry.characters["male_lead"].register_forbidden(first)


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

    # Invented doctors / undeclared titled cast (e.g. Dr. Mateo vs concept Dr. Ovid).
    allowed = collect_allowed_cast_names(ws, book)
    for plan in plans:
        ch = int(plan.get("chapter") or 0)
        blob = _plan_text_blob(plan)
        for doc in find_invented_doctors(blob, allowed):
            conflicts.append(
                {
                    "code": "invented_doctor_in_plan",
                    "source": f"master_plan.json:ch{ch}",
                    "value": doc,
                    "expected": "concept/bible cast only (e.g. Dr. Ovid phone-only)",
                    "detail": "named doctor not declared upstream — do not invent cast",
                }
            )

    conflicts.extend(validate_narrative_cast(ws, book))
    state_path = book_workspace_dir(ws, book) / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                conflicts.extend(validate_story_state_cast(ws, state, book))
        except (json.JSONDecodeError, OSError, TypeError):
            pass

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
