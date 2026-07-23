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


def lead_name_aliases(canonical: str) -> list[str]:
    """Given/surname aliases from canonical — never includes Dr./Mr./… alone."""
    bare = strip_lead_honorific(canonical)
    if not bare:
        return []
    parts = bare.split()
    out: list[str] = []
    if bare != str(canonical or "").strip():
        out.append(bare)
    for part in parts:
        if part and part not in out:
            out.append(part)
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
    pov = str(direction.get("pov_mode") or "third_person_limited").strip()

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


def _arc_lead_display_names(ws: Path) -> list[str]:
    """Ordered display names from bible/narrative/book_arc.json lead_internal_arc."""
    arc_path = ws / "bible" / "narrative" / "book_arc.json"
    if not arc_path.exists():
        return []
    try:
        arc = json.loads(arc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    lia = arc.get("lead_internal_arc") or {}
    keys: list[str] = []
    if isinstance(lia, list):
        for item in lia:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("character") or "").strip()
            if raw:
                keys.append(re.sub(r"\s*\(.*", "", raw).strip())
    elif isinstance(lia, dict):
        keys = [str(k).strip() for k in lia if str(k).strip()]
    out: list[str] = []
    for k in keys:
        display = _arc_key_as_display_name(k)
        if display and _is_plausible_lead_name(display):
            out.append(display)
    return out


def _ensure_supporting_cast_name(bible: dict[str, Any], name: str, *, note: str) -> bool:
    """Append ``name`` to supporting_cast if missing. Returns True if mutated."""
    cast = bible.get("supporting_cast")
    if not isinstance(cast, list):
        cast = []
        bible["supporting_cast"] = cast
    for row in cast:
        if isinstance(row, dict) and _matches_declared_lead(
            str(row.get("name") or ""), name, []
        ):
            return False
        if isinstance(row, str) and _matches_declared_lead(row, name, []):
            return False
    cast.append(
        {
            "name": name,
            "relation_to": "series",
            "relation_type": note,
            "alive": True,
            "secret": "",
        }
    )
    return True


def sync_canon_leads_from_narrative(ws: Path, book: int | None = None) -> dict[str, Any]:
    """Align canon_registry + series.json leads with narrative lead_internal_arc.

    Root cause of recurring approve-plan failures on Book N: develop-narrative
    invents/promotes a new POV (e.g. Pierre) while canon_registry / series.json
    still freeze Book-1 leads (e.g. Elias). Call after develop and before approve.

    - Female arc key matching current female_lead is kept.
    - First non-female arc key becomes male_lead when it differs from registry.
    - Previous male_lead is demoted into series.json supporting_cast.
    - No-op when absent-male placeholder or no usable arc keys.
    """
    path = canon_registry_path(ws)
    if not path.exists():
        return {"ok": False, "synced": False, "reason": "no_canon_registry"}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"ok": False, "synced": False, "reason": "invalid_canon_registry"}
    if not isinstance(data, dict):
        return {"ok": False, "synced": False, "reason": "invalid_canon_registry"}

    chars = data.get("characters") or {}
    if not isinstance(chars, dict):
        return {"ok": False, "synced": False, "reason": "missing_characters"}

    female_block = chars.get("female_lead") if isinstance(chars.get("female_lead"), dict) else {}
    male_block = chars.get("male_lead") if isinstance(chars.get("male_lead"), dict) else {}
    female_can = str(female_block.get("canonical") or "").strip()
    male_can = str(male_block.get("canonical") or "").strip()
    if is_absent_male_lead(male_can):
        return {"ok": True, "synced": False, "reason": "absent_male_lead"}

    arc_names = _arc_lead_display_names(ws)
    if not arc_names:
        return {"ok": True, "synced": False, "reason": "no_arc_leads"}

    f_aliases = [str(a) for a in (female_block.get("allowed_aliases") or []) if str(a).strip()]
    m_aliases = [str(a) for a in (male_block.get("allowed_aliases") or []) if str(a).strip()]

    female_hit = next(
        (n for n in arc_names if _matches_declared_lead(n, female_can, f_aliases)),
        None,
    )
    # Prefer full form already in registry when arc uses first name only
    new_female = female_can
    if female_hit and " " in female_hit and _norm_name(female_hit) != _norm_name(female_can):
        new_female = female_hit

    male_candidates = [
        n
        for n in arc_names
        if not _matches_declared_lead(n, new_female, f_aliases + lead_name_aliases(new_female))
    ]
    if not male_candidates:
        return {"ok": True, "synced": False, "reason": "no_male_arc_candidate"}

    # Prefer candidate that already matches registry; else longest / first arc male
    matched = next(
        (n for n in male_candidates if _matches_declared_lead(n, male_can, m_aliases)),
        None,
    )
    if matched:
        return {
            "ok": True,
            "synced": False,
            "reason": "already_aligned",
            "female_lead": new_female,
            "male_lead": male_can,
        }

    # New POV male — prefer full name (has space) over single token
    male_candidates_sorted = sorted(
        male_candidates, key=lambda n: (0 if " " in n else 1, -len(n))
    )
    new_male = male_candidates_sorted[0]
    if _matches_declared_lead(new_male, male_can, m_aliases):
        return {"ok": True, "synced": False, "reason": "already_aligned"}

    old_male = male_can
    changed: list[str] = []

    chars["female_lead"] = {
        "canonical": new_female or female_can,
        "allowed_aliases": lead_name_aliases(new_female or female_can),
        "forbidden_aliases": [],
    }
    chars["male_lead"] = {
        "canonical": new_male,
        "allowed_aliases": lead_name_aliases(new_male),
        "forbidden_aliases": [],
    }
    data["characters"] = chars
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    changed.append("canon_registry.yaml")

    bible_path = ws / "bible" / "series.json"
    if bible_path.exists():
        try:
            bible = json.loads(bible_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            bible = None
        if isinstance(bible, dict):
            leads = bible.get("leads")
            if not isinstance(leads, dict):
                leads = {}
                bible["leads"] = leads
            female_lead = leads.get("female") if isinstance(leads.get("female"), dict) else {}
            male_lead = leads.get("male") if isinstance(leads.get("male"), dict) else {}
            female_lead["name"] = new_female or female_can
            male_lead["name"] = new_male
            leads["female"] = female_lead
            leads["male"] = male_lead
            if old_male and not _matches_declared_lead(old_male, new_male, lead_name_aliases(new_male)):
                if _ensure_supporting_cast_name(
                    bible,
                    old_male,
                    note=(
                        f"Prior series male lead demoted after Book "
                        f"{int(book or load_direction(ws).get('book') or 1)} "
                        f"POV shift to {new_male}"
                    ),
                ):
                    changed.append("series.json:supporting_cast")
            bible_path.write_text(
                json.dumps(bible, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if "series.json:supporting_cast" not in changed:
                changed.append("series.json:leads")

    return {
        "ok": True,
        "synced": True,
        "female_lead": new_female or female_can,
        "male_lead": new_male,
        "previous_male_lead": old_male,
        "updated": changed,
        "message": (
            f"Synced leads from narrative: male_lead "
            f"{old_male!r} → {new_male!r}"
        ),
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
    """Case-fold + treat `_`/`-` as spaces so arc slugs match display names.

    Narrative ``lead_internal_arc`` often keys characters as ``stellan_marsh`` while
    series.json / registry use ``Stellan Marsh``. Without underscore folding those
    disagree and block approve-plan as a false name conflict.
    """
    s = str(name or "").strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s)


def _arc_key_as_display_name(key: str) -> str:
    """Map snake_case arc keys to Title Case display names; leave real names alone."""
    raw = str(key or "").strip()
    if not raw:
        return raw
    if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", raw):
        return " ".join(part.capitalize() for part in raw.split("_"))
    return raw


def _first_token(name: str) -> str:
    # Normalize snake_case arc keys first; keep Title Case for normal display names.
    parts = _arc_key_as_display_name(name).strip().split()
    return parts[0] if parts else ""


def _matches_declared_lead(
    name: str,
    canonical: str,
    aliases: list[str] | None = None,
) -> bool:
    """True if ``name`` is the declared lead or an allowed short form (first token / alias).

    Narrative ``lead_internal_arc`` often keys ``Sofia`` / ``Elias`` while registry
    stores ``Sofia Bellini`` / ``Elias van Doren``. Exact-norm mismatch previously
    misclassified the female first name as a forbidden male lead.
    """
    n = _norm_name(name)
    if not n or not str(canonical or "").strip():
        return False
    if n == _norm_name(canonical):
        return True
    ft = _first_token(name)
    c_ft = _first_token(canonical)
    if ft and c_ft and _norm_name(ft) == _norm_name(c_ft):
        return True
    for a in aliases or []:
        an = _norm_name(str(a))
        if not an:
            continue
        if n == an or (ft and _norm_name(ft) == an):
            return True
    return False


def _resolve_source_male_key(name: str, male: CharacterCanon) -> str:
    """Map any allowed male form to one comparison key (operator canonical)."""
    if male.is_allowed(name) or _matches_declared_lead(
        name, male.canonical, male.allowed_aliases
    ):
        return _norm_name(male.canonical)
    return _norm_name(name)


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
            names.add(str(cast["name"]).strip())
            names.add(_first_token(str(cast["name"])))
    return {n for n in names if n}


def _names_from_narrative(
    ws: Path,
    female_canonical: str,
    *,
    supporting_cast: set[str] | None = None,
    male_absent: bool = False,
    female_aliases: list[str] | None = None,
    male_canonical: str | None = None,
    male_aliases: list[str] | None = None,
) -> dict[str, set[str]]:
    """Lead-name candidates from structured narrative fields only (no prose regex scan).

    When male_absent, skip male candidates entirely (gothic / no-ML books).
    Supporting-cast names are never treated as male lead.
    First-name arc keys (``Sofia``, ``Elias``) match full declared leads.
    """
    nd = ws / "bible" / "narrative"
    male_names: set[str] = set()
    female_names: set[str] = set()
    cast = supporting_cast or set()
    f_aliases = list(female_aliases or [])
    m_aliases = list(male_aliases or [])

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
                display = _arc_key_as_display_name(k)
                if not display or not _is_plausible_lead_name(display):
                    continue
                if _matches_declared_lead(display, female_canonical, f_aliases):
                    female_names.add(display)
                elif male_canonical and _matches_declared_lead(
                    display, male_canonical, m_aliases
                ):
                    if not male_absent:
                        male_names.add(display)
                elif male_absent or _name_in_cast(display, cast):
                    # Twin / supporting / secondary arcs — not male lead.
                    continue
                else:
                    # Unknown third arc character — only treat as male-lead
                    # candidate when it does not look like the female lead.
                    male_names.add(display)
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
    female = registry.characters["female_lead"]
    male = registry.characters["male_lead"]
    female_canonical = female.canonical
    male_canonical = male.canonical
    male_absent = is_absent_male_lead(male_canonical)
    cast = _supporting_cast_names(bible)

    fn, mn = lead_names(bible)
    if mn:
        registry.source_male_lead_names["series.json"] = mn
        if not male_absent and not male.is_allowed(mn) and not _matches_declared_lead(
            mn, male_canonical, male.allowed_aliases
        ):
            male.register_forbidden(mn)
    if fn and not female.is_allowed(fn) and not _matches_declared_lead(
        fn, female_canonical, female.allowed_aliases
    ):
        female.register_forbidden(fn)

    narr = _names_from_narrative(
        ws,
        female_canonical,
        supporting_cast=cast,
        male_absent=male_absent,
        female_aliases=female.allowed_aliases,
        male_canonical=male_canonical,
        male_aliases=male.allowed_aliases,
    )
    male_narr = narr.get("male_lead") or set()
    if male_narr:
        # Prefer full declared form when short arc keys are present
        preferred = None
        for name in male_narr:
            if _matches_declared_lead(name, male_canonical, male.allowed_aliases):
                preferred = male_canonical
                break
        primary_narr = preferred or sorted(male_narr, key=len, reverse=True)[0]
        registry.source_male_lead_names["narrative/*.json"] = primary_narr
        for name in male_narr:
            if female.is_allowed(name) or _matches_declared_lead(
                name, female_canonical, female.allowed_aliases
            ):
                continue  # never forbid female lead tokens on male_lead
            if male.is_allowed(name) or _matches_declared_lead(
                name, male_canonical, male.allowed_aliases
            ):
                continue
            male.register_forbidden(name)
    for name in narr.get("female_lead") or set():
        if female.is_allowed(name) or _matches_declared_lead(
            name, female_canonical, female.allowed_aliases
        ):
            continue
        female.register_forbidden(name)

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
        if not (
            male.is_allowed(plan_male)
            or _matches_declared_lead(plan_male, male_canonical, male.allowed_aliases)
        ):
            if not (
                female.is_allowed(plan_male)
                or _matches_declared_lead(
                    plan_male, female_canonical, female.allowed_aliases
                )
            ):
                male.register_forbidden(plan_male)
                first = _first_token(plan_male)
                if (
                    first
                    and first != plan_male
                    and first not in _PLAN_NAME_STOPWORDS
                    and first.lower() not in _SKIP_FIRST_TOKENS
                    and not _matches_declared_lead(
                        first, female_canonical, female.allowed_aliases
                    )
                ):
                    male.register_forbidden(first)

    # First-token variants for structured narrative alternates only.
    # Do not expand absent-male placeholders into forbidden tokens.
    # Do not expand tokens that are the female lead's first name / alias.
    if not male_absent:
        for name in list(male.forbidden_aliases):
            if " " not in name:
                continue
            first = _first_token(name)
            if (
                first
                and first.lower() not in _SKIP_FIRST_TOKENS
                and first not in _PLAN_NAME_STOPWORDS
                and not _matches_declared_lead(
                    first, female_canonical, female.allowed_aliases
                )
                and not _matches_declared_lead(
                    first, male_canonical, male.allowed_aliases
                )
            ):
                male.register_forbidden(first)


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
    # Short forms (Elias) and full forms (Elias van Doren) agree when both
    # resolve to the declared male lead.
    source_values = {
        src: val for src, val in registry.source_male_lead_names.items() if str(val).strip()
    }
    distinct = {_resolve_source_male_key(v, male_canon) for v in source_values.values()}
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
        if male_canon.is_allowed(val) or _matches_declared_lead(
            val, male_canon.canonical, male_canon.allowed_aliases
        ):
            continue
        detail = None
        if src == "narrative/*.json":
            detail = (
                "narrative lead_internal_arc POV/male name differs from "
                "canon_registry male_lead — update canon_registry.yaml + "
                "bible/series.json leads.male (or add the name to supporting_cast "
                "if they are not the male lead)"
            )
        conflicts.append(
            {
                "code": "male_lead_source_mismatch",
                "source": src,
                "value": val,
                "expected": expected_male,
                **({"detail": detail} if detail else {}),
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
