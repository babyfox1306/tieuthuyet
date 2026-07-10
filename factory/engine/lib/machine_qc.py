"""Layer 1 QC — regex/machine checks before 9router QC."""

from __future__ import annotations

import json
import re
from pathlib import Path

from factory.engine.lib.language import find_foreign_chars, target_language
from factory.engine.lib.prose_sanitize import find_markdown_artifacts
from factory.engine.paths import workspace_dir


def word_count_vi(text: str) -> int:
    """Đếm từ/chữ — dùng cho mọi target_language."""
    body = re.sub(r"^#.*$", "", text, flags=re.M).strip()
    return len(re.findall(r"\S+", body))


def find_cjk(text: str) -> list[str]:
    """Deprecated — dùng find_foreign_chars. Giữ cho script cũ."""
    found = re.findall(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff]", text)
    return sorted(set(found))


def _apply_canon_registry_checks(
    issues: dict,
    text: str,
    *,
    workspace_id: str | None,
    book: int,
) -> None:
    if not workspace_id:
        return
    from factory.engine.lib.canon_prose_qc import canon_prose_issues
    from factory.engine.lib.canon_registry import build_canon_registry, canon_registry_path

    ws = workspace_dir(workspace_id)
    if not canon_registry_path(ws).exists():
        return
    registry = build_canon_registry(ws, book)
    issues.update(canon_prose_issues(text, registry))


def machine_qc(
    text: str,
    *,
    min_words: int = 1500,
    banned_phrases: list[str] | None = None,
    phrases_already_used: list[str] | None = None,
    target_lang: str | None = None,
    direction: dict | None = None,
    cfg: dict | None = None,
    workspace_id: str | None = None,
    book: int = 1,
) -> dict:
    issues: dict = {}
    lang = target_lang or target_language(direction, cfg)
    foreign = find_foreign_chars(text, lang)
    if foreign:
        issues["foreign_chars"] = foreign
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

    _apply_canon_registry_checks(
        issues, text, workspace_id=workspace_id, book=book
    )
    return issues


def machine_pass(issues: dict) -> bool:
    if any(
        k in issues
        for k in (
            "foreign_chars",
            "cjk_chars",
            "short",
            "repeat",
            "markdown",
            "name_drift",
            "pov_violation",
            "spice_violation",
        )
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
    for hit in issues.get("name_drift") or []:
        if isinstance(hit, dict):
            flags.append(f"name_drift:{hit.get('found')}->{hit.get('canonical')}")
    if "pov_violation" in issues:
        flags.append("pov_violation:first_person")
    if issues.get("spice_violation"):
        flags.append("spice_violation")
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
    for hit in issues.get("name_drift") or []:
        if isinstance(hit, dict):
            reasons.append(
                f"name drift: {hit.get('found')} → {hit.get('canonical')}"
            )
    if "pov_violation" in issues:
        pv = issues["pov_violation"]
        count = pv.get("count", "?") if isinstance(pv, dict) else pv
        reasons.append(f"POV first-person outside dialogue ({count} hits)")
    if issues.get("spice_violation"):
        markers = issues["spice_violation"]
        if isinstance(markers, list):
            reasons.append(f"spice violation markers: {', '.join(str(m) for m in markers[:4])}")
    return reasons


def save_machine_issues(path, issues: dict) -> None:
    Path(path).write_text(json.dumps(issues, indent=2, ensure_ascii=False), encoding="utf-8")
