"""Export gate (Tier 1) — deterministic checks before promote/export."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.language import _VN_LETTER_RE, target_language
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prose_sanitize import find_markdown_artifacts, sanitize_prose
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import book_catalog_dir, load_config, workspace_dir

CHAPTER_HEADING_LINE = re.compile(
    r"^#\s*(?:Chapter|Chương)\s+\d+\s*:?\s*(.*)$",
    re.IGNORECASE,
)
CHAPTER_HEADING_BODY = re.compile(
    r"^#\s*(?:Chapter|Chương)\s+\d+",
    re.IGNORECASE | re.MULTILINE,
)
# Template labels at line start — bold or plain (EG-02 v2)
TEMPLATE_LINE_LABEL = re.compile(
    r"(?im)^\s*(\*\*)?\s*"
    r"(Cliffhanger|Hook|Beat|Scene\s*goal|Must\s*happen|Carries\s*to\s*next|"
    r"Next\s*chapter|Setup|Payoff)\s*:\s*"
)
MARKER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bT\d{3}\b"), "T### thread marker"),
    (TEMPLATE_LINE_LABEL, "template label leak"),
    (re.compile(r"thread_ids", re.IGNORECASE), "thread_ids"),
    (re.compile(r"scene_type\s*:", re.IGNORECASE), "scene_type:"),
    (re.compile(r"must_happen\s*:", re.IGNORECASE), "must_happen:"),
    (re.compile(r"carries_to_next", re.IGNORECASE), "carries_to_next"),
    (re.compile(r"<!--"), "HTML comment"),
    (re.compile(r"NARRATIVE CONSTRAINTS", re.IGNORECASE), "NARRATIVE CONSTRAINTS"),
    (re.compile(r"Write \*\*Chapter", re.IGNORECASE), "Write **Chapter"),
]
CJK_BODY_RE = re.compile(
    r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef"
    r"\uac00-\ud7af\u3040-\u30ff]"
)
VALID_ENDING_CHARS = frozenset(
    ".!?…)]»—–"
    + "\"'"
    + "\u201d\u2019"
)
OPEN_CURLY = "\u201c\u201e"
CLOSE_CURLY = "\u201d"
PROMOTE_RULES = frozenset({"EG-01", "EG-02", "EG-03", "EG-06", "EG-08", "EG-10", "EG-11", "EG-12"})
FULL_RULES = frozenset(
    {
        "EG-01", "EG-02", "EG-03", "EG-04", "EG-05", "EG-06", "EG-07", "EG-08",
        "EG-09", "EG-10", "EG-11", "EG-12",
    }
)


class ExportGateError(Exception):
    """Raised when export gate blocks promote or export."""


def _check(
    check_id: str,
    severity: str,
    passed: bool,
    *,
    chapter: int | None = None,
    detail: str = "",
    snippet: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": check_id,
        "severity": severity,
        "passed": passed,
    }
    if chapter is not None:
        row["chapter"] = chapter
    if detail:
        row["detail"] = detail
    if snippet:
        row["snippet"] = snippet[:240]
    return row


def normalize_heading_text(text: str) -> str:
    line = text.strip()
    if line.startswith("#"):
        line = re.sub(r"^#\s*", "", line)
    return line.strip()


def strip_leading_chapter_heading(body: str) -> str:
    lines = body.lstrip("\n").splitlines()
    if not lines:
        return body
    if CHAPTER_HEADING_LINE.match(lines[0].strip()):
        return "\n".join(lines[1:]).lstrip("\n")
    return body


def prepare_chapter_for_export(
    meta: dict,
    body: str,
    lang: str,
) -> tuple[str, str | None, str]:
    """Normalize title/subtitle/body for EPUB/DOCX rendering."""
    body = strip_leading_chapter_heading(body)
    title = str(meta.get("title") or "").strip()
    subtitle_raw = meta.get("subtitle")
    subtitle = normalize_heading_text(str(subtitle_raw)) if subtitle_raw else None

    if lang == "en":
        if subtitle:
            m = re.match(r"^Chapter\s+\d+\s*:\s*(.+)$", subtitle, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                subtitle = None
        if re.match(r"^Chương\s+\d+$", title, re.IGNORECASE) and subtitle:
            m = re.match(r"^Chapter\s+\d+\s*:\s*(.+)$", subtitle, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                subtitle = None

    if subtitle:
        if subtitle.lower() == title.lower():
            subtitle = None
        first = body.split("\n", 1)[0].strip() if body else ""
        if normalize_heading_text(first).lower() == subtitle.lower():
            subtitle = None

    if not title:
        ch = meta.get("chapter")
        title = f"Chapter {ch}" if lang == "en" and ch else f"Chương {ch}"

    return title, subtitle, body


def _last_paragraph(body: str) -> str:
    parts = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    return parts[-1] if parts else body.strip()


def _count_in(text: str, chars: str) -> int:
    return sum(text.count(c) for c in chars)


def _quote_balance_issue(last_para: str) -> tuple[bool, str]:
    """True + detail when last paragraph has broken dialogue quotes."""
    straight = last_para.count('"')
    if straight % 2 == 1:
        return True, "unbalanced straight quotes in last paragraph"
    open_curly = _count_in(last_para, OPEN_CURLY)
    close_curly = _count_in(last_para, CLOSE_CURLY)
    if open_curly != close_curly:
        return True, "unbalanced curly quotes in last paragraph"
    return False, ""


def _straight_quote_terminal_invalid(body: str) -> bool:
    """ASCII quote as final char while prose predominantly uses curly quotes."""
    text = body.strip()
    if not text or text[-1] != '"':
        return False
    curly = text.count("\u201c") + text.count("\u201d")
    return curly >= 3


def check_eg01_truncated(body: str, chapter: int) -> dict[str, Any]:
    text = body.strip()
    if not text:
        return _check("EG-01", "error", False, chapter=chapter, detail="empty body")

    last_para = _last_paragraph(text)
    unbalanced, qb_detail = _quote_balance_issue(last_para)
    if unbalanced:
        return _check(
            "EG-01",
            "error",
            False,
            chapter=chapter,
            detail=f"unclosed/truncated dialogue ({qb_detail})",
            snippet=last_para[-80:],
        )

    if _straight_quote_terminal_invalid(text):
        return _check(
            "EG-01",
            "error",
            False,
            chapter=chapter,
            detail="straight ASCII quote terminal in curly-quote prose",
            snippet=text[-80:],
        )

    last_char = text[-1]
    if last_char in VALID_ENDING_CHARS:
        return _check("EG-01", "error", True, chapter=chapter)

    if last_char.isalpha():
        return _check(
            "EG-01",
            "error",
            False,
            chapter=chapter,
            detail="ends mid-sentence (trailing letter)",
            snippet=text[-60:],
        )
    if last_char == ",":
        return _check(
            "EG-01",
            "error",
            False,
            chapter=chapter,
            detail="ends with comma",
            snippet=text[-60:],
        )
    if last_char == "-":
        return _check(
            "EG-01",
            "error",
            False,
            chapter=chapter,
            detail="ends with ASCII hyphen",
            snippet=text[-60:],
        )

    return _check(
        "EG-01",
        "error",
        False,
        chapter=chapter,
        detail=f"invalid ending: {last_char!r}",
        snippet=text[-60:],
    )


def check_eg02_markers(body: str, chapter: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for pattern, label in MARKER_PATTERNS:
        m = pattern.search(body)
        if m:
            found.append(
                _check(
                    "EG-02",
                    "error",
                    False,
                    chapter=chapter,
                    detail=label,
                    snippet=m.group(0).strip()[:120],
                )
            )
    if not found:
        found.append(_check("EG-02", "error", True, chapter=chapter))
    return found


def check_eg03_header(meta: dict, body: str, lang: str, chapter: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    title = str(meta.get("title") or "")
    subtitle = str(meta.get("subtitle") or "")
    sub_norm = normalize_heading_text(subtitle) if subtitle else ""

    for m in CHAPTER_HEADING_BODY.finditer(body):
        results.append(
            _check(
                "EG-03",
                "error",
                False,
                chapter=chapter,
                detail="markdown chapter heading in body",
                snippet=m.group(0).strip()[:120],
            )
        )
        break

    first_line = body.lstrip("\n").split("\n", 1)[0].strip() if body.strip() else ""
    first_norm = normalize_heading_text(first_line)
    if sub_norm and first_norm and sub_norm.lower() == first_norm.lower():
        results.append(
            _check(
                "EG-03",
                "error",
                False,
                chapter=chapter,
                detail="subtitle duplicates first body line",
                snippet=first_norm[:120],
            )
        )

    if lang == "en" and re.match(r"^Chương\s+\d+$", title.strip(), re.IGNORECASE):
        results.append(
            _check(
                "EG-03",
                "error",
                False,
                chapter=chapter,
                detail="Vietnamese title on English book",
                snippet=title,
            )
        )

    if subtitle.strip().startswith("#"):
        results.append(
            _check(
                "EG-03",
                "error",
                False,
                chapter=chapter,
                detail="subtitle still has markdown # prefix",
                snippet=subtitle[:120],
            )
        )

    if not results:
        results.append(_check("EG-03", "error", True, chapter=chapter))
    return results


def check_eg04_gaps(chapter_nums: list[int], expected: int) -> dict[str, Any]:
    have = set(chapter_nums)
    missing = [n for n in range(1, expected + 1) if n not in have]
    if missing:
        return _check(
            "EG-04",
            "error",
            False,
            detail=f"missing chapters: {missing}",
        )
    return _check("EG-04", "error", True, detail=f"chapters 1..{expected} complete")


def check_eg05_dup_titles(
    chapters: list[tuple[int, dict, str]],
    severity: str,
) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for ch_num, meta, body in chapters:
        sub = normalize_heading_text(str(meta.get("subtitle") or ""))
        if not sub:
            for m in CHAPTER_HEADING_LINE.finditer(body):
                sub = normalize_heading_text(m.group(0))
                break
        key = sub.lower().strip() if sub else str(meta.get("title") or ch_num).lower()
        if not key:
            continue
        if key in seen:
            results.append(
                _check(
                    "EG-05",
                    severity,
                    False,
                    chapter=ch_num,
                    detail=f"duplicate title (same as ch {seen[key]})",
                    snippet=sub[:120],
                )
            )
        else:
            seen[key] = ch_num

    if not any(r["id"] == "EG-05" and not r["passed"] for r in results):
        results.insert(0, _check("EG-05", severity, True))
    return results


def _normalize_title(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _load_book_yaml(workspace_id: str, book_slug: str) -> dict:
    path = book_catalog_dir(workspace_id, book_slug) / "book.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_concept_title(workspace_id: str) -> str | None:
    path = workspace_dir(workspace_id) / "concept.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    t = data.get("title")
    return str(t).strip() if t else None


def check_eg09_metadata(
    workspace_id: str,
    book_slug: str,
    lang: str,
) -> list[dict[str, Any]]:
    """Book-level metadata — title/language must match catalog + target_language."""
    from factory.engine.lib.catalog import book_display_title, export_language

    results: list[dict[str, Any]] = []
    book_yaml = _load_book_yaml(workspace_id, book_slug)
    yaml_title = _normalize_title(
        str(book_yaml.get("title") or book_yaml.get("book_title") or "")
    )
    export_title = _normalize_title(book_display_title(workspace_id, book_slug))
    export_lang = export_language(workspace_id)
    concept_title = _load_concept_title(workspace_id)

    if yaml_title and export_title and yaml_title != export_title:
        results.append(
            _check(
                "EG-09",
                "error",
                False,
                detail=f"dc:title source mismatch ({export_title!r} vs book.yaml {yaml_title!r})",
            )
        )

    if lang == "en":
        if yaml_title and _VN_LETTER_RE.search(yaml_title):
            results.append(
                _check(
                    "EG-09",
                    "error",
                    False,
                    detail="book.yaml title has Vietnamese text on EN book",
                    snippet=yaml_title[:80],
                )
            )
        if export_lang != "en":
            results.append(
                _check(
                    "EG-09",
                    "error",
                    False,
                    detail=f"dc:language would be {export_lang!r}, target is en",
                )
            )

    if concept_title and yaml_title and _normalize_title(concept_title) != yaml_title:
        results.append(
            _check(
                "EG-09",
                "error",
                False,
                detail=f"book.yaml title != concept.title ({concept_title[:60]})",
                snippet=yaml_title[:80],
            )
        )

    legacy_slug_bits = ("hop-dong", "chuong", "hợp-đồng")
    if any(b in book_slug.lower() for b in legacy_slug_bits):
        results.append(
            _check(
                "EG-09",
                "warn",
                False,
                detail=f"legacy Vietnamese slug: {book_slug}",
            )
        )

    if not results:
        results.append(_check("EG-09", "error", True))
    return results


def check_eg10_cjk(body: str, chapter: int, lang: str) -> dict[str, Any]:
    if lang != "en":
        return _check("EG-10", "error", True, chapter=chapter)
    m = CJK_BODY_RE.search(body)
    if not m:
        return _check("EG-10", "error", True, chapter=chapter)
    start = max(0, m.start() - 10)
    end = min(len(body), m.end() + 10)
    return _check(
        "EG-10",
        "error",
        False,
        chapter=chapter,
        detail="CJK/fullwidth character in EN prose",
        snippet=body[start:end],
    )


def check_eg11_generic_title(
    meta: dict,
    lang: str,
    workspace_id: str,
    chapter: int,
) -> dict[str, Any]:
    from factory.engine.lib.catalog import chapter_title_from_plan, is_generic_chapter_title

    title = str(meta.get("title") or "")
    book = int(meta.get("book") or 1)
    if not is_generic_chapter_title(title, chapter, lang):
        return _check("EG-11", "error", True, chapter=chapter)
    plan_title = chapter_title_from_plan(workspace_id, book, chapter)
    if plan_title:
        return _check(
            "EG-11",
            "error",
            False,
            chapter=chapter,
            detail=f"generic catalog title; plan: {plan_title[:80]}",
            snippet=title,
        )
    return _check("EG-11", "error", True, chapter=chapter)


def check_eg12_needs_fix(meta: dict, chapter: int, *, severity: str = "error") -> dict[str, Any]:
    flags = meta.get("needs_fix") or []
    if flags:
        sample = ", ".join(str(f) for f in flags[:4])
        extra = f" (+{len(flags) - 4})" if len(flags) > 4 else ""
        return _check(
            "EG-12",
            severity,
            False,
            chapter=chapter,
            detail=f"catalog needs_fix: {sample}{extra}",
        )
    return _check("EG-12", severity, True, chapter=chapter)


def check_eg06_markdown(body: str, chapter: int) -> list[dict[str, Any]]:
    artifacts = find_markdown_artifacts(body)
    if not artifacts:
        return [_check("EG-06", "error", True, chapter=chapter)]
    return [
        _check(
            "EG-06",
            "error",
            False,
            chapter=chapter,
            detail="markdown artifact in prose",
            snippet=snippet,
        )
        for snippet in artifacts[:5]
    ]


def _token_set(text: str, limit: int = 500) -> set[str]:
    words = re.findall(r"\S+", text.lower())
    return set(words[:limit])


def check_eg07_near_dup(
    chapters: list[tuple[int, dict, str]],
    severity: str,
    *,
    threshold: float = 0.92,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    tokens = {ch: _token_set(body) for ch, _meta, body in chapters}
    nums = [ch for ch, _, _ in chapters]
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            ta, tb = tokens[a], tokens[b]
            if not ta or not tb:
                continue
            jaccard = len(ta & tb) / len(ta | tb)
            if jaccard >= threshold:
                results.append(
                    _check(
                        "EG-07",
                        severity,
                        False,
                        chapter=b,
                        detail=f"near-duplicate with ch {a} (jaccard={jaccard:.2f})",
                    )
                )
    if not any(r["id"] == "EG-07" and not r["passed"] for r in results):
        results.insert(0, _check("EG-07", severity, True))
    return results


def check_eg08_short(body: str, chapter: int, min_words: int) -> dict[str, Any]:
    wc = word_count_vi(body)
    if wc < min_words:
        return _check(
            "EG-08",
            "error",
            False,
            chapter=chapter,
            detail=f"too short for publish ({wc} < {min_words} words)",
        )
    return _check("EG-08", "error", True, chapter=chapter)


def _load_chapter_items(chapters_dir: Path) -> list[tuple[Path, dict, str]]:
    from factory.engine.lib.catalog import load_chapter_items

    return load_chapter_items(chapters_dir)


def _expected_chapter_count(workspace_id: str, book_slug: str, chapter_nums: list[int]) -> int:
    book_yaml = book_catalog_dir(workspace_id, book_slug) / "book.yaml"
    if book_yaml.exists():
        data = yaml.safe_load(book_yaml.read_text(encoding="utf-8")) or {}
        if data.get("chapter_count"):
            return int(data["chapter_count"])
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    if direction.get("total_chapters"):
        return int(direction["total_chapters"])
    return max(chapter_nums) if chapter_nums else 0


def _gate_cfg(cfg: dict | None) -> dict[str, Any]:
    cfg = cfg or load_config()
    return {
        "enabled": bool(cfg.get("export_gate_enabled", True)),
        "strict": bool(cfg.get("export_gate_strict", False)),
        "dup_title": str(cfg.get("export_gate_dup_title", "warn")).lower(),
        "near_dup": str(cfg.get("export_gate_near_dup", "warn")).lower(),
        "min_publish_words": int(
            cfg.get("min_publish_words") or cfg.get("min_word_count", 1500)
        ),
        "on_promote": bool(cfg.get("export_gate_on_promote", True)),
        "publish_mode": bool(cfg.get("export_gate_publish_mode", False)),
    }


def _severity_for(config_val: str) -> str:
    return "error" if config_val == "error" else "warn"


def check_chapter_for_promote(
    meta: dict,
    body: str,
    lang: str,
    *,
    cfg: dict | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Subset per-chapter rules at promote time."""
    gcfg = _gate_cfg(cfg)
    if not gcfg["enabled"] or not gcfg["on_promote"]:
        return []
    chapter = int(meta.get("chapter") or 0)
    checks: list[dict[str, Any]] = []
    checks.append(check_eg01_truncated(body, chapter))
    checks.extend(check_eg02_markers(body, chapter))
    checks.extend(check_eg03_header(meta, body, lang, chapter))
    checks.extend(check_eg06_markdown(body, chapter))
    checks.append(check_eg08_short(body, chapter, gcfg["min_publish_words"]))
    checks.append(check_eg10_cjk(body, chapter, lang))
    if workspace_id:
        checks.append(check_eg11_generic_title(meta, lang, workspace_id, chapter))
    eg12_sev = "error" if gcfg["publish_mode"] else "warn"
    checks.append(check_eg12_needs_fix(meta, chapter, severity=eg12_sev))
    return checks


def run_export_gate(
    workspace_id: str,
    book_slug: str,
    *,
    cfg: dict | None = None,
    scope: str = "full",
) -> dict[str, Any]:
    cfg = cfg or load_config()
    gcfg = _gate_cfg(cfg)
    chapters_dir = book_catalog_dir(workspace_id, book_slug) / "chapters"
    items = _load_chapter_items(chapters_dir)
    lang = _export_lang(workspace_id, cfg)
    chapter_nums = [int(m.get("chapter") or 0) for _p, m, _b in items]
    chapter_nums = [n for n in chapter_nums if n > 0]

    checks: list[dict[str, Any]] = []
    active = PROMOTE_RULES if scope == "promote" else FULL_RULES

    if not gcfg["enabled"]:
        return _build_report(
            workspace_id,
            book_slug,
            lang,
            chapter_nums,
            checks,
            skipped=True,
        )

    dup_severity = "error" if gcfg["publish_mode"] else _severity_for(gcfg["dup_title"])

    triples = [(int(m.get("chapter") or 0), m, b) for _p, m, b in items]

    for ch_num, meta, body in triples:
        if "EG-01" in active:
            checks.append(check_eg01_truncated(body, ch_num))
        if "EG-02" in active:
            checks.extend(check_eg02_markers(body, ch_num))
        if "EG-03" in active:
            checks.extend(check_eg03_header(meta, body, lang, ch_num))
        if "EG-06" in active:
            checks.extend(check_eg06_markdown(body, ch_num))
        if "EG-08" in active:
            checks.append(check_eg08_short(body, ch_num, gcfg["min_publish_words"]))
        if "EG-10" in active:
            checks.append(check_eg10_cjk(body, ch_num, lang))
        if "EG-11" in active:
            checks.append(check_eg11_generic_title(meta, lang, workspace_id, ch_num))
        if "EG-12" in active:
            eg12_sev = "error" if gcfg["publish_mode"] else "warn"
            checks.append(check_eg12_needs_fix(meta, ch_num, severity=eg12_sev))

    if "EG-04" in active and chapter_nums:
        expected = _expected_chapter_count(workspace_id, book_slug, chapter_nums)
        checks.append(check_eg04_gaps(chapter_nums, expected))

    if "EG-05" in active and triples:
        checks.extend(check_eg05_dup_titles(triples, dup_severity))

    if "EG-07" in active and len(triples) >= 2:
        checks.extend(check_eg07_near_dup(triples, _severity_for(gcfg["near_dup"])))

    if "EG-09" in active:
        checks.extend(check_eg09_metadata(workspace_id, book_slug, lang))

    expected = _expected_chapter_count(workspace_id, book_slug, chapter_nums) if chapter_nums else 0
    return _build_report(workspace_id, book_slug, lang, chapter_nums, checks, expected=expected)


def _export_lang(workspace_id: str, cfg: dict) -> str:
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    return target_language(direction, cfg)


def _build_report(
    workspace_id: str,
    book_slug: str,
    lang: str,
    chapter_nums: list[int],
    checks: list[dict[str, Any]],
    *,
    expected: int = 0,
    skipped: bool = False,
) -> dict[str, Any]:
    passed = export_gate_pass({"checks": checks}, load_config()) if checks else True
    if skipped:
        passed = True
    errors = sum(1 for c in checks if c.get("severity") == "error" and not c.get("passed"))
    warns = sum(1 for c in checks if c.get("severity") == "warn" and not c.get("passed"))
    summary = format_export_gate_summary(
        {
            "passed": passed,
            "checks": checks,
            "skipped": skipped,
            "errors": errors,
            "warnings": warns,
        }
    )
    return {
        "ok": True,
        "passed": passed,
        "skipped": skipped,
        "workspace_id": workspace_id,
        "book_slug": book_slug,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "chapter_count": len(chapter_nums),
        "expected_chapters": expected or (max(chapter_nums) if chapter_nums else 0),
        "target_language": lang,
        "checks": checks,
        "errors": errors,
        "warnings": warns,
        "summary": summary,
    }


def export_gate_pass(report: dict[str, Any], cfg: dict | None = None) -> bool:
    gcfg = _gate_cfg(cfg)
    if report.get("skipped"):
        return True
    for check in report.get("checks") or []:
        if check.get("passed"):
            continue
        sev = check.get("severity", "error")
        if sev == "error":
            return False
        if sev == "warn" and gcfg["strict"]:
            return False
    return True


def format_export_gate_summary(report: dict[str, Any]) -> str:
    if report.get("skipped"):
        return "Export gate SKIP (disabled)"
    if report.get("passed"):
        w = report.get("warnings", 0)
        return f"Export gate PASS — {w} warning(s)" if w else "Export gate PASS"
    e = report.get("errors", 0)
    w = report.get("warnings", 0)
    return f"Export gate FAIL — {e} error(s), {w} warning(s)"


def format_export_gate_reasons(report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for check in report.get("checks") or []:
        if check.get("passed"):
            continue
        ch = check.get("chapter")
        prefix = f"ch{ch:02d}" if ch else "book"
        detail = check.get("detail") or check.get("id")
        reasons.append(f"{prefix} {check.get('id')}: {detail}")
    return reasons


def save_export_gate_report(workspace_id: str, book_slug: str, report: dict[str, Any]) -> Path:
    out_dir = book_catalog_dir(workspace_id, book_slug) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ".export_gate.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def assert_export_gate(
    workspace_id: str,
    book_slug: str,
    *,
    cfg: dict | None = None,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    report = run_export_gate(workspace_id, book_slug, cfg=cfg, scope="full")
    save_export_gate_report(workspace_id, book_slug, report)
    if not export_gate_pass(report, cfg):
        reasons = format_export_gate_reasons(report)
        msg = format_export_gate_summary(report)
        if reasons:
            msg += "\n  " + "\n  ".join(reasons[:12])
        raise ExportGateError(msg)
    return report
