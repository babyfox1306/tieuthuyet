"""EG-21 — character identity lock (gender/pronouns + revealed role).

Reads ``character_identity`` from ``canon_registry.yaml`` and BLOCKs prose that:
- assigns wrong-gender pronouns near a named character, or
- assigns a forbidden role flip near a named character (e.g. Marsh as Special Agent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from factory.engine.paths import workspace_dir

# After a name hit, scan this many chars for wrong pronouns / role cues.
_PRONOUN_WINDOW = 140
_ROLE_WINDOW = 100

# Other cast names that reset the antecedent (stop attributing pronouns).
_SENTENCE_END = re.compile(r"[.!?…][\"”']?\s+")


@dataclass
class CharacterIdentity:
    canonical: str
    aliases: list[str] = field(default_factory=list)
    gender: str = ""
    pronouns: list[str] = field(default_factory=list)
    forbid_pronouns: list[str] = field(default_factory=list)
    pronoun_gate: bool = True
    role: str = ""
    forbid_role_patterns: list[re.Pattern[str]] = field(default_factory=list)

    def name_variants(self) -> list[str]:
        names = [self.canonical, *self.aliases]
        return sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)


@dataclass
class CharacterIdentityLock:
    characters: list[CharacterIdentity] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.characters


def _compile_patterns(raw: list[Any] | None) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for item in raw or []:
        s = str(item or "").strip()
        if not s:
            continue
        try:
            out.append(re.compile(s, re.IGNORECASE))
        except re.error:
            out.append(re.compile(re.escape(s), re.IGNORECASE))
    return out


def load_character_identity(ws: Path) -> CharacterIdentityLock:
    path = ws / "canon_registry.yaml"
    if not path.exists():
        return CharacterIdentityLock()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return CharacterIdentityLock()
    if not isinstance(data, dict):
        return CharacterIdentityLock()

    raw = data.get("character_identity") or []
    chars: list[CharacterIdentity] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            canonical = str(item.get("canonical") or "").strip()
            if not canonical:
                continue
            aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
            forbid_p = [str(p).strip().lower() for p in (item.get("forbid_pronouns") or []) if str(p).strip()]
            ok_p = [str(p).strip().lower() for p in (item.get("pronouns") or []) if str(p).strip()]
            pg = item.get("pronoun_gate")
            pronoun_gate = True if pg is None else bool(pg)
            chars.append(
                CharacterIdentity(
                    canonical=canonical,
                    aliases=aliases,
                    gender=str(item.get("gender") or "").strip().lower(),
                    pronouns=ok_p,
                    forbid_pronouns=forbid_p,
                    pronoun_gate=pronoun_gate,
                    role=str(item.get("role") or "").strip(),
                    forbid_role_patterns=_compile_patterns(item.get("forbid_role_patterns")),
                )
            )
    return CharacterIdentityLock(characters=chars)


def load_character_identity_for_workspace(workspace_id: str) -> CharacterIdentityLock:
    return load_character_identity(workspace_dir(workspace_id))


def _name_re(names: list[str]) -> re.Pattern[str] | None:
    if not names:
        return None
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(re.escape(n) for n in names), re.IGNORECASE)


def _all_other_name_re(lock: CharacterIdentityLock, exclude: CharacterIdentity) -> re.Pattern[str] | None:
    others: list[str] = []
    for c in lock.characters:
        if c.canonical == exclude.canonical:
            continue
        others.extend(c.name_variants())
    return _name_re(others)


def _window_after_name(text: str, start: int, end: int, max_len: int) -> str:
    """Take text after name until sentence end / max_len (exclusive of the name)."""
    chunk = text[end : end + max_len]
    # Cut at first hard sentence boundary
    m = _SENTENCE_END.search(chunk)
    if m:
        chunk = chunk[: m.end()]
    return chunk


def _pronoun_pattern(pronouns: list[str]) -> re.Pattern[str] | None:
    if not pronouns:
        return None
    # Word-boundary pronouns only (avoid matching inside words)
    parts = sorted({re.escape(p) for p in pronouns if p}, key=len, reverse=True)
    if not parts:
        return None
    return re.compile(r"\b(?:%s)\b" % "|".join(parts), re.IGNORECASE)


def find_pronoun_violations(
    text: str,
    lock: CharacterIdentityLock,
) -> list[dict[str, Any]]:
    """High-precision wrong-gender bindings only.

    Flags (examples):
    - ``Lund in his office`` / ``Lund at her desk`` (wrong gender)
    - ``Lund, who … his …``
    - ``Okafor had surrendered, his statement``
    Does NOT flag cross-reference (``Iris took his file``, ``Marsh …. Her voice``).
    """
    if not text or lock.empty:
        return []
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for char in lock.characters:
        if not char.pronoun_gate or not char.forbid_pronouns:
            continue
        names = char.name_variants()
        name_alt = "|".join(re.escape(n) for n in names)
        if not name_alt:
            continue
        forbid = {p.lower() for p in char.forbid_pronouns}
        # Location / custody possessives only — not with/to/for (other-person objects).
        loc_poss = [p for p in ("his", "her") if p in forbid]
        who_pron = sorted(
            {p for p in ("he", "she", "him", "her", "his", "hers", "himself", "herself") if p in forbid},
            key=len,
            reverse=True,
        )
        comma_poss = [p for p in ("his", "her") if p in forbid]

        patterns: list[tuple[re.Pattern[str], str]] = []
        if loc_poss:
            patterns.append(
                (
                    re.compile(
                        rf"(?<!\w)(?:{name_alt})(?!\w)(?!'s|’s)"
                        rf"\s+(?:in|at|inside|from)\s+"
                        rf"\b(?:{'|'.join(re.escape(p) for p in loc_poss)})\b",
                        re.IGNORECASE,
                    ),
                    "loc",
                )
            )
        if who_pron:
            patterns.append(
                (
                    re.compile(
                        rf"(?<!\w)(?:{name_alt})(?!\w)(?!'s|’s),\s+who\b"
                        rf"[^.!?]{{0,100}}\b(?:{'|'.join(re.escape(p) for p in who_pron)})\b",
                        re.IGNORECASE,
                    ),
                    "who",
                )
            )
        if comma_poss:
            # Self-referential custody/body nouns only — not "Halveston, her tone"
            self_nouns = (
                r"statement|office|hand|hands|digital|administrative|"
                r"signature|badge|keys|account|desk|file|files|"
                r"confession|admission|glove|gloves|phone|tablet"
            )
            patterns.append(
                (
                    re.compile(
                        rf"(?<!\w)(?:{name_alt})(?!\w)(?!'s|’s)"
                        rf"[^.!?]{{0,80}},\s+(?:{'|'.join(re.escape(p) for p in comma_poss)})\s+"
                        rf"(?:{self_nouns})\b",
                        re.IGNORECASE,
                    ),
                    "comma_poss",
                )
            )

        other_re = _all_other_name_re(lock, char)

        for pat, _kind in patterns:
            for m in pat.finditer(text):
                key = (char.canonical, m.start())
                if key in seen:
                    continue
                rest = m.group(0)
                rest2 = re.sub(
                    rf"^(?:{name_alt})\b", "", rest, count=1, flags=re.IGNORECASE
                )
                if other_re and other_re.search(rest2):
                    continue
                found = None
                for pm in re.finditer(
                    r"\b(he|she|him|her|his|hers|himself|herself)\b",
                    m.group(0),
                    re.IGNORECASE,
                ):
                    if pm.group(0).lower() in forbid:
                        found = pm.group(0)
                if not found:
                    continue
                seen.add(key)
                snippet = m.group(0).replace("\n", " ").strip()
                if len(snippet) > 180:
                    snippet = snippet[:180] + "…"
                hits.append(
                    {
                        "kind": "wrong_pronoun",
                        "canonical": char.canonical,
                        "gender": char.gender,
                        "match": found,
                        "name_hit": names[0],
                        "snippet": snippet,
                    }
                )
    return hits


def find_role_flip_violations(
    text: str,
    lock: CharacterIdentityLock,
) -> list[dict[str, Any]]:
    """Attribute a forbid-role match to the nearest preceding cast name only."""
    if not text or lock.empty:
        return []
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    # Collect all name spans for cast
    name_spans: list[tuple[int, int, CharacterIdentity, str]] = []
    for char in lock.characters:
        name_re = _name_re(char.name_variants())
        if not name_re:
            continue
        for nm in name_re.finditer(text):
            name_spans.append((nm.start(), nm.end(), char, nm.group(0)))

    for char in lock.characters:
        for pat in char.forbid_role_patterns:
            for rm in pat.finditer(text):
                # Nearest name ending at or before the role match, within window
                best: tuple[int, CharacterIdentity, str] | None = None
                for start, end, c, hit in name_spans:
                    if end > rm.start():
                        continue
                    dist = rm.start() - end
                    if dist > _ROLE_WINDOW:
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, c, hit)
                # Title-before-name: "Special Agent Marsh" — name starts soon after
                # match start (often overlapping the match itself).
                if best is None:
                    for start, end, c, hit in name_spans:
                        # Name begins inside or immediately after the role cue
                        if start < rm.start():
                            continue
                        if start > rm.end() + 24:
                            continue
                        dist = max(0, start - rm.start())
                        if best is None or dist < best[0]:
                            best = (dist, c, hit)
                if not best:
                    continue
                _dist, owner, name_hit = best
                if owner.canonical != char.canonical:
                    continue  # role cue belongs to someone else nearby
                key = (char.canonical, rm.start())
                if key in seen:
                    continue
                seen.add(key)
                left = max(0, rm.start() - _ROLE_WINDOW)
                right = min(len(text), rm.end() + 40)
                snippet = text[left:right].replace("\n", " ").strip()
                if len(snippet) > 180:
                    snippet = snippet[:180] + "…"
                hits.append(
                    {
                        "kind": "role_flip",
                        "canonical": char.canonical,
                        "role": char.role,
                        "match": rm.group(0),
                        "name_hit": name_hit,
                        "snippet": snippet,
                    }
                )
    return hits


def find_character_identity_violations(
    text: str,
    lock: CharacterIdentityLock,
) -> list[dict[str, Any]]:
    return find_pronoun_violations(text, lock) + find_role_flip_violations(text, lock)
