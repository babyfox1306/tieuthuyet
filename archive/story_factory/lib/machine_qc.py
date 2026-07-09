"""Layer 1 QC — regex/machine checks before 9router QC."""

from __future__ import annotations

import json
import re
from pathlib import Path

FACTORY_ROOT = Path(__file__).resolve().parent.parent


def word_count_vi(text: str) -> int:
    body = re.sub(r"^#.*$", "", text, flags=re.M).strip()
    return len(re.findall(r"\S+", body))


def find_cjk(text: str) -> list[str]:
    found = re.findall(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff]", text)
    return sorted(set(found))


def machine_qc(
    text: str,
    *,
    min_words: int = 1500,
    banned_phrases: list[str] | None = None,
    phrases_already_used: list[str] | None = None,
) -> dict:
    """Returns issues dict. Empty = pass."""
    issues: dict = {}
    cjk = find_cjk(text)
    if cjk:
        issues["cjk_chars"] = cjk
    wc = word_count_vi(text)
    issues["word_count"] = wc
    if wc < min_words:
        issues["short"] = wc
    used = phrases_already_used or []
    banned = banned_phrases or []
    repeats = []
    for phrase in banned:
        if phrase in text and phrase in used:
            repeats.append(phrase)
    if repeats:
        issues["repeat"] = repeats
    return issues


def machine_pass(issues: dict) -> bool:
    blockers = ["cjk_chars", "short", "repeat"]
    return not any(k in issues for k in blockers)


def save_machine_issues(path: Path, issues: dict) -> None:
    path.write_text(json.dumps(issues, indent=2, ensure_ascii=False), encoding="utf-8")
