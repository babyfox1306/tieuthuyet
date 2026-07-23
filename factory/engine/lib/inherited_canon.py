"""Inherited canon — prior-book ontology lock for sequential workspaces.

Book N workspace declares ``prior_workspace`` + ``inherited_canon`` in
``canon_registry.yaml``. Facts are immutable; ``forbid_patterns`` are regexes
that BLOCK prose contradicting Book N-1 ontology (e.g. Kessler bridge vs tunnel).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from factory.engine.paths import workspace_dir


@dataclass
class InheritedFact:
    id: str
    fact: str
    forbid_patterns: list[re.Pattern[str]] = field(default_factory=list)


@dataclass
class InheritedCanonLock:
    prior_workspace: str | None
    facts: list[InheritedFact]

    @property
    def empty(self) -> bool:
        return not self.facts and not self.prior_workspace


def _compile_patterns(raw: list[Any] | None) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for item in raw or []:
        s = str(item or "").strip()
        if not s:
            continue
        try:
            out.append(re.compile(s, re.IGNORECASE))
        except re.error:
            # Treat as literal if invalid regex
            out.append(re.compile(re.escape(s), re.IGNORECASE))
    return out


def load_inherited_canon(ws: Path) -> InheritedCanonLock:
    """Load inherited_canon from this workspace's canon_registry.yaml."""
    path = ws / "canon_registry.yaml"
    if not path.exists():
        return InheritedCanonLock(prior_workspace=None, facts=[])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return InheritedCanonLock(prior_workspace=None, facts=[])
    if not isinstance(data, dict):
        return InheritedCanonLock(prior_workspace=None, facts=[])

    prior = str(data.get("prior_workspace") or "").strip() or None
    # Also accept prior_workspace on direction/manifest via caller merge
    raw_facts = data.get("inherited_canon") or []
    facts: list[InheritedFact] = []
    if isinstance(raw_facts, list):
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            fid = str(item.get("id") or "").strip()
            fact = str(item.get("fact") or "").strip()
            if not fid and not fact:
                continue
            facts.append(
                InheritedFact(
                    id=fid or "unnamed",
                    fact=fact,
                    forbid_patterns=_compile_patterns(item.get("forbid_patterns")),
                )
            )
    return InheritedCanonLock(prior_workspace=prior, facts=facts)


def resolve_prior_workspace_id(ws: Path) -> str | None:
    """prior_workspace from canon_registry, else direction/manifest."""
    lock = load_inherited_canon(ws)
    if lock.prior_workspace:
        return lock.prior_workspace
    for name in ("direction.yaml", "manifest.yaml"):
        path = ws / name
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            p = str(data.get("prior_workspace") or "").strip()
            if p:
                return p
    return None


def load_inherited_canon_for_workspace(workspace_id: str) -> InheritedCanonLock:
    ws = workspace_dir(workspace_id)
    lock = load_inherited_canon(ws)
    if not lock.prior_workspace:
        prior = resolve_prior_workspace_id(ws)
        if prior:
            lock = InheritedCanonLock(prior_workspace=prior, facts=lock.facts)
    return lock


# Built-in ontology contradictions when prior is the-kessler-line / Kessler Book 1
# Applied in addition to workspace-declared forbid_patterns.
_DEFAULT_KESSLER_PATTERNS: list[tuple[str, str]] = [
    ("kessler_structure", r"\bkessler\s+bridge\b"),
    ("kessler_evidence", r"\bkessler\s+coupon(?:\s+micrograph)?\b"),
]


def effective_forbid_patterns(lock: InheritedCanonLock) -> list[tuple[str, re.Pattern[str]]]:
    """(fact_id, pattern) pairs to scan against prose."""
    out: list[tuple[str, re.Pattern[str]]] = []
    seen: set[str] = set()
    for fact in lock.facts:
        for pat in fact.forbid_patterns:
            key = pat.pattern.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((fact.id, pat))
    # Default Kessler ontology when prior_workspace points at Kessler
    prior = (lock.prior_workspace or "").lower()
    if "kessler" in prior:
        for fid, raw in _DEFAULT_KESSLER_PATTERNS:
            key = raw.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((fid, re.compile(raw, re.IGNORECASE)))
    return out


def find_inherited_canon_violations(text: str, lock: InheritedCanonLock) -> list[dict[str, Any]]:
    """Return hits: {id, pattern, snippet} for ontology contradictions."""
    if not text or lock.empty:
        # Still apply defaults if prior is set even with empty facts
        if not lock.prior_workspace and not lock.facts:
            return []
    hits: list[dict[str, Any]] = []
    for fid, pat in effective_forbid_patterns(lock):
        m = pat.search(text or "")
        if not m:
            continue
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        hits.append(
            {
                "id": fid,
                "pattern": pat.pattern,
                "match": m.group(0),
                "snippet": text[start:end].replace("\n", " ").strip(),
            }
        )
    return hits


def format_inherited_canon_for_prompt(lock: InheritedCanonLock, *, lang: str = "en") -> str:
    if lock.empty and not lock.prior_workspace:
        return ""
    if lang == "vi":
        lines = ["## Canon kế thừa (BẤT BIẾN — từ sách trước)"]
        if lock.prior_workspace:
            lines.append(f"Nguồn: workspace `{lock.prior_workspace}`")
        for f in lock.facts:
            lines.append(f"- [{f.id}] {f.fact}")
        lines.append("CẤM mâu thuẫn các fact trên trong prose.")
        return "\n".join(lines)
    lines = ["## Inherited canon (IMMUTABLE — prior book)"]
    if lock.prior_workspace:
        lines.append(f"Source workspace: `{lock.prior_workspace}`")
    for f in lock.facts:
        lines.append(f"- [{f.id}] {f.fact}")
    lines.append("Do NOT contradict these facts in prose.")
    return "\n".join(lines)
