"""Supporting-name lock — extract after PASS, reinject into writer, sanitize state.

Same reinjection pattern that keeps Marcus/Lydia stable via plan text, applied to
supporting roles (previous housekeeper, narrator alias, unresolved initials).
Does NOT touch canon_registry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

UNKNOWN_UNTIL_REVEAL = "unknown_until_reveal"

_NAME_TAG_RE = re.compile(
    r"name\s+tag[^\n]{0,100}?[\'\"\u201c\u201d]([A-Z][a-z]{1,20})\.?[\'\"\u201c\u201d]",
    re.IGNORECASE,
)
_PREV_HK_NAMED_RE = re.compile(
    r"previous\s+housekeeper\s+(?:was\s+)?named\s+[\'\"\u201c\u201d]?([A-Z][a-z]{1,20})"
    r"[\'\"\u201c\u201d]?",
    re.IGNORECASE,
)
_HOUSEKEEPER_NAMED_RE = re.compile(
    r"housekeeper\s+named\s+[\'\"\u201c\u201d]?([A-Z][a-z]{1,20})[\'\"\u201c\u201d]?",
    re.IGNORECASE,
)
# "Clara." The previous housekeeper. / Clara, the previous housekeeper
_NAME_THEN_PREV_HK_RE = re.compile(
    r"[\'\"\u201c\u201d]([A-Z][a-z]{1,20})\.?[\'\"\u201c\u201d]\s*[.,]?\s*"
    r"(?:The\s+)?previous\s+housekeeper",
    re.IGNORECASE,
)
_PREV_HK_COMMA_NAME_RE = re.compile(
    r"previous\s+housekeeper[^\n]{0,40}?\bnamed\s+([A-Z][a-z]{1,20})\b",
    re.IGNORECASE,
)
_WRITTEN_ONLY_RE = re.compile(
    r"written\s+only\s+[\'\"\u2018\u201c]([A-Z][a-z]{1,20})\.?[\'\"\u2019\u201d]",
    re.IGNORECASE,
)
_MY_NAME_WAS_RE = re.compile(
    r"\b(?:my\s+name\s+was|called\s+myself|said\s+my\s+name\s+was)\s+[\'\"\u2018\u201c]?"
    r"([A-Z][a-z]{1,20})[\'\"\u2019\u201d]?",
    re.IGNORECASE,
)
# Husband / male target — allowed even when canon male_lead is Unassigned (no romance).
_HUSBAND_NAMED_RE = re.compile(
    r"\bhusband(?:'s)?(?:\s+name)?\s+(?:was|is|named)\s+[\'\"\u2018\u201c]?"
    r"([A-Z][a-z]{1,20})[\'\"\u2019\u201d]?",
    re.IGNORECASE,
)
_HUSBAND_WAS_RE = re.compile(
    r"\b(?:the\s+)?husband(?:'s)?\s+was\s+([A-Z][a-z]{1,20})\b",
    re.IGNORECASE,
)
_INITIALS_RE = re.compile(r"(?<![A-Za-z])([A-Z]\.[A-Z]\.)(?![A-Za-z])")
_INITIALS_CONTEXT_RE = re.compile(
    r"(?:initials?|watch|engraved|monogram).{0,80}?(?<![A-Za-z])([A-Z]\.[A-Z]\.)(?![A-Za-z])"
    r"|(?<![A-Za-z])([A-Z]\.[A-Z]\.)(?![A-Za-z]).{0,80}?(?:initials?|watch|engraved|monogram)",
    re.IGNORECASE | re.DOTALL,
)
_FULL_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20})\b")

_STOP_NAMES = frozenset(
    {
        "Katherine",
        "Thornton",
        "Detective",
        "Harris",
        "Subject",
        "Vance",
        "The",
        "Not",
    }
)
# Names that must not be locked into previous_housekeeper / narrator_alias by accident,
# but ARE valid for husband/wife roles.
_LEADISH_STOP_FOR_SUPPORT = frozenset({"Marcus", "Lydia", "Harold", "Emily", "Clara", "Anna"})


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def extract_name_locks_from_prose(text: str) -> dict[str, str]:
    """Deterministic proper-noun → role locks from chapter prose."""
    found: dict[str, str] = {}
    if not text or not str(text).strip():
        return found

    def _set(role: str, name: str) -> None:
        name = _clean_name(name)
        if not name or name in _STOP_NAMES:
            return
        if role in {"previous_housekeeper", "narrator_alias"} and name in {
            "Marcus",
            "Lydia",
            "Harold",
        }:
            return
        if role not in found:
            found[role] = name

    for m in _NAME_TAG_RE.finditer(text):
        _set("previous_housekeeper", m.group(1))
    for m in _NAME_THEN_PREV_HK_RE.finditer(text):
        _set("previous_housekeeper", m.group(1))
    for m in _PREV_HK_NAMED_RE.finditer(text):
        _set("previous_housekeeper", m.group(1))
    for m in _PREV_HK_COMMA_NAME_RE.finditer(text):
        _set("previous_housekeeper", m.group(1))
    for m in _HOUSEKEEPER_NAMED_RE.finditer(text):
        _set("previous_housekeeper", m.group(1))

    for m in _WRITTEN_ONLY_RE.finditer(text):
        _set("narrator_alias", m.group(1))
    for m in _MY_NAME_WAS_RE.finditer(text):
        _set("narrator_alias", m.group(1))

    for m in _HUSBAND_NAMED_RE.finditer(text):
        _set("husband", m.group(1))
    for m in _HUSBAND_WAS_RE.finditer(text):
        _set("husband", m.group(1))

    for m in _INITIALS_CONTEXT_RE.finditer(text):
        initials = m.group(1) or m.group(2)
        if initials:
            _set(initials, UNKNOWN_UNTIL_REVEAL)
    if re.search(r"Who\s+was\s+[A-Z]\.[A-Z]\.", text, re.IGNORECASE):
        for m in _INITIALS_RE.finditer(text):
            _set(m.group(1), UNKNOWN_UNTIL_REVEAL)

    return found


def extract_husband_from_plan_blob(blob: str) -> str | None:
    """Pull husband proper name from master_plan / concept text (plan SoT)."""
    if not blob:
        return None
    not_names = frozenset(
        {
            "dangerous",
            "controlling",
            "wealthy",
            "absent",
            "away",
            "gone",
            "dead",
            "home",
            "here",
            "there",
            "back",
            "early",
            "late",
            "still",
            "already",
            "always",
            "never",
            "often",
            "truly",
            "really",
            "clearly",
            "the",
            "his",
            "her",
            "this",
            "that",
            "said",
            "from",
            "with",
            "into",
            "about",
            "fragile",
            "unwell",
            "violent",
            "guilty",
            "innocent",
        }
    )
    patterns = (
        # "The husband's was Marcus" / "husband's name was Marcus"
        r"husband(?:'s)?(?:\s+name)?\s+was\s+([A-Z][a-z]{1,20})\b",
        r"husband(?:'s)?\s+named\s+([A-Z][a-z]{1,20})\b",
        r"husband(?:'s)?\s+is\s+([A-Z][a-z]{1,20})\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, blob, re.IGNORECASE):
            name = _clean_name(m.group(1))
            if not name or name in _STOP_NAMES:
                continue
            if name.lower() in not_names:
                continue
            # Prefer Title Case person tokens (plan JSON preserves Marcus)
            if name[0].isupper():
                return name
    return None


def seed_locked_names_from_plan(ws: Path, book: int = 1) -> dict[str, str]:
    """Seed supporting locks from master_plan (husband etc.) before write."""
    from factory.engine.paths import book_workspace_dir

    path = book_workspace_dir(ws, book) / "master_plan.json"
    seeded: dict[str, str] = {}
    if not path.exists():
        return seeded
    try:
        blob = path.read_text(encoding="utf-8")
    except OSError:
        return seeded
    husband = extract_husband_from_plan_blob(blob)
    if husband:
        seeded["husband"] = husband
    if re.search(r"written only ['\u2018\u201c]Anna", blob, re.I):
        seeded.setdefault("narrator_alias", "Anna")
    if re.search(r"\bClara\b", blob) and re.search(r"housekeeper|name tag", blob, re.I):
        seeded.setdefault("previous_housekeeper", "Clara")
    if re.search(r"(?<![A-Za-z])E\.M\.(?![A-Za-z])", blob):
        seeded.setdefault("E.M.", UNKNOWN_UNTIL_REVEAL)
    return seeded


def merge_locked_names(
    existing: dict[str, Any] | None,
    extracted: dict[str, str] | None,
) -> dict[str, str]:
    """First lock wins. Never replace a locked name with a later variant."""
    out: dict[str, str] = {}
    for src in (existing or {}, extracted or {}):
        if not isinstance(src, dict):
            continue
        for role, name in src.items():
            role_s = str(role).strip()
            name_s = _clean_name(str(name))
            if not role_s or not name_s:
                continue
            if role_s not in out:
                out[role_s] = name_s
    return out


def format_locked_names_block(
    locked_names: dict[str, str] | None,
    *,
    lang: str = "en",
) -> str:
    """Writer reinjection block — do not rename / invent variants."""
    if not locked_names:
        return ""
    items = sorted((str(k), str(v)) for k, v in locked_names.items() if k and v)
    if not items:
        return ""
    if lang == "vi":
        lines = [
            "## LOCKED NAMES (cấm đổi tên, cấm bịa biến thể)",
            "Dùng ĐÚNG các tên sau cho vai phụ / alias. Không invent tên mới cho cùng vai.",
        ]
    else:
        lines = [
            "## LOCKED NAMES (do not rename, do not invent variants)",
            "Use these supporting names / aliases EXACTLY. "
            "Do not invent a second name for the same role.",
        ]
    for role, name in items:
        if name == UNKNOWN_UNTIL_REVEAL:
            lines.append(
                f"- {role}: {UNKNOWN_UNTIL_REVEAL} "
                "(initials/clue only — do NOT invent a full name)"
            )
        else:
            lines.append(f"- {role}: {name}")
    return "\n".join(lines)


def _name_matches_unknown_initials(candidate: str, locked: dict[str, str]) -> bool:
    parts = candidate.split()
    if len(parts) != 2:
        return False
    if not parts[0] or not parts[1]:
        return False
    initials = f"{parts[0][0]}.{parts[1][0]}."
    return locked.get(initials) == UNKNOWN_UNTIL_REVEAL


def _conflicting_housekeeper_name(text: str, locked_prev: str) -> str | None:
    """If text names a housekeeper other than locked_prev, return that name."""
    if "housekeeper" not in text.lower() and "carer" not in text.lower():
        return None
    # "named Emily" / "housekeeper named X"
    m = re.search(
        r"(?:housekeeper|carer)\s+named\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        text,
        re.IGNORECASE,
    )
    if m:
        cand = _clean_name(m.group(1))
        if cand != locked_prev and not cand.startswith(locked_prev):
            return cand
    # "Emily Morrison, a former housekeeper" / "watch belonged to Emily Morrison, a housekeeper"
    m = re.search(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b(?:,)?\s+a\s+(?:former\s+)?"
        r"(?:housekeeper|carer)",
        text,
        re.IGNORECASE,
    )
    if m:
        cand = _clean_name(m.group(1))
        if cand != locked_prev and locked_prev not in cand:
            return cand
    # "previous housekeeper was named Clara" ok; "Emily" alone with housekeeper + not Clara
    for m in _FULL_NAME_RE.finditer(text):
        full = m.group(1)
        if locked_prev in full:
            continue
        if re.search(rf"\b{re.escape(full)}\b.*\b(?:housekeeper|carer)\b", text, re.I) or re.search(
            rf"\b(?:housekeeper|carer)\b.*\b{re.escape(full)}\b", text, re.I
        ):
            return full
    # Bare first name that isn't locked, in housekeeper sentence (Emily vs Clara)
    for m in re.finditer(r"\b([A-Z][a-z]{2,20})\b", text):
        first = m.group(1)
        if first in _STOP_NAMES or first == locked_prev:
            continue
        if first in {"Emily"} and locked_prev == "Clara":
            return first
    return None


def _should_drop_fact(text: str, locked: dict[str, str]) -> bool:
    locked_prev = locked.get("previous_housekeeper")
    locked_alias = locked.get("narrator_alias")
    locked_husband = locked.get("husband")

    for m in _FULL_NAME_RE.finditer(text):
        if _name_matches_unknown_initials(m.group(1), locked):
            return True

    # Any "Emily Morrison" while E.M. is unknown_until_reveal
    if locked.get("E.M.") == UNKNOWN_UNTIL_REVEAL and re.search(
        r"\bEmily\s+Morrison\b", text
    ):
        return True

    if locked_prev and _conflicting_housekeeper_name(text, locked_prev):
        return True

    if locked_husband:
        # Alternate husband first name (Harold when Marcus locked)
        if re.search(r"\bHarold(?:\s+Vance)?\b", text) and locked_husband == "Marcus":
            return True
        for m in re.finditer(r"\b([A-Z][a-z]{2,20})\b", text):
            first = m.group(1)
            if first == locked_husband or first in _STOP_NAMES | {"Lydia", "Clara", "Anna"}:
                continue
            if re.search(
                rf"\bhusband\b.*\b{re.escape(first)}\b|\b{re.escape(first)}\b.*\bhusband\b",
                text,
                re.I,
            ):
                if first != locked_husband:
                    return True

    if locked_alias:
        for m in _FULL_NAME_RE.finditer(text):
            full = m.group(1)
            if full == locked_alias:
                continue
            if re.search(r"\balias\b|\bfake\s+name\b|\breal\s+name\b", text, re.I):
                if full.split()[0] != locked_alias.split()[0]:
                    return True
        if re.search(r"\bSarah\s+Mills\b", text) and locked_alias.startswith("Anna"):
            return True
    return False


def _scrub_text(text: str, locked: dict[str, str]) -> str | None:
    if _should_drop_fact(text, locked):
        return None
    out = text
    # Soft: strip parenthetical invent "E.M. (Emily Morrison)"
    for m in list(_FULL_NAME_RE.finditer(out)):
        if _name_matches_unknown_initials(m.group(1), locked):
            out = out.replace(f"({m.group(1)})", "").replace(m.group(1), "unknown")
            out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def _scrub_string_list(items: list[Any], locked: dict[str, str]) -> list[Any]:
    kept: list[Any] = []
    for item in items:
        if not isinstance(item, str):
            kept.append(item)
            continue
        cleaned = _scrub_text(item, locked)
        if cleaned is not None:
            kept.append(cleaned)
    return kept


def sanitize_state_for_locked_names(state: dict) -> dict:
    """Enforce one name per role; block inventing full names for unknown initials."""
    locked = merge_locked_names(state.get("locked_names"), None)
    state = dict(state)
    state["locked_names"] = locked
    if not locked:
        return state

    if isinstance(state.get("facts_established"), list):
        state["facts_established"] = _scrub_string_list(state["facts_established"], locked)
    if isinstance(state.get("timeline"), list):
        state["timeline"] = _scrub_string_list(state["timeline"], locked)
    if isinstance(state.get("open_threads"), list):
        state["open_threads"] = _scrub_string_list(state["open_threads"], locked)

    status = state.get("character_status")
    if isinstance(status, dict):
        new_status: dict[str, Any] = {}
        for key, val in status.items():
            if not isinstance(val, dict):
                new_status[key] = val
                continue
            entry = dict(val)
            if isinstance(entry.get("knows"), list):
                entry["knows"] = _scrub_string_list(entry["knows"], locked)
            rel = entry.get("relationship_other")
            if isinstance(rel, str):
                scrubbed = _scrub_text(rel, locked)
                entry["relationship_other"] = "" if scrubbed is None else scrubbed
            new_status[key] = entry
        state["character_status"] = new_status

    phrases = state.get("phrases_used")
    if isinstance(phrases, list):
        locked_prev = locked.get("previous_housekeeper")
        locked_alias = locked.get("narrator_alias")
        locked_husband = locked.get("husband")
        kept_p: list[Any] = []
        for p in phrases:
            if not isinstance(p, str):
                kept_p.append(p)
                continue
            if any(_name_matches_unknown_initials(m.group(1), locked) for m in _FULL_NAME_RE.finditer(p)):
                continue
            if locked_prev == "Clara" and p.strip() == "Emily":
                continue
            if locked_alias and locked_alias.startswith("Anna") and "Sarah" in p:
                continue
            if locked_husband == "Marcus" and re.search(r"\bHarold\b", p):
                continue
            kept_p.append(p)
        state["phrases_used"] = kept_p

    # Rename character_status keys that used the drifted husband name
    locked_husband = locked.get("husband")
    if locked_husband and isinstance(state.get("character_status"), dict):
        status = state["character_status"]
        renamed: dict[str, Any] = {}
        for key, val in status.items():
            new_key = key
            if locked_husband == "Marcus" and re.search(r"\bHarold\b", str(key)):
                new_key = re.sub(r"\bHarold(?:\s+Vance)?\b", "Marcus", str(key))
            renamed[new_key] = val
        state["character_status"] = renamed

    return state


def apply_locked_names_after_pass(state: dict, chapter_text: str) -> dict:
    """Merge locks from prose into state, then sanitize conflicting facts."""
    extracted = extract_name_locks_from_prose(chapter_text)
    merged = merge_locked_names(state.get("locked_names"), extracted)
    state = dict(state)
    state["locked_names"] = merged
    return sanitize_state_for_locked_names(state)


def state_mentions_emily_as_housekeeper(state: dict) -> bool:
    """True when a single fact/knows/timeline string ties Emily(+Morrison) to housekeeper."""
    chunks: list[str] = []
    for key in ("facts_established", "timeline", "open_threads", "phrases_used"):
        val = state.get(key)
        if isinstance(val, list):
            chunks.extend(str(x) for x in val)
    status = state.get("character_status")
    if isinstance(status, dict):
        for entry in status.values():
            if not isinstance(entry, dict):
                continue
            knows = entry.get("knows")
            if isinstance(knows, list):
                chunks.extend(str(x) for x in knows)
            rel = entry.get("relationship_other")
            if isinstance(rel, str):
                chunks.append(rel)
    for chunk in chunks:
        if re.search(r"\bEmily(?:\s+Morrison)?\b", chunk) and re.search(
            r"housekeeper|carer", chunk, re.I
        ):
            return True
    return False


def json_blob(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False)
