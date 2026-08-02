"""Layer 1 QC — regex/machine checks before 9router QC."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.engine.lib.language import find_foreign_chars, target_language
from factory.engine.paths import workspace_dir

# Deterministic, operator-fixable — never auto-rewrite for these alone.
# Markdown (*italic* / **bold**) is format_fix → needs_fix so the user sees
# and can strip via UI markdown-fix (not silent advisory).
#
# missing_quotes is ALSO advisory forever (2026-07): tag-verb heuristics measure
# attribution vocabulary, not "speech lacks quote marks". Four false-positive
# patches proved the detector is wrong-class — do not re-promote to needs_fix.
FORMAT_ISSUE_KEYS = frozenset(
    {
        "foreign_chars",
        "cjk_chars",
        "stray_whitespace",
        "heading_artifact",
        "markdown_leaks",
        "markdown_advisory",  # legacy key → still treat as format_fix
    }
)

# Canon / story defects — may regenerate, then hard-cap → needs_review.
CONTENT_ISSUE_KEYS = frozenset(
    {
        "name_drift",
        "pov_violation",
        "repeat",
        "invented_character",
        "unsupported_case_fact",
        "bible_rule",
        "must_happen_miss",
        "cliffhanger_paste",
        "publication_duplicate_block",
        "technical_chapter_reference",
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


def _apply_locked_names_drift_checks(
    issues: dict,
    text: str,
    *,
    workspace_id: str | None,
    book: int,
) -> None:
    """Flag prose using a drifted name when locked_names already locked the role."""
    if not workspace_id or not text:
        return
    from factory.engine.lib.state_updater import load_state

    ws = workspace_dir(workspace_id)
    state = load_state(ws, book)
    locked = state.get("locked_names") if isinstance(state.get("locked_names"), dict) else {}
    if not locked:
        return
    hits: list[dict[str, Any]] = []
    husband = locked.get("husband")
    if husband == "Marcus" and re.search(r"\bHarold\b", text):
        hits.append({"found": "Harold", "canonical": "Marcus", "role": "husband"})
    prev = locked.get("previous_housekeeper")
    if prev == "Clara" and re.search(r"\bEmily(?:\s+Morrison)?\b", text):
        # Only when housekeeper context OR full invent of E.M.
        if re.search(r"housekeeper|carer|name tag", text, re.I) or re.search(
            r"\bEmily\s+Morrison\b", text
        ):
            hits.append({"found": "Emily", "canonical": "Clara", "role": "previous_housekeeper"})
    alias = locked.get("narrator_alias")
    if alias and str(alias).startswith("Anna") and re.search(r"\bSarah\s+Mills\b", text):
        hits.append({"found": "Sarah Mills", "canonical": "Anna", "role": "narrator_alias"})
    if hits:
        issues["name_drift"] = list(issues.get("name_drift") or []) + hits


def _workspace_has_canonical_ir(workspace_id: str | None) -> bool:
    if not workspace_id:
        return False
    try:
        from factory.engine.lib.canonical_ir import load_canonical_ir
        from factory.engine.paths import workspace_dir

        return load_canonical_ir(workspace_dir(workspace_id)) is not None
    except Exception:
        return False


def _apply_closed_world_story_checks(
    issues: dict,
    text: str,
    *,
    workspace_id: str | None,
    plan: dict | None,
) -> None:
    """Reject invented named cast and high-stakes case facts absent from plan."""
    if not workspace_id or not text:
        return
    from factory.engine.lib.narrative_schema import load_concept
    from factory.engine.paths import workspace_dir

    ws = workspace_dir(workspace_id)
    concept = load_concept(ws)
    allowed = {
        str(row.get("name") or "").strip().casefold()
        for row in concept.get("characters") or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    candidates: dict[str, int] = {}
    for match in re.finditer(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:'s)?\b",
        text,
    ):
        name = match.group(1).strip()
        candidates[name] = candidates.get(name, 0) + 1
    invented = [
        {"name": name, "occurrences": count}
        for name, count in candidates.items()
        if name.casefold() not in allowed
        and not re.match(r"^(?:The|A|An)\s+", name)
        and name.split()[-1].casefold()
        not in {"server", "vault", "database", "system", "software", "camera"}
        and (
            # With Canonical IR, one unsourced proper noun is enough (Holloway case).
            # Without IR, keep legacy threshold to limit false positives.
            (count >= 1 if _workspace_has_canonical_ir(workspace_id) else count >= 2)
            or re.search(rf"\bnamed\s+{re.escape(name)}\b", text)
        )
    ]
    allowed_surnames = {
        token.casefold()
        for name in allowed
        for token in name.split()
    }
    for match in re.finditer(
        r"\b([A-Z][a-z]{2,})\s+"
        r"(?:files?|dossier|transcripts?|recordings?|job)\b",
        text,
    ):
        label = match.group(1)
        if (
            label.casefold() not in allowed_surnames
            and label.casefold()
            not in {"the", "every", "each", "these", "those", "this", "that", "my", "his", "her"}
        ):
            invented.append({"name": label, "occurrences": 1, "kind": "case_label"})
    if invented:
        issues["invented_character"] = invented[:10]

    # Prefer Canonical IR allowlist over plan text (plan is not SoT).
    authority = ""
    if workspace_id:
        try:
            from factory.engine.lib.canonical_ir import (
                allowed_claim_blob,
                load_canonical_ir,
            )

            ir = load_canonical_ir(ws)
            if ir:
                authority = allowed_claim_blob(ir, 99)
        except Exception:
            authority = ""
    if not authority:
        authority = json.dumps(plan or {}, ensure_ascii=False, default=str).casefold()
    marker_patterns = {
        "autopsy report": r"\bautopsy(?:\s+report)?\b",
        "coroner": r"\bcoroner\b",
        "bank CCTV": r"\bbank(?:'s)?\s+CCTV\b",
        "financial advisor": r"\bfinancial advisor\b",
        "offshore accounts": r"\boffshore accounts?\b",
        "shell companies": r"\bshell compan(?:y|ies)\b",
        "calendar-year backstory": (
            r"\b(?:built|founded|started|created)\b.{0,24}\b(?:19|20)\d{2}\b"
        ),
        "federal investigation": r"\bfederal investigation\b",
        "Senate campaign": r"\bSenate campaign\b",
        "invented training history": r"\bsystem admin who trained\b",
        "invented planted file": r"\bfile I planted\b",
    }
    unsupported = [
        label
        for label, pattern in marker_patterns.items()
        if re.search(pattern, text, re.IGNORECASE)
        and not re.search(pattern, authority, re.IGNORECASE)
    ]
    if unsupported:
        issues["unsupported_case_fact"] = unsupported


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
# Narration: tag verb + negation / non-utterance object — NOT unquoted dialogue.
# "Arthur said nothing." must never fire; wrapping it would corrupt prose.
_NON_UTTERANCE_SPEECH_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:said|says|asked|asks|answered|answers|replied|replies|"
    r"spoke|speaks|whispered|muttered)\s+"
    r"(?:nothing|no more|not a word|little)\b|"
    r"never\s+(?:spoke|said)\b|"
    r"(?:did|does|do)\s+not\s+(?:speak|say)\b|"
    r"didn'?t\s+(?:speak|say)\b"
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


def _normalize_quotes(text: str) -> str:
    from factory.engine.lib.canon_prose_qc import normalize_typographic_quotes

    return normalize_typographic_quotes(text)


def _text_outside_quotes(text: str) -> str:
    """Strip paired quote spans so dialogue tags inside speech are ignored."""
    text = _normalize_quotes(text)
    out = re.sub(r'"[^"\n]*"', " ", text)
    out = re.sub(r"“[^”\n]*”", " ", out)
    out = re.sub(r"«[^»\n]*»", " ", out)
    return out


def _mask_non_utterance_speech(text: str) -> str:
    """Remove negated / non-utterance tag spans before dialogue-tag detection."""
    return _NON_UTTERANCE_SPEECH_RE.sub(" ", text)


def _count_dialogue_tags_outside_quotes(text: str) -> int:
    scrubbed = _mask_non_utterance_speech(_text_outside_quotes(text))
    return len(_DIALOGUE_TAG_VERBS_RE.findall(scrubbed))


def _quote_mark_count(text: str) -> int:
    text = _normalize_quotes(text)
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

    text = _normalize_quotes(text)
    hits: list[dict[str, Any]] = []

    def is_dash_dialogue(line_strip: str) -> bool:
        if not line_strip.startswith(("-", "—", "–")):
            return False
        return not _has_quote_mark(line_strip)

    def is_tag_dialogue(line_strip: str) -> bool:
        if _has_quote_mark(line_strip):
            return False
        # Tag verb + negation/non-utterance object is narration, not dialogue.
        scrubbed = _mask_non_utterance_speech(line_strip)
        if not scrubbed.strip():
            return False
        return bool(_TAG_DIALOGUE_LINE_RE.search(scrubbed))

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
    text = _normalize_quotes(text)
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


def classify_machine_issues(issues: dict) -> dict[str, Any]:
    """Split machine_qc issues into format_fix / content_fail / length buckets.

    - format_fix: foreign chars, whitespace, markdown *…* — operator hand-edits, no rewrite
    - length (short): below min_word_count — MUST expand/rewrite; never treat as hand-fix
    - content_fail: POV / name drift / bible — capped rewrites then needs_review
    missing_quotes stays ADVISORY only — never format_fix.
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
        "quotes_advisory",  # tag-verb heuristic — never content_fail / needs_fix
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


def find_must_happen_misses(
    text: str,
    plan: dict | None,
    *,
    min_ratio: float = 0.22,
) -> list[dict[str, Any]]:
    """Flag plan must_happen items weakly covered by chapter prose (betrayal of lock)."""
    if not isinstance(plan, dict):
        return []
    raw = plan.get("must_happen") or []
    if not isinstance(raw, list) or not raw:
        return []
    from factory.engine.lib.intent_gates import _coverage_ratio, _tokens

    prose = str(text or "")
    misses: list[dict[str, Any]] = []
    for item in raw:
        beat = str(item or "").strip()
        # Compiler pointer, not prose vocabulary. The executable threshold
        # details are separately projected into the same plan/prompt and are
        # still checked; requiring "siblings/threshold_events.yaml" on-page
        # creates a guaranteed false negative after a correct scene.
        if re.search(
            r"\bsee\s+siblings/threshold_events\.ya?ml\b",
            beat,
            re.IGNORECASE,
        ):
            continue
        # Seal marker is a planning-level turn label. Concrete must_happen
        # rows in the same plan carry the on-page action; requiring the
        # abstract label verbatim (e.g. "a false interpretation takes hold")
        # rejects correct dramatization.
        if beat.startswith("[INTENT LOCK]"):
            continue
        if not beat or len(_tokens(beat)) < 5:
            continue
        ratio = _coverage_ratio(beat, prose)
        if ratio < min_ratio:
            misses.append(
                {
                    "must_happen": beat[:160],
                    "coverage": round(ratio, 3),
                    "min_ratio": min_ratio,
                }
            )
    return misses


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
    publication_safety: bool = False,
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

    _apply_canon_registry_checks(
        issues, text, workspace_id=workspace_id, book=book
    )
    _apply_locked_names_drift_checks(
        issues, text, workspace_id=workspace_id, book=book
    )

    resolved_plan = plan
    if resolved_plan is None and workspace_id and chapter:
        from factory.engine.lib.catalog import chapter_beat_from_plan

        resolved_plan = chapter_beat_from_plan(workspace_id, book, chapter)

    _apply_closed_world_story_checks(
        issues,
        text,
        workspace_id=workspace_id,
        plan=resolved_plan,
    )

    mh_miss = find_must_happen_misses(text, resolved_plan)
    if mh_miss:
        issues["must_happen_miss"] = mh_miss

    cliff = ""
    if isinstance(resolved_plan, dict):
        raw_cliff = resolved_plan.get("cliffhanger") or ""
        cliff = raw_cliff if isinstance(raw_cliff, str) else str(raw_cliff)
    if cliff.strip():
        from factory.engine.lib.export_gate import find_cliffhanger_paste

        paste_hit = find_cliffhanger_paste(text, cliff)
        if paste_hit:
            issues["cliffhanger_paste"] = paste_hit

    quote_hits = find_missing_dialogue_quote_hits(
        text, plan=resolved_plan, direction=direction
    )
    # Advisory only — never needs_fix / never machine_pass fail / never format_fix.
    # Heuristic is wrong-class (attribution verbs ≠ missing speech quotes).
    if quote_hits:
        issues["quotes_advisory"] = [
            {"line": h.get("line"), "snippet": h.get("snippet")}
            for h in quote_hits[:20]
        ]
        soft_note = (
            f"quotes advisory ({len(quote_hits)} hit) — tag-verb heuristic; "
            "eye-check only, không chặn promote"
        )
        issues["warnings"] = list(issues.get("warnings") or []) + [soft_note]

    soft_warnings = find_sparse_quote_warnings(
        text, plan=resolved_plan, direction=direction
    )
    if soft_warnings:
        issues["warnings"] = list(issues.get("warnings") or []) + soft_warnings

    format_locations: dict[str, list] = {}
    ws_hits = find_stray_whitespace_hits(text)
    if ws_hits:
        issues["stray_whitespace"] = True
        format_locations["stray_whitespace"] = ws_hits
    if format_locations:
        issues["format_locations"] = format_locations

    # Format fail — surfaces in needs_fix so user can strip * / ** via UI fixer
    from factory.engine.lib.prose_sanitize import find_markdown_leaks

    md_leaks = find_markdown_leaks(text)
    if md_leaks:
        issues["markdown_leaks"] = [
            {"id": h["id"], "kind": h["kind"], "match": h["match"], "context": h["context"]}
            for h in md_leaks[:20]
        ]

    # Run publication-safety checks before labeling a chapter READY. These
    # previously existed only at promote/export, creating misleading READY files
    # that were guaranteed to fail in the next stage.
    from factory.engine.lib.export_gate import check_eg16_duplicate_block
    from factory.engine.lib.technical_refs import find_technical_chapter_reference

    duplicate_failures = (
        [
            check
            for check in check_eg16_duplicate_block(text, int(chapter or 0))
            if not check.get("passed") and check.get("severity") == "error"
        ]
        if publication_safety
        else []
    )
    if duplicate_failures:
        issues["publication_duplicate_block"] = [
            {
                "code": check.get("code") or check.get("id"),
                "detail": check.get("detail"),
                "snippet": check.get("snippet"),
            }
            for check in duplicate_failures
        ]
    technical_ref = (
        find_technical_chapter_reference(text) if publication_safety else None
    )
    if technical_ref:
        issues["technical_chapter_reference"] = technical_ref

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
    for hit in issues.get("name_drift") or []:
        if isinstance(hit, dict):
            flags.append(f"name_drift:{hit.get('found')}->{hit.get('canonical')}")
    if "pov_violation" in issues:
        flags.append("pov_violation:first_person")
    for miss in issues.get("must_happen_miss") or []:
        if isinstance(miss, dict):
            flags.append(f"must_happen_miss:{str(miss.get('must_happen') or '')[:48]}")
    if issues.get("cliffhanger_paste"):
        hit = issues["cliffhanger_paste"]
        if isinstance(hit, dict):
            flags.append(
                f"cliffhanger_paste:end_sim={hit.get('end_similarity')}"
            )
        else:
            flags.append("cliffhanger_paste")
    if issues.get("publication_duplicate_block"):
        flags.append("publication_duplicate_block")
    if issues.get("technical_chapter_reference"):
        flags.append(
            "technical_chapter_reference:"
            + str(issues["technical_chapter_reference"])[:48]
        )
    # missing_quotes / quotes_advisory: never needs_fix (advisory forever)
    if "stray_whitespace" in issues:
        flags.append("stray_whitespace")
    md = issues.get("markdown_leaks") or issues.get("markdown_advisory") or []
    if md:
        sample = next(
            (str(h.get("match") or "") for h in md if isinstance(h, dict) and h.get("match")),
            "*…*",
        )
        flags.append(f"markdown:{sample[:40]}")
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
    md = issues.get("markdown_leaks") or issues.get("markdown_advisory") or []
    if md:
        samples = [
            str(h.get("match") or "")
            for h in md[:3]
            if isinstance(h, dict) and h.get("match")
        ]
        bit = f" — {'; '.join(samples)}" if samples else ""
        reasons.append(
            f"markdown leak ({len(md)} hit){bit} — vào needs_fix, dùng UI strip * /**"
        )
    q_adv = issues.get("quotes_advisory") or []
    if q_adv:
        bits = [
            f"L{h.get('line')}: {h.get('snippet')}"
            for h in q_adv[:3]
            if h.get("snippet")
        ]
        detail = (" — " + "; ".join(bits)) if bits else ""
        reasons.append(
            f"quotes advisory ({len(q_adv)} hit){detail} — heuristic sai lớp, không chặn promote"
        )
    for hit in issues.get("name_drift") or []:
        if isinstance(hit, dict):
            reasons.append(
                f"name drift: {hit.get('found')} → {hit.get('canonical')}"
            )
    if "pov_violation" in issues:
        pv = issues["pov_violation"]
        count = pv.get("count", "?") if isinstance(pv, dict) else pv
        reasons.append(f"POV first-person outside dialogue ({count} hits)")
    mh_miss = issues.get("must_happen_miss") or []
    if mh_miss:
        samples = [
            str(m.get("must_happen") or "")[:60]
            for m in mh_miss[:3]
            if isinstance(m, dict)
        ]
        bit = f": {'; '.join(samples)}" if samples else ""
        reasons.append(f"thiếu MUST HAPPEN khóa ({len(mh_miss)}){bit}")
    if issues.get("cliffhanger_paste"):
        hit = issues["cliffhanger_paste"]
        sim = hit.get("end_similarity") if isinstance(hit, dict) else "?"
        reasons.append(
            f"cliffhanger paste (near-dup ending, end_sim={sim}) — "
            "dẫn tới cliff, không dán lại câu prompt"
        )
    if "stray_whitespace" in issues:
        reasons.append("khoảng trắng thừa cuối dòng (stray whitespace)")

    for hit in issues.get("publication_duplicate_block") or []:
        if isinstance(hit, dict):
            reasons.append(
                "publication duplicate block: "
                + str(hit.get("detail") or hit.get("snippet") or "")[:180]
            )
    if issues.get("technical_chapter_reference"):
        reasons.append(
            "technical chapter label in prose: "
            + str(issues["technical_chapter_reference"])[:120]
        )

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
        reasons.insert(0, "[format_fix — chỉ sửa tay, không rewrite]")
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
