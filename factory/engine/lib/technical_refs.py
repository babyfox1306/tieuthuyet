"""Project engine chapter references into writer-facing story time.

Chapter numbers belong to planning metadata.  Writer-facing narrative fields must
use the story's own clock so models do not make characters say "in Chapter 12".
The projection is deliberately scoped to known chapter plans; it never performs a
global replacement over arbitrary prose.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_ONES = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}
_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}
_DAY_ANCHOR_RE = re.compile(
    r"\bday\s+("
    r"\d{1,3}|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"thirty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"forty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"fifty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"sixty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"seventy(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"eighty(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"ninety(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"
    r")\b",
    re.IGNORECASE,
)


def _number_words(value: int) -> str:
    if value in _ONES:
        return _ONES[value]
    if value in _TENS:
        return _TENS[value]
    if 20 < value < 100:
        tens = value // 10 * 10
        return f"{_TENS[tens]}-{_ONES[value % 10]}"
    return str(value)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return ""


def derive_chapter_day_map(plans: Iterable[dict[str, Any]]) -> dict[int, str]:
    """Return ``chapter -> day label`` from structured plan time anchors."""
    out: dict[int, str] = {}
    for plan in plans:
        try:
            chapter = int(plan.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if chapter <= 0:
            continue
        # The opening is the strongest clock source; summaries are fallbacks.
        for field in ("opens_with", "beat_summary", "one_line_summary", "chapter_task"):
            match = _DAY_ANCHOR_RE.search(_text(plan.get(field)))
            if match:
                out[chapter] = match.group(1).lower().replace("-", " ")
                break
    return out


def project_technical_chapter_refs(
    text: str,
    chapter_days: dict[int, str],
    *,
    current_chapter: int | None = None,
) -> str:
    """Translate known metadata references in a writer-facing field.

    Only references whose chapter has a structured day anchor are translated.
    The current chapter is left alone because prompt headings/tasks legitimately
    identify the chapter being written.
    """
    out = str(text or "")
    for chapter, day in sorted(chapter_days.items(), reverse=True):
        if current_chapter is not None and chapter == int(current_chapter):
            continue
        word = _number_words(chapter)
        patterns = (
            rf"\bChapter\s+{chapter}\b",
            rf"\bChapter\s+{re.escape(word)}\b",
            rf"\bCh\s*{chapter}\b",
        )
        for pattern in patterns:
            out = re.sub(pattern, f"day {day}", out, flags=re.IGNORECASE)
    return out


_TECHNICAL_PROSE_PATTERNS = (
    re.compile(
        r"\b(?:until|since|from|during|before|after|by|in|on)\s+"
        r"Chapter\s+(?:\d{1,3}|[A-Z][a-z]+(?:[- ][A-Z][a-z]+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bChapter\s+(?:\d{1,3}|[A-Z][a-z]+(?:[- ][A-Z][a-z]+)?)\s+"
        r"(?:instruction|message|entry|record|recording|footage|event|reveal|"
        r"conversation|meeting|audit|evidence)\b",
        re.IGNORECASE,
    ),
)


def find_technical_chapter_reference(text: str) -> str | None:
    """Return a conservative technical-reference leak from prose, if present."""
    for pattern in _TECHNICAL_PROSE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None
