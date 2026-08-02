"""Prose span segmentation — classify narration/dialogue/letter/message.

Does NOT strip dialogue from provenance scans. Spans exist so gates can
record span_type; every proper noun in every span still requires a source.
"""

from __future__ import annotations

import re
from typing import Any

# Double/single quoted dialogue runs (simple, non-nested).
_DIALOGUE_RE = re.compile(
    r'("([^"\\]|\\.)*")|(\'([^\'\\]|\\.)*\')',
    re.DOTALL,
)
# Letter / message blocks: salutation through sign-off, or fenced message markers.
_LETTER_RE = re.compile(
    r"(?is)(?:^|\n)(?:Dear\s+[^\n]+,|To\s+whom\s+it\s+may\s+concern,|"
    r"Subject:\s*[^\n]+|From:\s*[^\n]+\n(?:To:\s*[^\n]+\n)?)"
    r".{0,2000}?(?:\n(?:Yours|Sincerely|Best|Regards|—)[^\n]*\n|\n{2})",
)
_MESSAGE_RE = re.compile(
    r"(?is)(?:\[(?:SMS|TEXT|EMAIL|MESSAGE|CHAT)[^\]]*\]|"
    r"<msg>|<<message>>)"
    r".{0,800}?(?:\[/(?:SMS|TEXT|EMAIL|MESSAGE|CHAT)\]|</msg>|<<\/message>>)",
)

SPAN_TYPES = frozenset({"narration", "dialogue", "letter", "message"})


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def segment_prose(prose: str) -> list[dict[str, Any]]:
    """Return non-overlapping spans covering the full prose.

    Priority when ranges collide: message > letter > dialogue > narration.
    """
    text = prose or ""
    n = len(text)
    if n == 0:
        return []

    marked: list[tuple[int, int, str]] = []
    for m in _MESSAGE_RE.finditer(text):
        marked.append((m.start(), m.end(), "message"))
    for m in _LETTER_RE.finditer(text):
        marked.append((m.start(), m.end(), "letter"))
    for m in _DIALOGUE_RE.finditer(text):
        marked.append((m.start(), m.end(), "dialogue"))

    # Drop lower-priority overlaps.
    priority = {"message": 3, "letter": 2, "dialogue": 1}
    marked.sort(key=lambda t: (t[0], -(t[1] - t[0]), -priority[t[2]]))
    kept: list[tuple[int, int, str]] = []
    for start, end, kind in marked:
        if any(_overlaps(start, end, s, e) for s, e, _ in kept):
            continue
        kept.append((start, end, kind))
    kept.sort(key=lambda t: t[0])

    spans: list[dict[str, Any]] = []
    cursor = 0
    for start, end, kind in kept:
        if cursor < start:
            spans.append(
                {
                    "span_type": "narration",
                    "start": cursor,
                    "end": start,
                    "text": text[cursor:start],
                }
            )
        spans.append(
            {
                "span_type": kind,
                "start": start,
                "end": end,
                "text": text[start:end],
            }
        )
        cursor = end
    if cursor < n:
        spans.append(
            {
                "span_type": "narration",
                "start": cursor,
                "end": n,
                "text": text[cursor:n],
            }
        )
    return spans


def span_type_at(spans: list[dict[str, Any]], index: int) -> str:
    for span in spans:
        if int(span["start"]) <= index < int(span["end"]):
            return str(span["span_type"])
    return "narration"
