"""Prose sanitize — detect markdown leaks; optional operator fix; strip on promote.

Factory policy: *italic* / **bold** / `code` / # headings are writer leaks.
The advisor UI (``find_markdown_leaks`` + ``apply_markdown_leak_fix``) lets the
operator choose quotes vs strip per hit. ``sanitize_prose`` still strips
emphasis at promote/export so EG-06 cannot ship raw markdown.
"""

from __future__ import annotations

import re
from typing import Any, Literal

# Export-gate / detector patterns (samples for EG-06).
_ARTIFACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*[^*\n]+?\*\*"), "markdown_bold"),
    (re.compile(r"(?<!\*)\*[^*\n]+?\*(?!\*)"), "markdown_italic"),
    (re.compile(r"`[^`\n]+?`"), "markdown_code"),
    (re.compile(r"^#{2,}\s", re.MULTILINE), "markdown_heading"),
    (re.compile(r"\*\*Cliffhanger:\*\*", re.IGNORECASE), "cliffhanger_marker"),
]

_LINE_ITALIC = re.compile(r"^\*[^*\n]+\*$", re.MULTILINE)

# Ordered longest-first so ** wins over *
_LEAK_SPECS: list[tuple[str, re.Pattern[str]]] = [
    ("cliffhanger_marker", re.compile(r"\*\*Cliffhanger:\*\*", re.IGNORECASE)),
    ("bold", re.compile(r"\*\*([^*\n]+?)\*\*")),
    ("italic", re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")),
    ("code", re.compile(r"`([^`\n]+?)`")),
    ("heading", re.compile(r"^(#{2,6})\s+(.+)$", re.MULTILINE)),
]

_PIPELINE_TITLE = re.compile(
    r"^#\s*(?:Chapter|Chương)\s+\d+\s*[^\n]*\n*",
    re.IGNORECASE,
)

FixMode = Literal["quotes", "strip"]
CONTEXT_RADIUS = 60


def body_scan_start(text: str) -> int:
    """Skip pipeline ``# Chapter N: Title`` so it is not treated as a prose leak."""
    m = _PIPELINE_TITLE.match(text or "")
    return m.end() if m else 0


def find_markdown_artifacts(text: str, *, max_samples: int = 8) -> list[str]:
    """Return sample substrings of markdown/template artifacts still in text."""
    samples: list[str] = []
    seen: set[str] = set()
    for pattern, _label in _ARTIFACT_PATTERNS:
        for m in pattern.finditer(text or ""):
            snippet = m.group(0).strip()[:72]
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            samples.append(snippet)
            if len(samples) >= max_samples:
                return samples
    for m in _LINE_ITALIC.finditer(text or ""):
        snippet = m.group(0).strip()[:72]
        key = snippet.lower()
        if key not in seen:
            seen.add(key)
            samples.append(snippet)
            if len(samples) >= max_samples:
                break
    return samples


def find_markdown_leaks(text: str, *, max_hits: int = 40) -> list[dict[str, Any]]:
    """All markdown leaks in prose with span + ~60ch context. Advisor + QC.

    Returns dicts with ``id``, ``kind``, ``match``, ``inner``, ``context``,
    ``context_prefix``, ``context_suffix``, ``start``, ``end``, and previews.
    Leading pipeline chapter title is excluded.
    """
    text = text or ""
    start0 = body_scan_start(text)
    body = text[start0:]
    hits: list[tuple[int, int, str, str, str]] = []

    for kind, pattern in _LEAK_SPECS:
        for m in pattern.finditer(body):
            if kind == "heading":
                line = m.group(0)
                if re.match(r"^#\s*(?:Chapter|Chương)\s+\d+", line, re.IGNORECASE):
                    continue
                inner = m.group(2)
            elif kind == "cliffhanger_marker":
                inner = ""
            else:
                inner = m.group(1)
            abs_start = start0 + m.start()
            abs_end = start0 + m.end()
            hits.append((abs_start, abs_end, kind, m.group(0), inner))

    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    cleaned: list[tuple[int, int, str, str, str]] = []
    last_end = -1
    for h in hits:
        if h[0] < last_end:
            continue
        cleaned.append(h)
        last_end = h[1]

    out: list[dict[str, Any]] = []
    for i, (a, b, kind, match, inner) in enumerate(cleaned):
        left = max(0, a - CONTEXT_RADIUS)
        right = min(len(text), b + CONTEXT_RADIUS)
        context = re.sub(r"\s+", " ", text[left:right]).strip()
        out.append(
            {
                "id": i,
                "start": a,
                "end": b,
                "kind": kind,
                "match": match[:160],
                "inner": inner,
                "context": context[:160],
                "context_prefix": text[left:a],
                "context_suffix": text[b:right],
                "preview_quotes": _render_fix(match, inner, kind, "quotes"),
                "preview_strip": _render_fix(match, inner, kind, "strip"),
            }
        )
        if len(out) >= max_hits:
            break
    return out


def _render_fix(match: str, inner: str, kind: str, mode: FixMode) -> str:
    if kind == "cliffhanger_marker":
        return ""
    core = inner.strip()
    if mode == "quotes":
        return f'"{core}"'
    return core


def apply_markdown_leak_fix(
    text: str,
    *,
    mode: FixMode,
    hit_ids: list[int] | None = None,
    apply_all: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    """Apply quotes or strip to selected leak ids (or all).

    Returns ``(new_text, changelog)``. Never invents a mode — caller must pass
    ``quotes|strip`` after the operator chooses.
    """
    if mode not in ("quotes", "strip"):
        raise ValueError(f"invalid mode: {mode!r} (use quotes|strip)")
    text = text or ""
    leaks = find_markdown_leaks(text, max_hits=200)
    if not leaks:
        return text, []
    if apply_all or hit_ids is None:
        chosen = leaks
    else:
        id_set = {int(i) for i in hit_ids}
        chosen = [h for h in leaks if h["id"] in id_set]
    if not chosen:
        return text, []

    chosen_sorted = sorted(chosen, key=lambda h: h["start"], reverse=True)
    out = text
    changelog: list[dict[str, Any]] = []
    for h in chosen_sorted:
        replacement = _render_fix(h["match"], h["inner"], h["kind"], mode)
        out = out[: h["start"]] + replacement + out[h["end"] :]
        changelog.append(
            {
                "id": h["id"],
                "kind": h["kind"],
                "mode": mode,
                "before": h["match"],
                "after": replacement,
                "start": h["start"],
                "end": h["end"],
            }
        )
    changelog.reverse()
    return out, changelog


def sanitize_prose(text: str) -> str:
    """Strip markdown emphasis markers; keep inner text. Idempotent on clean prose."""
    out = text or ""
    for _ in range(12):
        prev = out
        out = re.sub(r"\*\*([^*]+?)\*\*", r"\1", out)
        out = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", out)
        out = re.sub(r"`([^`\n]+?)`", r"\1", out)
        if out == prev:
            break
    out = re.sub(r"\*\*Cliffhanger:\*\*\s*", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bT\d{3}\b\.?\s*", "", out)
    out = re.sub(r"\n---\s*$", "", out.rstrip())
    return out


def prose_is_clean(text: str) -> bool:
    return not find_markdown_artifacts(text)
