"""Layer 1 QC — regex/machine checks before 9router QC."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.lib.language import find_foreign_chars, target_language
from factory.engine.lib.prose_sanitize import find_markdown_artifacts
from factory.engine.paths import workspace_dir

# Deterministic, operator-fixable — never auto-rewrite for these alone.
FORMAT_ISSUE_KEYS = frozenset(
    {
        "markdown",
        "missing_quotes",
        "foreign_chars",
        "cjk_chars",
        "stray_whitespace",
        "heading_artifact",
    }
)

# Canon / story defects — may regenerate, then hard-cap → needs_review.
CONTENT_ISSUE_KEYS = frozenset(
    {
        "name_drift",
        "pov_violation",
        "repeat",
        "invented_character",
        "bible_rule",
    }
)

# Length is expandable a few times, then needs_fix (not endless rewrite).
LENGTH_ISSUE_KEYS = frozenset({"short"})


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


_QUOTE_CHARS = ('"', "“", "”", "«", "»")
_DIALOGUE_TAG_VERBS_RE = re.compile(
    r"\b(?:"
    r"said|asked|whispered|muttered|replied|shouted|cried|answered|snapped|"
    r"murmured|called|yelled|hissed|growled|"
    r"nói|hỏi|cười|thì thầm|lẩm bẩm|đáp|trả lời"
    r")\b",
    re.IGNORECASE,
)
_TAG_DIALOGUE_LINE_RE = re.compile(
    r"(?:"
    # "...speech..., she said" / "...speech..., Clara whispered"
    r",\s*(?:cô|anh|hắn|nàng|ông|bà|ta|y|[Ss]he|[Hh]e|[Tt]hey|[Ii]t|[A-Z][\w'-]*)\s+"
    r"(?i:nói|hỏi|cười|thì thầm|lẩm bẩm|đáp|trả lời|said|asked|whispered|"
    r"muttered|replied|shouted|cried|answered|snapped|murmured)\b"
    r"|"
    # "She said ..." / "Clara whispered ..." (proper name keeps capital; verbs case-insensitive)
    r"\b(?:[Ss]he|[Hh]e|[Tt]hey|[Ii]t|cô|anh|hắn|nàng|ông|bà|ta|y|[A-Z][\w'-]*)\s+"
    r"(?i:said|asked|whispered|muttered|replied|shouted|cried|answered|snapped|"
    r"murmured|nói|hỏi|thì thầm|lẩm bẩm|đáp|trả lời)\b"
    r")"
)
# Plan/direction signals that sparse dialogue is intentional — never fail on quote count.
_LOW_DIALOGUE_SIGNAL_RE = re.compile(
    r"\[ISOLATION\]|"
    r"\bisolat(?:ion|ed)\b|"
    r"\bsolo[- ](?:pov|point of view|character)\b|"
    r"\bsingle[- ]character\b|"
    r"\babsence(?:[- ]only)?\b|"
    r"\bnear[- ]zero dialogue\b|"
    r"\b(?:no|minimal|little)\s+dialogue\b|"
    r"\binternal (?:narration|monologue)\b|"
    r"\bcatalog(?:ue)? notes\b|"
    r"\bno (?:spoken|external) (?:dialogue|speech)\b|"
    r"\bunassigned\s*\(\s*no male lead\s*\)",
    re.IGNORECASE,
)


def _line_locations(text: str, predicate) -> list[dict[str, Any]]:
    """Return {line, snippet} for lines matching predicate(line_strip)."""
    out: list[dict[str, Any]] = []
    for i, line in enumerate(text.split("\n"), start=1):
        line_strip = line.strip()
        if not line_strip:
            continue
        if predicate(line_strip):
            out.append({"line": i, "snippet": line_strip[:100]})
            if len(out) >= 8:
                break
    return out


def _has_quote_mark(s: str) -> bool:
    return any(q in s for q in _QUOTE_CHARS)


def _text_outside_quotes(text: str) -> str:
    """Strip paired quote spans so dialogue tags inside speech are ignored."""
    out = re.sub(r'"[^"\n]*"', " ", text)
    out = re.sub(r"“[^”\n]*”", " ", out)
    out = re.sub(r"«[^»\n]*»", " ", out)
    return out


def _count_dialogue_tags_outside_quotes(text: str) -> int:
    return len(_DIALOGUE_TAG_VERBS_RE.findall(_text_outside_quotes(text)))


def _quote_mark_count(text: str) -> int:
    return sum(text.count(q) for q in ('"', "“", "”"))


def _plan_direction_blob(plan: dict | None, direction: dict | None) -> str:
    parts: list[str] = []
    if isinstance(plan, dict):
        for key in (
            "must_happen",
            "must_not",
            "spice_note",
            "chapter_task",
            "beat_summary",
            "one_line_summary",
            "emotional_beat",
            "opens_with",
            "cliffhanger",
        ):
            val = plan.get(key)
            if isinstance(val, list):
                parts.extend(str(x) for x in val if x is not None)
            elif val is not None and str(val).strip():
                parts.append(str(val))
    if isinstance(direction, dict):
        for key in (
            "goal",
            "blurb",
            "narrative_profile",
            "male_lead",
            "female_lead",
            "pov",
        ):
            val = direction.get(key)
            if val is not None and str(val).strip():
                parts.append(str(val))
        tropes = direction.get("tropes")
        if isinstance(tropes, list):
            parts.extend(str(t) for t in tropes if t is not None)
    return "\n".join(parts)


def expects_low_dialogue(
    plan: dict | None = None,
    direction: dict | None = None,
) -> bool:
    """True when plan/direction signals isolation or intentional solo / low dialogue."""
    return bool(_LOW_DIALOGUE_SIGNAL_RE.search(_plan_direction_blob(plan, direction)))


def find_missing_dialogue_quote_hits(
    text: str,
    *,
    plan: dict | None = None,
    direction: dict | None = None,
) -> list[dict[str, Any]]:
    """Locate structurally unquoted dialogue (never fail on raw quote count alone).

    Sparse quotation marks are normal for isolation / solo-POV chapters. Those
    signal via plan ``[ISOLATION]`` / isolation language — suppress entirely.
    Otherwise only flag dangling dialogue-tag verbs (or dash speech) outside quotes.
    """
    if expects_low_dialogue(plan, direction):
        return []

    hits: list[dict[str, Any]] = []

    def is_dash_dialogue(line_strip: str) -> bool:
        if not line_strip.startswith(("-", "—", "–")):
            return False
        return not _has_quote_mark(line_strip)

    def is_tag_dialogue(line_strip: str) -> bool:
        if _has_quote_mark(line_strip):
            return False
        return bool(_TAG_DIALOGUE_LINE_RE.search(line_strip))

    hits.extend(_line_locations(text, is_dash_dialogue))
    if len(hits) < 8:
        for h in _line_locations(text, is_tag_dialogue):
            if h not in hits:
                hits.append(h)
            if len(hits) >= 8:
                break

    # Real case: many dialogue-tag verbs outside quotes and zero quote marks.
    total_quotes = _quote_mark_count(text)
    outside_tags = _count_dialogue_tags_outside_quotes(text)
    if total_quotes == 0 and outside_tags >= 3 and not hits:
        hits.append(
            {
                "line": 0,
                "snippet": (
                    f"({outside_tags} dialogue-tag verbs outside quotes, "
                    f"0 quote marks)"
                ),
            }
        )
    return hits


def find_sparse_quote_warnings(
    text: str,
    *,
    plan: dict | None = None,
    direction: dict | None = None,
) -> list[str]:
    """Soft WARN only — never feeds needs_fix / missing_quotes.

    Sparse quotes alone do not warn (isolation chapters are legitimate).
    Emits at most a soft note when many dialogue tags sit outside quotes
    while quote marks are sparse but non-zero (structural hits already cover
    the zero-quote case as a format issue).
    """
    if expects_low_dialogue(plan, direction):
        return []
    total_quotes = _quote_mark_count(text)
    outside_tags = _count_dialogue_tags_outside_quotes(text)
    if 0 < total_quotes < 4 and outside_tags >= 3:
        return [
            f"sparse quotes ({total_quotes}) with {outside_tags} "
            f"dialogue-tag verbs outside quotation marks"
        ]
    return []


def find_missing_dialogue_quotes(
    text: str,
    *,
    plan: dict | None = None,
    direction: dict | None = None,
) -> bool:
    """Return True if structurally unquoted dialogue is detected."""
    return bool(
        find_missing_dialogue_quote_hits(text, plan=plan, direction=direction)
    )

def find_stray_whitespace_hits(text: str) -> list[dict[str, Any]]:
    """Trailing spaces / tabs on lines (operator-fixable)."""
    hits: list[dict[str, Any]] = []
    for i, line in enumerate(text.split("\n"), start=1):
        if line.endswith((" ", "\t")) and line.strip():
            hits.append({"line": i, "snippet": repr(line[-20:])})
            if len(hits) >= 5:
                break
    return hits


def find_markdown_locations(text: str) -> list[dict[str, Any]]:
    """Map markdown samples to approximate line numbers."""
    samples = find_markdown_artifacts(text)
    locs: list[dict[str, Any]] = []
    lines = text.split("\n")
    for sample in samples:
        line_no = 0
        for i, line in enumerate(lines, start=1):
            if sample in line:
                line_no = i
                break
        locs.append({"line": line_no, "snippet": sample[:100]})
    return locs


def classify_machine_issues(issues: dict) -> dict[str, Any]:
    """Split machine_qc issues into format_fix / content_fail / length buckets.

    - format_fix: ``*`` markdown, quotes, whitespace — operator hand-edits, no rewrite
    - length (short): below min_word_count — MUST expand/rewrite; never treat as hand-fix
    - content_fail: POV / name drift / bible — capped rewrites then needs_review
    """
    format_fix = {k: issues[k] for k in FORMAT_ISSUE_KEYS if k in issues}
    content_fail = {k: issues[k] for k in CONTENT_ISSUE_KEYS if k in issues}
    length = {k: issues[k] for k in LENGTH_ISSUE_KEYS if k in issues}
    known = FORMAT_ISSUE_KEYS | CONTENT_ISSUE_KEYS | LENGTH_ISSUE_KEYS | {
        "word_count",
        "target_language",
        "classification",
        "retry_meta",
        "format_locations",
        "warnings",
    }
    for k, v in issues.items():
        if k not in known and not str(k).startswith("_"):
            content_fail[k] = v
    has_format = bool(format_fix)
    has_content = bool(content_fail)
    has_length = bool(length)
    return {
        "format_fix": format_fix,
        "content_fail": content_fail,
        "length": length,
        # ONLY typography/format — never include short/length
        "format_only": has_format and not has_content and not has_length,
        "length_only": has_length and not has_content and not has_format,
        "has_format": has_format,
        "has_content": has_content,
        "has_length": has_length,
    }


def is_format_only_issues(issues: dict) -> bool:
    """True only for hand-fixable typography — short chapters are NEVER format_only."""
    return bool(classify_machine_issues(issues)["format_only"])


def is_length_fail(issues: dict) -> bool:
    return bool(classify_machine_issues(issues)["has_length"])


def has_content_fail(issues: dict) -> bool:
    return bool(classify_machine_issues(issues)["has_content"])


def machine_qc(
    text: str,
    *,
    min_words: int = 1250,
    banned_phrases: list[str] | None = None,
    phrases_already_used: list[str] | None = None,
    target_lang: str | None = None,
    direction: dict | None = None,
    cfg: dict | None = None,
    workspace_id: str | None = None,
    book: int = 1,
    chapter: int | None = None,
    plan: dict | None = None,
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

    resolved_plan = plan
    if resolved_plan is None and workspace_id and chapter:
        from factory.engine.lib.catalog import chapter_beat_from_plan

        resolved_plan = chapter_beat_from_plan(workspace_id, book, chapter)

    quote_hits = find_missing_dialogue_quote_hits(
        text, plan=resolved_plan, direction=direction
    )
    if quote_hits:
        issues["missing_quotes"] = True

    soft_warnings = find_sparse_quote_warnings(
        text, plan=resolved_plan, direction=direction
    )
    if soft_warnings:
        issues["warnings"] = list(issues.get("warnings") or []) + soft_warnings

    format_locations: dict[str, list] = {}
    if markdown:
        format_locations["markdown"] = find_markdown_locations(text)
    if quote_hits:
        format_locations["missing_quotes"] = quote_hits
    ws_hits = find_stray_whitespace_hits(text)
    if ws_hits:
        issues["stray_whitespace"] = True
        format_locations["stray_whitespace"] = ws_hits
    if format_locations:
        issues["format_locations"] = format_locations

    issues["classification"] = classify_machine_issues(issues)
    return issues


def machine_pass(issues: dict) -> bool:
    cls = classify_machine_issues(issues)
    if cls["has_format"] or cls["has_content"] or cls["has_length"]:
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
    if "missing_quotes" in issues:
        flags.append("missing_quotes:dialogue")
    if "stray_whitespace" in issues:
        flags.append("stray_whitespace")
    if extra:
        flags.extend(extra)
    return flags


def format_machine_reasons(issues: dict) -> list[str]:
    """Human-readable why a chapter landed in needs_fix / content review."""
    reasons: list[str] = []
    locs = issues.get("format_locations") or {}

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
        md_locs = locs.get("markdown") or []
        if md_locs:
            bits = [
                f"L{h.get('line')}: {h.get('snippet')}"
                for h in md_locs[:3]
                if h.get("snippet")
            ]
            reasons.append("markdown trong prose — " + "; ".join(bits))
        else:
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
    if "missing_quotes" in issues:
        q_locs = locs.get("missing_quotes") or []
        if q_locs:
            bits = [
                f"L{h.get('line')}: {h.get('snippet')}"
                for h in q_locs[:3]
                if h.get("snippet")
            ]
            reasons.append("thiếu dấu ngoặc kép đối thoại — " + "; ".join(bits))
        else:
            reasons.append("thiếu dấu ngoặc kép đối thoại (dialogue quotes missing)")
    if "stray_whitespace" in issues:
        reasons.append("khoảng trắng thừa cuối dòng (stray whitespace)")

    cls = issues.get("classification") or classify_machine_issues(issues)
    if cls.get("has_length"):
        wc = issues.get("word_count", issues.get("short", "?"))
        meta = issues.get("retry_meta") or {}
        expands = meta.get("short_expands")
        length_rw = meta.get("length_rewrites")
        cap_e = meta.get("max_short_retries")
        cap_l = meta.get("max_length_retries")
        bits = []
        if expands is not None and cap_e is not None:
            bits.append(f"expand {expands}/{cap_e}")
        if length_rw is not None and cap_l is not None:
            bits.append(f"rewrite {length_rw}/{cap_l}")
        bit = f" ({', '.join(bits)})" if bits else ""
        reasons.insert(
            0,
            f"[length_fail — {wc} từ < min; đã expand/rewrite; "
            f"KHÔNG cho qua ready{bit} — không phải lỗi dấu *]",
        )
    elif cls.get("format_only"):
        reasons.insert(0, "[format_fix — chỉ sửa dấu */quotes tay, không rewrite]")
    elif cls.get("has_content"):
        meta = issues.get("retry_meta") or {}
        used = meta.get("content_attempts")
        cap = meta.get("max_content_retries")
        if used is not None and cap is not None:
            reasons.insert(0, f"[content_fail — retries {used}/{cap}]")
        else:
            reasons.insert(0, "[content_fail]")
    return reasons


def save_machine_issues(path, issues: dict) -> None:
    Path(path).write_text(json.dumps(issues, indent=2, ensure_ascii=False), encoding="utf-8")
