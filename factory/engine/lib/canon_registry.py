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




# Honorifics that must never become a lead "first name" / alias token.
_LEAD_HONORIFIC_RE = re.compile(
    r"^(?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor|Sir|Dame|Lady|Lord)\.?\s+",
    re.IGNORECASE,
)
_LEAD_HONORIFIC_PREFIX = (
    r"(?:(?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor|Sir|Dame|Lady|Lord)\.?\s+)?"
)
# 1–4 capitalized name tokens (given + optional middle + surname).
_LEAD_NAME_TOKEN = r"[A-Z][a-zA-Z'.\-]+"
_LEAD_NAME_CORE = rf"{_LEAD_NAME_TOKEN}(?:\s+{_LEAD_NAME_TOKEN}){{0,3}}"
# Full capture may keep the honorific in the canonical string (e.g. Dr. Alistair Finch).
_LEAD_NAME_CAPTURE = rf"({_LEAD_HONORIFIC_PREFIX}{_LEAD_NAME_CORE})"
# Stop before age parenthetical, clause comma, or end.
_LEAD_NAME_STOP = r"(?=\s*[\(,;]|\s*$)"


def strip_lead_honorific(name: str) -> str:
    """Remove leading Dr./Mr./… so honorifics never become alias tokens."""
    return _LEAD_HONORIFIC_RE.sub("", str(name or "").strip()).strip()


_ALIAS_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "no",
        "male",
        "female",
        "lead",
        "unnamed",
        "narrator",
        "protagonist",
        "pov",
    }
)


def lead_name_aliases(canonical: str) -> list[str]:
    """Given/surname aliases from canonical — never includes Dr./Mr./… alone.

    Parenthetical descriptors (e.g. ``(unnamed narrator)``) are stripped before
    splitting so they do not become junk aliases like ``(unnamed``.
    """
    bare = strip_lead_honorific(canonical)
    if not bare:
        return []
    # Drop parenthetical descriptors before tokenizing.
    bare_core = re.sub(r"\([^)]*\)", " ", bare)
    bare_core = re.sub(r"\s+", " ", bare_core).strip()
    out: list[str] = []
    raw = str(canonical or "").strip()
    if bare_core and bare_core != raw:
        out.append(bare_core)
    elif bare and bare != raw:
        out.append(bare)
    for part in bare_core.split() if bare_core else bare.split():
        cleaned = part.strip(".,;:()[]{}\"'")
        if not cleaned:
            continue
        if cleaned.lower() in _ALIAS_STOPWORDS:
            continue
        if cleaned not in out:
            out.append(cleaned)
    return out


def _parse_lead_from_concept_text(text: str, *, side: str) -> str | None:
    """Pull 'Female lead: Name' / 'Male lead: Name' from author_directive.

    Captures optional honorific + 1–4 name tokens; stops at ``(`` so ages are
    excluded. Honorifics stay on the canonical string when present, but are
    stripped when deriving aliases (see ``lead_name_aliases``).
    """
    if side == "female":
        labels = (
            rf"(?<![A-Za-z])Female\s+lead:\s*{_LEAD_NAME_CAPTURE}{_LEAD_NAME_STOP}",
            rf"(?<![A-Za-z])female_lead\s*[:=]\s*{_LEAD_NAME_CAPTURE}{_LEAD_NAME_STOP}",
        )
    else:
        labels = (
            rf"(?<![A-Za-z])Male\s+lead:\s*{_LEAD_NAME_CAPTURE}{_LEAD_NAME_STOP}",
            rf"(?<![A-Za-z])male_lead\s*[:=]\s*{_LEAD_NAME_CAPTURE}{_LEAD_NAME_STOP}",
        )
    skip = {"none", "n/a", "na", "tbd", "unknown", "n.a.", "male lead", "female lead"}
    for pat in labels:
        m = re.search(pat, text)  # case-sensitive so Name stays Title Case
        if not m:
            m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        name = m.group(1).strip().rstrip(".,;")
        bare = strip_lead_honorific(name)
        check = bare.lower() if bare else name.lower()
        if check in skip or not name or not name[0].isupper():
            continue
        # Reject honorific-only captures (e.g. bare "Dr.")
        if not bare:
            continue
        return name
    return None


_FEMALE_ROLE_RE = re.compile(
    r"\b(?:female[\s_-]*lead|heroine|female[\s_-]*protagonist|fmc)\b",
    re.IGNORECASE,
)
_MALE_ROLE_RE = re.compile(
    r"\b(?:male[\s_-]*lead|hero(?!ine)|male[\s_-]*protagonist|mmc)\b",
    re.IGNORECASE,
)
_GENERIC_LEAD_ROLE_RE = re.compile(
    r"\b(?:lead|protagonist|main[\s_-]*character)\b",
    re.IGNORECASE,
)


def concept_lead_names(concept: dict[str, Any]) -> tuple[str, str]:
    """Resolve female/male leads from positive structured concept declarations.

    ``pov.character`` identifies the viewpoint lead, not the lead's gender.
    Explicit role text identifies heroine/hero first. If only one side is
    explicit, a distinct POV character marked as a generic lead fills the
    other side.
    """
    raw_characters = concept.get("characters")
    if not isinstance(raw_characters, list):
        return "", ""

    rows: list[tuple[str, str]] = []
    for item in raw_characters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "").strip()
        if name:
            rows.append((name, role))

    female = next((name for name, role in rows if _FEMALE_ROLE_RE.search(role)), "")
    male = next((name for name, role in rows if _MALE_ROLE_RE.search(role)), "")

    pov_raw = concept.get("pov")
    pov_name = ""
    if isinstance(pov_raw, dict):
        pov_name = str(pov_raw.get("character") or pov_raw.get("name") or "").strip()
    pov_role = next(
        (role for name, role in rows if _norm_name(name) == _norm_name(pov_name)),
        "",
    )

    if pov_name and _FEMALE_ROLE_RE.search(pov_role):
        female = female or pov_name
    elif pov_name and _MALE_ROLE_RE.search(pov_role):
        male = male or pov_name

    # "dark-romance lead" is gender-neutral. The explicitly declared opposite
    # side (e.g. heroine) lets us assign this distinct POV lead safely.
    if (
        pov_name
        and _GENERIC_LEAD_ROLE_RE.search(pov_role)
        and not _FEMALE_ROLE_RE.search(pov_role)
        and not _MALE_ROLE_RE.search(pov_role)
    ):
        if female and _norm_name(pov_name) != _norm_name(female):
            male = male or pov_name
        elif male and _norm_name(pov_name) != _norm_name(male):
            female = female or pov_name

    return female, male


def resolve_lead_names_for_registry(ws: Path) -> tuple[str, str]:
    """Female/male canonical names: intent → structured cast → directive → bible."""
    from factory.engine.lib.intent_manifest import load_intent_manifest
    from factory.engine.lib.narrative_schema import load_concept

    concept = load_concept(ws)
    female, male = concept_lead_names(concept)

    # Approved / compiled IntentManifest cast + POV is a legacy fallback.
    # Structured role declarations above win; POV alone never declares gender.
    try:
        man = load_intent_manifest(ws, 1)
    except (OSError, TypeError, ValueError):
        man = {}
    if man:
        pov = str(man.get("pov") or "")
        cast = [str(x).strip() for x in (man.get("cast") or []) if str(x).strip()]
        pov_name = pov.split("|")[0].split(",")[0].strip()
        if (
            not female
            and pov_name
            and len(pov_name) < 80
            and pov_name.lower() not in {"first_person", "third_person", "past", "present"}
            and ( " " in pov_name or pov_name[0].isupper())
        ):
            female = pov_name
        if cast:
            if not female:
                female = cast[0]
            # Gothic / single-POV: no romantic male lead unless clearly labeled
            if not male:
                male = "Unassigned (no male lead)"

    # Legacy structured concepts without useful role labels.
    if not female:
        pov_raw = concept.get("pov")
        if isinstance(pov_raw, dict):
            female = str(pov_raw.get("character") or pov_raw.get("name") or "").strip()
        chars = concept.get("characters")
        if isinstance(chars, list):
            names = [
                str(c.get("name") or "").strip()
                for c in chars
                if isinstance(c, dict) and str(c.get("name") or "").strip()
            ]
            if names and not female:
                female = names[0]
            if names and not male:
                male = "Unassigned (no male lead)"

    # 3) Legacy "Female lead:" lines in free text
    blob = "\n".join(
        str(concept.get(k) or "")
        for k in ("author_directive", "notes", "must_include", "title", "logline")
    )
    female = female or (_parse_lead_from_concept_text(blob, side="female") or "")
    male_from_text = _parse_lead_from_concept_text(blob, side="male") or ""
    if male_from_text:
        male = male_from_text

    try:
        bible = load_series_bible(ws)
        bf, bm = lead_names(bible)
        female = female or bf
        if not male or male.lower() in {"male lead", "unassigned", "unassigned (no male lead)"}:
            # Only take bible male if it is a real name
            if bm and bm.strip().lower() not in {
                "male lead",
                "unassigned",
                "unassigned (no male lead)",
                "m.i.a.",
                "n/a",
            }:
                male = bm
            elif not male:
                male = "Unassigned (no male lead)"
    except FileNotFoundError:
        pass

    if not female:
        female = "Female Lead"
    if not male:
        male = "Unassigned (no male lead)"
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
    pov = str(direction.get("pov_mode") or "").strip()
    if not pov:
        try:
            from factory.engine.lib.intent_manifest import load_intent_manifest

            man_pov = str(load_intent_manifest(ws, 1).get("pov") or "").lower()
            pov = "first_person" if "first" in man_pov else "third_person_limited"
        except (OSError, TypeError, ValueError):
            pov = "third_person_limited"

    data: dict[str, Any] = {
        "characters": {
            "female_lead": {
                "canonical": f_name,
                "allowed_aliases": lead_name_aliases(f_name),
                "forbidden_aliases": [],
            },
            "male_lead": {
                "canonical": m_name,
                "allowed_aliases": lead_name_aliases(m_name),
                "forbidden_aliases": [],
            },
        },
        "pov_mode": pov,
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


def locked_canon_names_payload(ws: Path, book: int = 1) -> dict[str, Any] | None:
    """Outliner LOCKED-NAMES block from canon_registry (None if registry missing)."""
    if not canon_registry_path(ws).exists():
        return None
    registry = build_canon_registry(ws, book)
    female = registry.characters["female_lead"]
    male = registry.characters["male_lead"]
    return {
        "female_lead": female.canonical,
        "male_lead": male.canonical,
        "female_aliases": list(female.allowed_aliases),
        "male_aliases": list(male.allowed_aliases),
        "instruction": (
            "LOCKED CANON NAMES — use these lead names VERBATIM in every "
            "chapter_plan field (summaries, must_happen, knowledge keys, etc.). "
            "Do not shorten, expand, invent, or substitute surnames/titles. "
            "Allowed aliases are short forms only; prefer the canonical full name."
        ),
    }


def sync_bible_leads_from_registry(ws: Path, book: int = 1) -> dict[str, Any]:
    """Write series.json lead names from canon_registry so approve sources agree.

    No-op when registry is missing. Returns {updated, female, male}.
    """
    if not canon_registry_path(ws).exists():
        return {"updated": False, "reason": "no_canon_registry"}

    from factory.engine.paths import bible_path

    path = bible_path(ws)
    if not path.exists():
        return {"updated": False, "reason": "no_series_json"}

    registry = build_canon_registry(ws, book)
    f_name = registry.characters["female_lead"].canonical
    m_name = registry.characters["male_lead"].canonical
    data = json.loads(path.read_text(encoding="utf-8"))
    leads = data.setdefault("leads", {})
    if not isinstance(leads, dict):
        leads = {}
        data["leads"] = leads
    female = leads.setdefault("female", {})
    male = leads.setdefault("male", {})
    if not isinstance(female, dict):
        female = {}
        leads["female"] = female
    if not isinstance(male, dict):
        male = {}
        leads["male"] = male

    changed = False
    if str(female.get("name") or "").strip() != f_name:
        female["name"] = f_name
        changed = True
    if str(male.get("name") or "").strip() != m_name:
        male["name"] = m_name
        changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "updated": changed,
        "female": f_name,
        "male": m_name,
        "path": str(path),
    }


def _norm_name(name: str) -> str:
    # Narrative JSON commonly uses identifier keys (``victor_rhodes``) for the
    # same character whose display/canon name is ``Victor Rhodes``.
    text = str(name or "").strip().replace("_", " ")
    return re.sub(r"\s+", " ", text).lower()


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
        if len(tok) >= 2 and tok[0].isupper() and tok.lower() not in {
            "the", "a", "an", "of", "and", "or", "dr", "mr", "mrs", "ms", "miss"
        }:
            out.add(tok)
    # Never allow bare honorifics as cast tokens.
    return {
        t
        for t in out
        if t
        and not re.fullmatch(r"(?:Dr|Mr|Mrs|Ms|Miss)\.?", t, flags=re.I)
        and t.lower() not in {"the", "a", "an"}
    }


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
        for key in ("supporting_cast", "cast"):
            for cast in bible.get(key) or []:
                if isinstance(cast, dict):
                    allowed |= _name_tokens_for_allowlist(str(cast.get("name") or ""))
                elif isinstance(cast, str):
                    allowed |= _name_tokens_for_allowlist(cast)
        leads = bible.get("leads") if isinstance(bible.get("leads"), dict) else {}
        for lead in leads.values():
            if isinstance(lead, dict):
                allowed |= _name_tokens_for_allowlist(str(lead.get("name") or ""))
            elif isinstance(lead, str):
                allowed |= _name_tokens_for_allowlist(lead)
    except Exception:
        pass

    try:
        from factory.engine.lib.intent_manifest import _infer_cast
        from factory.engine.lib.narrative_schema import load_concept

        concept = load_concept(ws)
        directive = str(concept.get("author_directive") or "")
        for name in _infer_cast(concept, directive):
            allowed |= _name_tokens_for_allowlist(name)
        blob = "\n".join(
            [
                directive,
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
        # Locked role declarations: ``- ORIGIN KILLER (...): Julian Croft —``.
        # The generic bullet matcher above sees the role label, not the name.
        for m in re.finditer(
            r"^\s*[-*]\s+[^:\n]{1,100}:\s*"
            r"([A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,2})"
            r"(?=\s+(?:—|-)|\s*\(|\s*$)",
            blob,
            re.M,
        ):
            allowed |= _name_tokens_for_allowlist(m.group(1))
    except Exception:
        pass

    return {a for a in allowed if a and not is_absent_male_lead(a)}


_PLAN_PERSON_NAME_RE = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
    r"(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){1,2})\b"
)
_NON_PERSON_NAME_SUFFIXES = frozenset(
    {
        "company", "corporation", "corp", "inc", "llc", "ltd", "holdings",
        "group", "foundation", "institute", "university", "hospital", "clinic",
        "department", "agency", "bureau", "office", "street", "road", "avenue",
        "city", "county", "district", "river", "lake", "mountain", "hotel",
        "warehouse", "marina", "network", "podcast", "case", "file",
    }
)
_PERSON_CONTEXT_RE = re.compile(
    r"\b(?:named|victim|woman|girl|man|boy|person|mother|father|sister|brother|"
    r"daughter|son|wife|husband|friend|lawyer|doctor|detective|killer|murderer|"
    r"witness|suspect|podcaster|coroner|hacker|intermediary|member)\b",
    re.I,
)
_NAME_LEADING_CONTEXT = frozenset(
    {
        "as", "when", "while", "after", "before", "during", "then", "later",
        "inside", "outside", "once", "because", "although", "if",
        # Imperatives and sentence-leading verbs in plan prose are not part of
        # a person's name.  In particular, "Do NOT" is a prohibition and
        # "Shows Grant" is a verb plus a real cast member, not a two-word name.
        "do", "does", "did", "show", "shows", "include", "stage", "have",
        "keep", "let",
    }
)
_PERSON_ROLE_PREFIXES = frozenset(
    {
        "detective", "officer", "agent", "attorney", "lawyer", "doctor",
        "dr", "mr", "mrs", "ms", "professor", "judge",
    }
)


def _clean_plan_person_candidate(raw: str) -> tuple[str, bool]:
    text = str(raw or "").strip()
    possessive = bool(re.search(r"['’]s$", text, flags=re.I))
    text = re.sub(r"['’]s$", "", text, flags=re.I).strip()
    words = text.split()
    while len(words) >= 2 and (
        words[0].lower().rstrip(".") in _NAME_LEADING_CONTEXT
        or words[0].lower().rstrip(".") in _PERSON_ROLE_PREFIXES
    ):
        words = words[1:]
    return " ".join(words), possessive


def _full_person_name_allowed(name: str, allowed: set[str]) -> bool:
    """Require the full proper name, not a coincidental shared first/surname."""
    norm = _norm_name(
        re.sub(r"^(?:Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", str(name), flags=re.I)
    )
    return norm in {
        _norm_name(re.sub(r"^(?:Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", a, flags=re.I))
        for a in allowed
        if " " in re.sub(r"^(?:Dr|Mr|Mrs|Ms|Miss)\.?\s+", "", a, flags=re.I).strip()
    }


def _looks_like_person_mention(
    text: str,
    start: int,
    end: int,
    name: str,
    *,
    possessive: bool = False,
) -> bool:
    """Conservative person-vs-texture classifier for plan proper nouns."""
    words = name.lower().split()
    if words[-1].rstrip(".") in _NON_PERSON_NAME_SUFFIXES:
        return False
    if words[0] in {
        "the", "must", "write", "chapter", "act", "intent", "clue",
        "payoff", "reveal", "isolation",
    }:
        return False
    window = text[max(0, start - 70): min(len(text), end + 70)]
    after = text[end: min(len(text), end + 3)]
    return bool(
        _PERSON_CONTEXT_RE.search(window)
        or possessive
        or re.match(r"['’]s\b", after)
        or re.search(
            re.escape(name)
            + r"\s+(?:says?|said|asks?|asked|walks?|looks?|calls?|confesses?|"
            r"admits?|knows?|learns?|finds?|killed|murdered|died|vanished)\b",
            window,
        )
    )


def find_recurring_invented_plan_characters(
    plans: list[dict],
    allowed: set[str],
    *,
    min_chapters: int = 2,
) -> list[dict[str, Any]]:
    """WARN-only recurring person names absent from upstream cast.

    Requiring person context and recurrence across distinct chapters keeps
    one-off texture (companies, places, chapter titles) quiet.
    """
    chapters_by_name: dict[str, set[int]] = {}
    display_by_norm: dict[str, str] = {}
    for plan in plans:
        ch = int(plan.get("chapter") or 0)
        text = _plan_text_blob(plan)
        seen_here: set[str] = set()
        for match in _PLAN_PERSON_NAME_RE.finditer(text):
            name, possessive = _clean_plan_person_candidate(match.group(1))
            if len(name.split()) < 2:
                continue
            norm = _norm_name(name)
            if norm in seen_here or _full_person_name_allowed(name, allowed):
                continue
            if not _looks_like_person_mention(
                text,
                match.start(1),
                match.end(1),
                name,
                possessive=possessive,
            ):
                continue
            seen_here.add(norm)
            display_by_norm.setdefault(norm, name)
            chapters_by_name.setdefault(norm, set()).add(ch)
    warnings: list[dict[str, Any]] = []
    for norm, chapters in chapters_by_name.items():
        valid_chapters = sorted(ch for ch in chapters if ch > 0)
        if len(valid_chapters) < min_chapters:
            continue
        warnings.append(
            {
                "code": "outliner_invented_recurring_character",
                "name": display_by_norm[norm],
                "chapter": valid_chapters[0],
                "chapters": valid_chapters,
            }
        )
    return sorted(warnings, key=lambda item: (item["chapter"], item["name"]))


def scrub_recurring_invented_plan_characters(
    plans: list[dict],
    allowed: set[str],
) -> tuple[list[dict], list[str]]:
    """Replace recurring undeclared proper names with an unnamed role.

    This is the deterministic counterpart to the cast allowlist.  The model may
    invent texture, but a person recurring across chapters must be declared
    upstream.  Narrative metadata is compiler-owned and is therefore untouched.
    """
    warnings = find_recurring_invented_plan_characters(plans, allowed)
    names = sorted(
        {str(item.get("name") or "") for item in warnings if item.get("name")},
        key=len,
        reverse=True,
    )
    if not names:
        return plans, []

    all_text = "\n".join(_plan_text_blob(plan) for plan in plans)

    def replacement_for(name: str) -> str:
        titled = re.search(
            rf"\b(Detective|Officer|Agent|Attorney|Lawyer|Doctor|Dr\.?|"
            rf"Judge)\s+{re.escape(name)}\b",
            all_text,
            re.I,
        )
        if titled:
            role = titled.group(1).lower().rstrip(".")
            if role == "dr":
                role = "doctor"
            return f"the unnamed {role}"
        return "the unnamed contact"

    replacements = {name: replacement_for(name) for name in names}

    def scrub_value(value: Any) -> Any:
        if isinstance(value, str):
            out = value
            for name, replacement in replacements.items():
                # Consume an optional role prefix so we never produce
                # "Detective the unnamed detective".
                out = re.sub(
                    rf"\b(?:Detective|Officer|Agent|Attorney|Lawyer|Doctor|"
                    rf"Dr\.?|Judge)\s+{re.escape(name)}\b",
                    replacement,
                    out,
                    flags=re.I,
                )
                out = re.sub(
                    rf"\b{re.escape(name)}\b",
                    replacement,
                    out,
                    flags=re.I,
                )
            return out
        if isinstance(value, list):
            return [scrub_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: val if key == "narrative" else scrub_value(val)
                for key, val in value.items()
            }
        return value

    out = [scrub_value(dict(plan)) for plan in plans]
    notes = [f"{name}->{replacements[name]}" for name in names]
    return out, notes


def warn_invented_plan_characters(
    ws: Path,
    plans: list[dict],
    book: int = 1,
) -> list[dict[str, Any]]:
    """Print operator-facing WARNs; never block or auto-register names."""
    from factory.engine.lib.catalog import safe_print

    warnings = find_recurring_invented_plan_characters(
        plans, collect_allowed_cast_names(ws, book)
    )
    for warning in warnings:
        chapters = ",".join(f"ch{ch}" for ch in warning["chapters"])
        safe_print(
            f"  [plan-cast WARN] Outliner invented: {warning['name']} "
            f"@ ch{warning['chapter']} (recurs {chapters}) — "
            "operator duyệt hoặc khóa vào concept."
        )
    return warnings


def locked_cast_payload(ws: Path, book: int = 1) -> list[dict[str, str]]:
    """Named cast Outliner may use — concept.characters + bible + leads."""
    from factory.engine.lib.narrative_schema import load_concept, normalize_concept_characters

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(name: str, role: str = "") -> None:
        name = str(name or "").strip()
        if not name or is_absent_male_lead(name):
            return
        key = _norm_name(name)
        if key in seen:
            return
        seen.add(key)
        rows.append({"name": name, "role": str(role or "").strip()})

    try:
        concept = load_concept(ws)
        for row in normalize_concept_characters(concept.get("characters")):
            _add(row.get("name", ""), row.get("role", ""))
        directive = str(concept.get("author_directive") or "")
        for m in re.finditer(
            r"^\s*[-*]\s+([^:\n]{1,80}):\s*"
            r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
            r"(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){1,2})",
            directive,
            re.M,
        ):
            _add(m.group(2), m.group(1))
    except Exception:
        pass

    try:
        bible = load_series_bible(ws)
        leads = bible.get("leads") if isinstance(bible.get("leads"), dict) else {}
        female = leads.get("female") if isinstance(leads.get("female"), dict) else {}
        male = leads.get("male") if isinstance(leads.get("male"), dict) else {}
        _add(str(female.get("name") or ""), "female_lead")
        _add(str(male.get("name") or ""), "male_lead")
        for cast in list(bible.get("supporting_cast") or []) + list(bible.get("cast") or []):
            if isinstance(cast, dict):
                _add(str(cast.get("name") or ""), str(cast.get("relation_type") or ""))
            elif isinstance(cast, str):
                _add(cast, "")
    except Exception:
        pass

    try:
        registry = build_canon_registry(ws, book)
        for role in LEAD_ROLES:
            _add(registry.characters[role].canonical, role)
    except Exception:
        pass

    return rows


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
    # Honorific alone is never a lead name (``Mrs`` from ``Mrs. Gable``).
    if re.fullmatch(
        r"(?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor|Sir|Dame|Lady|Lord)\.?",
        n,
        flags=re.I,
    ):
        return False
    return True


def _person_name_capture() -> str:
    """Honorific-aware person name for invented-male regex groups."""
    return (
        r"((?:(?:Dr|Mr|Mrs|Ms|Miss)\.?\s+)?"
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
    )


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


def resolve_spice_max_from_direction(direction: dict) -> int:
    """Book-wide spice ceiling from direction (not per-chapter spice_default)."""
    for key in ("spice_max", "spice_level"):
        val = direction.get(key)
        if val is not None:
            return int(val)
    raise CanonRegistryError(
        [
            {
                "code": "missing_spice_max",
                "source": "direction.yaml",
                "value": "(missing)",
                "expected": "spice_max or spice_level",
                "detail": (
                    "Book spice ceiling required in direction.yaml; "
                    "spice_default is per-chapter baseline only"
                ),
            }
        ]
    )


def _spice_max_from_direction(direction: dict) -> int:
    return resolve_spice_max_from_direction(direction)


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
            names |= _name_tokens_for_allowlist(str(cast["name"]))
        elif isinstance(cast, str) and cast.strip():
            names |= _name_tokens_for_allowlist(cast)
    return {n for n in names if n}


def _names_from_narrative(
    ws: Path,
    female_canonical: str,
    male_canonical: str,
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
    male_norm = _norm_name(male_canonical)
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
                elif _norm_name(k) == male_norm:
                    male_names.add(k)
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
    """Strict person-name extraction for no-ML books (avoid place names like 'Sea Crest').

    Husband / male target names declared in plan are NOT romance leads — skip them.
    """
    from factory.engine.lib.locked_names import extract_husband_from_plan_blob

    husband = extract_husband_from_plan_blob(blob) or ""
    husband_first = husband.split()[0] if husband else ""

    # Prefixes may be case-insensitive; captured names stay Title-Case sensitive.
    name = _person_name_capture()
    patterns = (
        rf"(?i:(?:man|neighbor|stranger|volunteer)\s+named\s+){name}",
        rf"['\"]{name}['\"]\s*[—\-–].{{0,60}}(?i:\bman\b)",
        rf"(?i:\b(?:meets|met)\s+){name}\b",
        rf"(?i:\blove interest\b[^.!]{{0,40}}\b){name}\b",
        rf"(?i:\bfather\b[^.!]{{0,80}}\b){name}\b",
        rf"{name}\b[^.!]{{0,40}}(?i:\bfather\b)",
        rf"(?i:\bthe name\b[\s'\"“”‘’—\-–:]*){name}\b",
        rf"(?i:\bnames?\s+){name}(?i:\s+as\s+(?:her\s+)?father\b)",
    )
    hits: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, blob):
            candidate = m.group(1).strip()
            if not candidate or female_first in candidate.split():
                continue
            if husband and (
                candidate == husband
                or candidate.split()[0] == husband_first
            ):
                continue
            # Reject lowercase-start tokens inside the capture
            parts = candidate.replace(".", " ").split()
            if any(p and p[0].islower() for p in parts if p.lower() not in {"dr", "mr", "mrs", "ms", "miss"}):
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
        male_canonical,
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
                    "detail": (
                        "plan spice exceeds book ceiling "
                        "(direction spice_max or spice_level) — fix plan, do not clamp"
                    ),
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

    # Recurring undeclared people (Elise class) — BLOCK approve until operator locks name.
    for warning in find_recurring_invented_plan_characters(plans, allowed):
        chapters = ",".join(f"ch{c}" for c in warning["chapters"])
        conflicts.append(
            {
                "code": "outliner_invented_recurring_character",
                "source": f"master_plan.json:ch{warning['chapter']}",
                "value": warning["name"],
                "expected": "concept.characters / LOCKED CAST / bible supporting_cast",
                "detail": (
                    f"recurs {chapters} — khóa tên vào Cast UI hoặc concept trước approve; "
                    "không để Outliner bịa vai plot"
                ),
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

    # Catch a generated surname swap even when that exact bad full name was
    # never seen before (for example "Calder Hart" when canon is
    # "Calder Reed").  Only unique lead given names are eligible, and only a
    # capitalized surname token is replaced, so ordinary uses of the given name
    # remain untouched.
    given_names: dict[str, list[str]] = {}
    for role in LEAD_ROLES:
        canonical = strip_lead_honorific(registry.characters[role].canonical)
        parts = canonical.split()
        if len(parts) < 2 or canonical.lower().startswith("unassigned"):
            continue
        given_names.setdefault(parts[0].casefold(), []).append(canonical)
    for candidates in given_names.values():
        if len(candidates) != 1:
            continue
        canonical = candidates[0]
        parts = canonical.split()
        given, surname = parts[0], parts[-1]
        pat = re.compile(
            rf"\b{re.escape(given)}\s+(?!{re.escape(surname)}\b)"
            rf"[A-Z][A-Za-z'.-]+\b"
        )
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


def sanitize_json_for_registry(value: Any, registry: CanonRegistry) -> Any:
    """Recursively seal generated JSON prose to canonical lead names."""
    if isinstance(value, str):
        return sanitize_text_for_registry(value, registry)
    if isinstance(value, list):
        return [sanitize_json_for_registry(item, registry) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize_json_for_registry(item, registry)
            for key, item in value.items()
        }
    return value
