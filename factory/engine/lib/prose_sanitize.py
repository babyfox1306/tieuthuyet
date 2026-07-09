"""Prose sanitize — detect and strip markdown artifacts from fiction output.

Factory policy: published prose is plain text + curly/straight quotes only.
Markdown (**bold**, *italic*, backticks, template markers) is a writer defect,
not a rendering feature. Detect at write; normalize at promote; verify at export.
"""

from __future__ import annotations

import re

# Patterns that must never appear in catalog body (after sanitize).
_ARTIFACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*[^*\n]+?\*\*"), "markdown_bold"),
    (re.compile(r"(?<!\*)\*[^*\n]+?\*(?!\*)"), "markdown_italic"),
    (re.compile(r"`[^`\n]+?`"), "markdown_code"),
    (re.compile(r"^#{2,}\s", re.MULTILINE), "markdown_heading"),
    (re.compile(r"\*\*Cliffhanger:\*\*", re.IGNORECASE), "cliffhanger_marker"),
]

# Whole-line italic like *click-click-click* (common writer tic)
_LINE_ITALIC = re.compile(r"^\*[^*\n]+\*$", re.MULTILINE)


def find_markdown_artifacts(text: str, *, max_samples: int = 8) -> list[str]:
    """Return sample substrings of markdown/template artifacts still in text."""
    samples: list[str] = []
    seen: set[str] = set()
    for pattern, _label in _ARTIFACT_PATTERNS:
        for m in pattern.finditer(text):
            snippet = m.group(0).strip()[:72]
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            samples.append(snippet)
            if len(samples) >= max_samples:
                return samples
    for m in _LINE_ITALIC.finditer(text):
        snippet = m.group(0).strip()[:72]
        key = snippet.lower()
        if key not in seen:
            seen.add(key)
            samples.append(snippet)
            if len(samples) >= max_samples:
                break
    return samples


def sanitize_prose(text: str) -> str:
    """Strip markdown emphasis markers; keep inner text. Idempotent on clean prose."""
    out = text
    for _ in range(12):
        prev = out
        out = re.sub(r"\*\*([^*]+?)\*\*", r"\1", out)
        out = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", out)
        out = re.sub(r"`([^`\n]+?)`", r"\1", out)
        if out == prev:
            break
    # Template markers that should be deleted entirely
    out = re.sub(r"\*\*Cliffhanger:\*\*\s*", "", out, flags=re.IGNORECASE)
    # Writer thread markers (T001, T002, …) — never publish
    out = re.sub(r"\bT\d{3}\b\.?\s*", "", out)
    # Trailing draft horizontal rule
    out = re.sub(r"\n---\s*$", "", out.rstrip())
    return out


def prose_is_clean(text: str) -> bool:
    return not find_markdown_artifacts(text)
