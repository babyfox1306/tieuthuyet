"""Layer 1 QC — regex/machine checks before 9router QC."""

from __future__ import annotations

import json
import re

from factory.engine.lib.language import find_foreign_chars, target_language
from factory.engine.lib.prose_sanitize import find_markdown_artifacts


def word_count_vi(text: str) -> int:
    """Đếm từ/chữ — dùng cho mọi target_language."""
    body = re.sub(r"^#.*$", "", text, flags=re.M).strip()
    return len(re.findall(r"\S+", body))


def find_cjk(text: str) -> list[str]:
    """Deprecated — dùng find_foreign_chars. Giữ cho script cũ."""
    found = re.findall(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff]", text)
    return sorted(set(found))


def machine_qc(
    text: str,
    *,
    min_words: int = 1500,
    banned_phrases: list[str] | None = None,
    phrases_already_used: list[str] | None = None,
    target_lang: str | None = None,
    direction: dict | None = None,
    cfg: dict | None = None,
) -> dict:
    issues: dict = {}
    lang = target_lang or target_language(direction, cfg)
    foreign = find_foreign_chars(text, lang)
    if foreign:
        issues["foreign_chars"] = foreign
        # alias cho log cũ
        if lang == "vi":
            issues["cjk_chars"] = foreign
    wc = word_count_vi(text)
    issues["word_count"] = wc
    issues["target_language"] = lang
    if wc < min_words:
        issues["short"] = wc
    used = phrases_already_used or []
    banned = banned_phrases or []
    repeats = [p for p in banned if p in text and p in used]
    if repeats:
        issues["repeat"] = repeats
    markdown = find_markdown_artifacts(text)
    if markdown:
        issues["markdown"] = markdown
    return issues


def machine_pass(issues: dict) -> bool:
    if any(
        k in issues
        for k in ("foreign_chars", "cjk_chars", "short", "repeat", "markdown")
    ):
        return False
    return True


def issues_to_needs_fix(issues: dict, extra: list[str] | None = None) -> list[str]:
    flags: list[str] = []
    chars = issues.get("foreign_chars") or issues.get("cjk_chars") or []
    if chars:
        flags.extend(f"foreign:{c}" for c in chars)
    if "short" in issues:
        flags.append(f"short:{issues['short']}")
    if "repeat" in issues:
        flags.extend(f"repeat:{p}" for p in issues["repeat"])
    if "markdown" in issues:
        flags.extend(f"markdown:{s[:40]}" for s in issues["markdown"][:5])
    if extra:
        flags.extend(extra)
    return flags


def format_machine_reasons(issues: dict) -> list[str]:
    """Human-readable why a chapter landed in needs_fix."""
    reasons: list[str] = []
    chars = issues.get("foreign_chars") or issues.get("cjk_chars") or []
    if chars:
        sample = "".join(str(c) for c in chars[:8])
        extra = f" (+{len(chars) - 8})" if len(chars) > 8 else ""
        reasons.append(f"ký tự ngoại ngữ: {sample}{extra}")
    if "short" in issues:
        wc = issues.get("word_count", issues["short"])
        reasons.append(f"quá ngắn ({wc} từ)")
    if "repeat" in issues:
        phrases = [str(p) for p in (issues["repeat"] or [])][:3]
        if phrases:
            reasons.append(f"lặp cụm cấm: {', '.join(phrases)}")
    if "markdown" in issues:
        samples = [str(s) for s in (issues["markdown"] or [])][:2]
        if samples:
            reasons.append(f"markdown trong prose: {', '.join(samples)}")
    return reasons


def save_machine_issues(path, issues: dict) -> None:
    from pathlib import Path

    Path(path).write_text(json.dumps(issues, indent=2, ensure_ascii=False), encoding="utf-8")
