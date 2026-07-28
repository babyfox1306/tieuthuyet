"""Canon bible schema — LUẬT máy (generic). Dữ liệu từng cuốn nằm trong series.json."""

from __future__ import annotations

import re
from typing import Any

# lead_relation values that imply shared blood — forbidden for romance leads
FORBIDDEN_LEAD_RELATIONS = frozenset(
    {
        "blood_relative",
        "sibling",
        "half_sibling",
        "parent_child",
        "cousin",
        "family",
        "same_blood",
        "adopted_sibling",
        "step_sibling",
    }
)

ALLOWED_RELATION_TYPES = frozenset(
    {
        "mẹ ruột",
        "mẹ kế",
        "cha ruột",
        "cha kế",
        "em gái",
        "anh trai",
        "chị gái",
        "em trai",
        "con ruột",
        "con nuôi",
        "người yêu cũ",
        "bạn thân",
        "đối thủ",
        "cấp dưới",
        "cấp trên",
        "hàng xóm",
        "luật sư",
        "bác sĩ",
        "bảo mẫu",
        "bạn đời cũ",
        "thư ký",
        "trợ lý",
        "mẹ chồng",
        "mẹ vợ",
        "cha chồng",
        "cha vợ",
        "họ hàng xa",
        "người lạ",
        "đồng nghiệp",
        "bạn cùng lớp",
        "hôn phu cũ",
        "hôn thê cũ",
    }
)

# Patterns implying blood kinship between leads (language-agnostic + Vietnamese)
BLOOD_KINSHIP_PHRASES = [
    r"em gái",
    r"anh trai",
    r"chị gái",
    r"em trai",
    r"ruột thịt",
    r"cùng cha",
    r"cùng mẹ",
    r"cùng máu",
    r"họ hàng",
    r"anh em ruột",
    r"chị em ruột",
    r"half[\s-]?sibling",
    r"blood relative",
    r"same mother",
    r"same father",
    r"cousin",
    r"đồng huyết",
]

RELATION_TYPE_ALIASES: dict[str, str] = {
    "mẹ đẻ": "mẹ ruột",
    "mẹ nuôi": "mẹ kế",
    "mẹ kế": "mẹ kế",
    "mẹ ruột": "mẹ ruột",
    "bố ruột": "cha ruột",
    "bố nuôi": "cha kế",
    "cha kế": "cha kế",
    "cha ruột": "cha ruột",
    "mẹ chồng": "mẹ chồng",
    "mẹ vợ": "mẹ vợ",
    "người yêu cũ": "người yêu cũ",
    "em gái ruột": "em gái",
    "anh trai ruột": "anh trai",
}

# English relation_type values (target_language=en) — preferred enum; pattern fallback for free labels
ALLOWED_RELATION_TYPES_EN = frozenset(
    {
        "mother",
        "father",
        "stepmother",
        "stepfather",
        "uncle",
        "aunt",
        "cousin",
        "niece",
        "nephew",
        "younger sister",
        "older sister",
        "younger brother",
        "older brother",
        "biological child",
        "adopted child",
        "ex",
        "ex-boyfriend",
        "ex-girlfriend",
        "ex-fiancé",
        "ex-fiance",
        "ex-fiancée",
        "ex-fiancee",
        "best friend",
        "rival",
        "subordinate",
        "superior",
        "boss",
        "neighbor",
        "lawyer",
        "doctor",
        "physician",
        "attending physician",
        "oncologist",
        "nanny",
        "ex-spouse",
        "secretary",
        "assistant",
        "mother-in-law",
        "father-in-law",
        "distant relative",
        "stranger",
        "colleague",
        "former colleague",
        "classmate",
        "business partner",
    }
)

# Short descriptive English phrase — Unicode letters OK (ex-fiancée, etc.)
_EN_RELATION_LABEL_RE = re.compile(
    r"^[\w][\w\s,'\-/().&]{0,78}[\w0-9)]?$|^[\w]{2,40}$",
    re.UNICODE,
)


def bible_language(bible: dict) -> str:
    lang = str(bible.get("meta", {}).get("target_language", "vi")).strip().lower()
    return "en" if lang == "en" else "vi"


def relation_type_valid(rt: str, lang: str) -> bool:
    raw = str(rt or "").strip()
    if not raw:
        return False
    if lang == "vi":
        if raw in ALLOWED_RELATION_TYPES:
            return True
        return raw.lower() in RELATION_TYPE_ALIASES
    if raw in ALLOWED_RELATION_TYPES or raw.lower() in RELATION_TYPE_ALIASES:
        return False
    key = raw.lower()
    if key in ALLOWED_RELATION_TYPES_EN:
        return True
    if 2 <= len(raw) <= 80 and _EN_RELATION_LABEL_RE.fullmatch(raw):
        # Must contain at least one letter (reject "123", "---", etc.)
        return bool(re.search(r"[^\W\d_]", raw, re.UNICODE))
    return False


def _require(obj: dict, path: str, errors: list[str], *, typ: type | tuple[type, ...] = str) -> Any:
    parts = path.split(".")
    cur: Any = obj
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            errors.append(f"missing:{path}")
            return None
        cur = cur[p]
    if cur is None or cur == "" or cur == []:
        errors.append(f"empty:{path}")
        return None
    if typ and not isinstance(cur, typ):
        errors.append(f"type:{path}")
        return None
    return cur


def female_lead(bible: dict) -> dict:
    if "leads" in bible:
        return bible.get("leads", {}).get("female", {}) or {}
    return bible.get("characters", {}).get("female_lead", {}) or {}


def male_lead(bible: dict) -> dict:
    if "leads" in bible:
        return bible.get("leads", {}).get("male", {}) or {}
    return bible.get("characters", {}).get("male_lead", {}) or {}


def lead_names(bible: dict) -> tuple[str, str]:
    f = str(female_lead(bible).get("name", "")).strip()
    m = str(male_lead(bible).get("name", "")).strip()
    return f, m


def validate_bible(bible: dict, *, concept: dict | None = None) -> list[str]:
    """Trả list lỗi. Rỗng = pass schema + luật bất biến."""
    errors: list[str] = []

    _require(bible, "meta.series_id", errors)
    _require(bible, "meta.genre", errors)
    _require(bible, "meta.target_language", errors)

    for side in ("female", "male"):
        base = f"leads.{side}"
        _require(bible, f"{base}.name", errors)
        age = _require(bible, f"{base}.age", errors, typ=(int, float))
        if age is not None and int(age) < 18:
            errors.append(f"underage:{base}.age")
        _require(bible, f"{base}.voice", errors)
        tics = _require(bible, f"{base}.tics", errors, typ=list)
        if tics is not None and len(tics) < 1:
            errors.append(f"empty:{base}.tics")
        _require(bible, f"{base}.boundary", errors)

    cast = bible.get("supporting_cast")
    if not isinstance(cast, list) or len(cast) < 1:
        errors.append("empty:supporting_cast")
    else:
        for i, c in enumerate(cast):
            if not isinstance(c, dict):
                errors.append(f"supporting_cast[{i}]:not_object")
                continue
            if not c.get("name"):
                errors.append(f"supporting_cast[{i}]:missing:name")
            if not c.get("relation_to"):
                errors.append(f"supporting_cast[{i}]:missing:relation_to")
            rt = c.get("relation_type", "")
            lang = bible_language(bible)
            if not rt:
                errors.append(f"supporting_cast[{i}]:missing:relation_type")
            elif not relation_type_valid(rt, lang):
                errors.append(f"supporting_cast[{i}]:invalid:relation_type:{rt}")
            if "alive" not in c:
                errors.append(f"supporting_cast[{i}]:missing:alive")

    cm = bible.get("central_mystery")
    if not isinstance(cm, dict):
        errors.append("missing:central_mystery")
    else:
        _require(bible, "central_mystery.question", errors)
        ans = cm.get("answer")
        if ans is None or ans == "":
            errors.append("empty:central_mystery.answer")
        elif isinstance(ans, list):
            errors.append("central_mystery.answer:must_be_single_string")
        elif not isinstance(ans, str):
            errors.append("type:central_mystery.answer")
        rc = cm.get("reveal_chapter")
        if rc is None or not isinstance(rc, (int, float)) or int(rc) < 1:
            errors.append("invalid:central_mystery.reveal_chapter")

    bl = bible.get("bloodline")
    if not isinstance(bl, dict):
        errors.append("missing:bloodline")
    else:
        _require(bible, "bloodline.description", errors)
        rules = bl.get("hard_rules")
        if not isinstance(rules, list) or len(rules) < 1:
            errors.append("empty:bloodline.hard_rules")
        lr = str(bl.get("lead_relation", "")).strip().lower()
        if not lr:
            errors.append("empty:bloodline.lead_relation")
        elif lr in FORBIDDEN_LEAD_RELATIONS:
            errors.append(f"forbidden:bloodline.lead_relation:{lr}")

    wr = bible.get("world_rules")
    if not isinstance(wr, list) or len(wr) < 1:
        errors.append("empty:world_rules")

    if concept:
        errors.extend(_deferred_leak_lock_errors(bible, concept))
        errors.extend(_anti_romance_genre_errors(bible, concept))

    return errors


_LEAK_SECRET_LOCK_RE = re.compile(
    r"\bis the leak\b|\bthe leak who\b|\bbetrays?\b|\bmole who\b",
    re.I,
)
# Proper-name capture must stay case-sensitive — IGNORECASE would match
# ``network fractures`` as a fake two-token name.
_NAMED_BETRAY_IN_ARC_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b.{0,48}\bbetrays?\b|"
    r"\bwhen\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+betrays?\b",
)


def _concept_defers_leak(concept: dict) -> bool:
    blob = "\n".join(
        [
            str(concept.get("author_directive") or ""),
            str(concept.get("notes") or ""),
            "\n".join(str(x) for x in (concept.get("must_include") or [])),
        ]
    )
    return bool(
        re.search(
            r"decide\s+which.{0,80}plan|"
            r"decide.{0,40}at\s+plan\s*time|"
            r"leak.{0,120}decide\s+which|"
            r"THE LEAK:.{0,200}decide",
            blob,
            re.I | re.DOTALL,
        )
    )


def _deferred_leak_lock_errors(bible: dict, concept: dict) -> list[str]:
    if not _concept_defers_leak(concept):
        return []
    errors: list[str] = []
    for i, row in enumerate(bible.get("supporting_cast") or []):
        if not isinstance(row, dict):
            continue
        secret = str(row.get("secret") or "")
        if _LEAK_SECRET_LOCK_RE.search(secret):
            errors.append(
                f"supporting_cast[{i}]:premature_leak_lock:"
                f"{row.get('name') or i} — concept keeps leak open until plan"
            )
    for i, arc in enumerate(bible.get("series_arc") or []):
        if not isinstance(arc, dict):
            continue
        for key in ("thesis", "ending_hook"):
            text = str(arc.get(key) or "")
            if _NAMED_BETRAY_IN_ARC_RE.search(text):
                errors.append(
                    f"series_arc[{i}].{key}:named_betrayer_locked — "
                    "use 'a network member betrays' until plan decides"
                )
    return errors


def _anti_romance_genre_errors(bible: dict, concept: dict) -> list[str]:
    from factory.engine.lib.workspace_metadata import concept_forbids_romance

    if not concept_forbids_romance(concept):
        return []
    errors: list[str] = []
    genre = str((bible.get("meta") or {}).get("genre") or "").lower()
    niche = str(bible.get("sub_niche") or "").lower()
    if "romance" in genre:
        errors.append(f"meta.genre:romance_forbidden_for_concept:{genre}")
    if "romance" in niche:
        errors.append(f"sub_niche:romance_forbidden_for_concept:{niche}")
    return errors


def render_bible_block(
    bible: dict,
    *,
    lang: str = "vi",
    reveal_chapter: int | None = None,
    chapter: int | None = None,
) -> str:
    """Render character bible block for Writer prompts — đọc từ series.json.

    When ``chapter`` is before the designated reveal chapter, the full mystery
    answer is REDACTED so the writer cannot copy-spoil from the prompt.
    """
    f_lead = female_lead(bible)
    m_lead = male_lead(bible)
    fn, mn = f_lead.get("name", "?"), m_lead.get("name", "?")
    fa, ma = f_lead.get("age", "?"), m_lead.get("age", "?")

    if lang == "vi":
        heading = "## CHARACTER BIBLE — BẮT BUỘC"
        leads_heading = "### Nhân vật chính"
        cast_heading = "### Nhân vật phụ"
        blood_heading = "### Quan hệ & huyết thống (CANON — không được đổi)"
        mystery_heading = "### Bí ẩn trung tâm (chưa tiết lộ đầy đủ trước chương quy định)"
        rules_heading = "### Luật thế giới"
        voice_note = (
            f"> Nếu hai nhân vật chính cùng giọng, hoặc {fn} mềm yếu cầu xin, "
            f"hoặc {mn} nói dài giải thích — SAI bible."
        )
        alive_yes, alive_no = "còn sống", "đã mất"
        reveal_note = "Chỉ tiết lộ đầy đủ đáp án tại chương"
        answer_redacted = (
            "Đáp án canon: [REDACTED — chưa tới chương reveal. "
            "Không spoiler / không bịa đáp án.]"
        )
    else:
        heading = "## CHARACTER BIBLE — REQUIRED"
        leads_heading = "### Leads"
        cast_heading = "### Supporting cast"
        blood_heading = "### Relationships & bloodline (CANON — do not change)"
        mystery_heading = "### Central mystery (do not fully reveal before designated chapter)"
        rules_heading = "### World rules"
        voice_note = (
            f"> If both leads sound alike, or {fn} begs weakly, "
            f"or {mn} over-explains — bible violation."
        )
        alive_yes, alive_no = "alive", "deceased"
        reveal_note = "Full answer reveal only at chapter"
        answer_redacted = (
            "Canon answer: [REDACTED — before reveal chapter. "
            "Do not spoil or invent the answer.]"
        )

    cm = bible.get("central_mystery", {})
    reveal = reveal_chapter if reveal_chapter is not None else cm.get("reveal_chapter", "?")
    try:
        reveal_int = int(reveal)
    except (TypeError, ValueError):
        reveal_int = None
    redact = (
        chapter is not None
        and reveal_int is not None
        and int(chapter) < reveal_int
    )

    def _prompt_safe_internal(text: str) -> str:
        """Drop end-state arc wording from chapter prompts (planning-only)."""
        raw = str(text or "").strip()
        if not raw:
            return ""
        low = raw.lower()
        if any(
            m in low
            for m in (
                "finally ",
                "cuối cùng",
                "rejects the false",
                "rejecting the false",
                "fully resolves",
                "completely resolved",
            )
        ):
            return ""
        return raw

    def fmt_lead(lead: dict) -> str:
        from factory.engine.lib.canon_registry import is_absent_male_lead

        name = str(lead.get("name") or "").strip() or "?"
        if is_absent_male_lead(name):
            return (
                f"### {name}: no romantic male lead — do not invent one."
                if lang != "vi"
                else f"### {name}: không có male lead lãng mạn — cấm bịa."
            )
        age = lead.get("age", "")
        voice = str(lead.get("voice") or "").strip()
        tics = ", ".join(str(t) for t in (lead.get("tics") or []) if str(t).strip())
        boundary = str(lead.get("boundary") or "").strip()
        internal = (
            ""
            if redact
            else _prompt_safe_internal(str(lead.get("internal_voice") or ""))
        )
        bits: list[str] = []
        head = f"### {name}"
        if age not in ("", "?", None):
            head += f" ({age})"
        head += ":"
        bits.append(head)
        if voice:
            bits.append(voice)
        if tics:
            bits.append(f"{'Tật' if lang == 'vi' else 'Tics'}: {tics}.")
        if boundary:
            bits.append(f"{'Lằn ranh' if lang == 'vi' else 'Boundary'}: {boundary}.")
        if internal:
            bits.append(
                f"{'Nội tâm' if lang == 'vi' else 'Internal'}: {internal}."
            )
        if len(bits) == 1:
            bits.append("Use locked intent traits; do not invent a new personality.")
        return " ".join(bits)

    lines = [heading, "", leads_heading, fmt_lead(f_lead)]
    # Skip empty/absent male lead noise when book has no romantic ML
    from factory.engine.lib.canon_registry import is_absent_male_lead

    if not is_absent_male_lead(str(mn)):
        lines.append(fmt_lead(m_lead))
        lines.extend(["", voice_note])
    else:
        lines.append(fmt_lead(m_lead))
        lines.append("")

    cast = bible.get("supporting_cast", [])
    if cast:
        lines.extend(["", cast_heading])
        for c in cast:
            if not isinstance(c, dict):
                continue
            alive = alive_yes if c.get("alive", True) else alive_no
            secret = "" if redact else c.get("secret", "")
            sec_part = f" | {'Bí mật' if lang == 'vi' else 'Secret'}: {secret}" if secret else ""
            rel_type = str(c.get("relation_type") or "?").strip()
            rel_to = str(c.get("relation_to") or "").strip()
            if rel_to:
                rel_bit = (
                    f"{'quan hệ' if lang == 'vi' else 'role'}: {rel_type}; "
                    f"{'với' if lang == 'vi' else 'tied to'} {rel_to}"
                )
            else:
                rel_bit = f"{'quan hệ' if lang == 'vi' else 'role'}: {rel_type}"
            lines.append(f"- **{c.get('name', '?')}** — {rel_bit} ({alive}){sec_part}")

    bl = bible.get("bloodline", {})
    if bl:
        lines.extend(["", blood_heading, bl.get("description", "")])
        lines.append(f"- lead_relation: **{bl.get('lead_relation', '')}**")
        for rule in bl.get("hard_rules", []):
            lines.append(f"- {rule}")

    if cm:
        lines.extend(
            [
                "",
                mystery_heading,
                f"{'Câu hỏi' if lang == 'vi' else 'Question'}: {cm.get('question', '')}",
                f"{reveal_note} {reveal}.",
            ]
        )
        if redact:
            lines.append(answer_redacted)
        else:
            lines.append(
                f"{'Đáp án canon' if lang == 'vi' else 'Canon answer'} "
                f"(Writer/QC reference): {cm.get('answer', '')}"
            )

    # World rules live in LOCKED CANON (HARD). Pointer only — avoid duplicating soft copy.
    wr = bible.get("world_rules", [])
    if wr:
        lines.extend(
            [
                "",
                rules_heading,
                (
                    "(See LOCKED CANON — World rules HARD. Do not contradict.)"
                    if lang != "vi"
                    else "(Xem LOCKED CANON — Luật thế giới CỨNG. Không được trái.)"
                ),
            ]
        )

    return "\n".join(lines)


def bible_is_approved(bible: dict, direction: dict | None = None) -> bool:
    direction = direction or {}
    if direction.get("bible_status") == "approved":
        return True
    return bible.get("bible_status") == "approved"


def _plan_text_blob(plan: dict) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "one_line_summary",
        "beat_summary",
        "opens_with",
        "cliffhanger",
        "chapter_task",
        "signature_detail_hint",
        "spice_note",
        "carries_to_next",
    ):
        v = plan.get(key, "")
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v)
    for key in ("must_happen", "must_not"):
        v = plan.get(key, [])
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
    return " ".join(parts).lower()


_PROHIBITION_LINE_RE = re.compile(
    r"(?i)\b(?:do not|don't|never|without|must not|forbid(?:den)?|withhold|"
    r"no\s+(?:visual|ghost|apparition|male lead|romance|romantic))\b"
)


def _strip_prohibition_clauses(text: str) -> str:
    """Drop sentences that only forbid an action (avoid false positives on must_not)."""
    keep: list[str] = []
    for chunk in re.split(r"(?<=[.!;?\n])\s+", str(text or "")):
        s = chunk.strip()
        if not s:
            continue
        if _PROHIBITION_LINE_RE.search(s):
            continue
        keep.append(s)
    return " ".join(keep)


def _plan_affirmative_blob(plan: dict) -> str:
    """Plan text that asserts beats — excludes must_not and prohibition clauses."""
    parts: list[str] = []
    for key in (
        "title",
        "one_line_summary",
        "beat_summary",
        "opens_with",
        "cliffhanger",
        "chapter_task",
        "signature_detail_hint",
        "spice_note",
        "carries_to_next",
    ):
        v = plan.get(key, "")
        if isinstance(v, str):
            parts.append(_strip_prohibition_clauses(v))
        elif isinstance(v, list):
            parts.extend(_strip_prohibition_clauses(str(x)) for x in v)
    for item in plan.get("must_happen") or []:
        parts.append(_strip_prohibition_clauses(str(item)))
    # Intentionally omit must_not — "Do not reveal X" is not a reveal of X.
    return " ".join(p for p in parts if p).lower()


def _mystery_fact_match(
    fact: str,
    blob: str,
    bible: dict[str, Any],
) -> tuple[bool, int | None]:
    """Match one reveal fact without weakening the established seven-token bar."""
    fact_lower = str(fact or "").lower().strip()
    if not fact_lower:
        return False, None
    if len(fact_lower) > 20:
        snippet = fact_lower[: min(40, len(fact_lower))]
        if snippet in blob:
            return True, None

    name_stop = {
        str(female_lead(bible).get("name") or "").lower().split()[0]
        if female_lead(bible).get("name")
        else "",
        str(male_lead(bible).get("name") or "").lower().split()[0]
        if male_lead(bible).get("name")
        else "",
    }
    for cast_member in bible.get("supporting_cast", []) or []:
        if isinstance(cast_member, dict) and cast_member.get("name"):
            name_stop.update(str(cast_member["name"]).lower().split())
    stop = {
        "the", "and", "was", "were", "that", "with", "from", "her", "his",
        "she", "who", "had", "for", "are", "this", "they", "been", "have",
        "into", "only", "also", "while", "after", "before", "their", "them",
        "a", "an", "of", "to", "in", "on", "as", "by", "or", "it", "is",
        "name", "child", "children", "voice", "room", "hotel", "family",
        "summer", "years", "year", "said", "says", "including", "through",
    } | {name for name in name_stop if name}
    tokens = [
        token
        for token in re.findall(r"[a-zÀ-Ỹà-ỹ']{5,}", fact_lower)
        if token not in stop
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    fingerprint = unique[:16]
    hits = sum(1 for token in fingerprint if token in blob)
    density = hits / max(1, len(fingerprint))
    # Seven shared nouns can still join two different evidence beats. Require
    # the cluster to cover most of this specific reveal fact as well.
    return hits >= 7 and density >= 0.60, hits


def mystery_reveal_timing_issues(
    plan: dict[str, Any],
    bible: dict[str, Any],
    *,
    ledger: dict[str, Any] | None = None,
) -> list[str]:
    """Validate plan prose only against reveal facts still hidden this chapter."""
    from factory.engine.lib.narrative_compiler import (
        hidden_reveal_facts_at_chapter,
    )

    chapter = int(plan.get("chapter") or 0)
    central = bible.get("central_mystery") or {}
    answer = str(central.get("answer") or "").strip()
    reveal_chapter = int(central.get("reveal_chapter") or 0)
    if not answer:
        return []

    timeline = hidden_reveal_facts_at_chapter(
        ledger or {},
        chapter,
        fallback_answer=answer,
        fallback_reveal_chapter=reveal_chapter,
    )
    blob = _plan_affirmative_blob(plan)
    issues: list[str] = []
    for fact in timeline["hidden"]:
        matched, hits = _mystery_fact_match(str(fact.get("text") or ""), blob, bible)
        if not matched:
            continue
        suffix = "" if hits is None else f":token_hits_{hits}"
        issues.append(
            f"ch{chapter}:canon:mystery_reveal_too_early:"
            f"{fact.get('id')}:before_ch{int(fact.get('chapter') or reveal_chapter)}"
            f"{suffix}"
        )

    # Unmapped summary prose stays hidden until the canonical chapter. A match
    # fails loudly instead of silently assuming that the fragment is already open.
    for fact in timeline["unmapped"]:
        fact_chapter = int(fact.get("chapter") or reveal_chapter)
        if fact_chapter <= chapter or not fact.get("text"):
            continue
        matched, hits = _mystery_fact_match(str(fact["text"]), blob, bible)
        if not matched:
            continue
        suffix = "" if hits is None else f":token_hits_{hits}"
        issues.append(
            f"ch{chapter}:canon:mystery_answer_fragment_unmapped:"
            f"{fact.get('id')}:before_ch{fact_chapter}{suffix}"
        )

    if timeline["hidden"]:
        next_hidden_chapter = min(int(fact["chapter"]) for fact in timeline["hidden"])
        for negation in (r"không phải", r"thực ra là", r"sự thật là"):
            question = str(central.get("question") or "").lower()[:15]
            if re.search(negation, blob) and question and question in blob:
                issues.append(
                    f"ch{chapter}:canon:mystery_alternate_reveal:"
                    f"before_ch{next_hidden_chapter}"
                )
    return issues


def _both_leads_near(text: str, name_a: str, name_b: str, window: int = 80) -> bool:
    if not name_a or not name_b:
        return False
    ta = text.lower()
    na, nb = name_a.lower(), name_b.lower()
    for m in re.finditer(re.escape(nb), ta):
        start, end = max(0, m.start() - window), min(len(ta), m.end() + window)
        chunk = ta[start:end]
        if na in chunk:
            return True
    return False


def validate_plan_against_canon(
    plan: dict,
    bible: dict,
    *,
    all_plans: list[dict] | None = None,
    ledger: dict[str, Any] | None = None,
) -> list[str]:
    """QC canon từ bible — không hardcode tên cuốn."""
    issues: list[str] = []
    ch = plan.get("chapter", 0)
    blob = _plan_text_blob(plan)
    fn, mn = lead_names(bible)
    if not fn or not mn:
        return [f"ch{ch}:canon:missing_lead_names_in_bible"]

    # 1. Bloodline guard
    for pat in BLOOD_KINSHIP_PHRASES:
        if re.search(pat, blob, re.I) and _both_leads_near(blob, fn, mn):
            issues.append(f"ch{ch}:canon:bloodline_implied_between_leads:{pat}")

    lr = str(bible.get("bloodline", {}).get("lead_relation", "")).lower()
    if lr in FORBIDDEN_LEAD_RELATIONS:
        issues.append(f"ch{ch}:canon:bible_lead_relation_forbidden:{lr}")

    # 2. Identity consistency vs bible
    cast = bible.get("supporting_cast", [])
    for c in cast:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        canon_rt = str(c.get("relation_type", "")).strip()
        if not name or not canon_rt:
            continue
        if name.lower() not in blob:
            continue
        for alias, normalized in RELATION_TYPE_ALIASES.items():
            if alias in blob and normalized != canon_rt:
                # only flag if this alias is near the character name
                if _both_leads_near(blob.replace(mn, name), name, alias, window=40) or (
                    name.lower() in blob and alias in blob
                ):
                    if normalized != canon_rt:
                        issues.append(
                            f"ch{ch}:canon:identity_mismatch:{name}:plan_says_{normalized}_bible_{canon_rt}"
                        )

    # Cross-chapter identity tracking
    if all_plans:
        relation_claims: dict[str, set[str]] = {}
        for p in all_plans:
            pc = p.get("chapter", 0)
            if pc > ch:
                continue
            pb = _plan_text_blob(p)
            for c in cast:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name", "")).strip()
                if not name or name.lower() not in pb:
                    continue
                for alias, normalized in RELATION_TYPE_ALIASES.items():
                    if alias in pb and name.lower() in pb:
                        relation_claims.setdefault(name, set()).add(normalized)
        for name, types in relation_claims.items():
            if len(types) > 1:
                issues.append(f"ch{ch}:canon:identity_drift_across_plans:{name}:{sorted(types)}")

    # 3 & 4. Mystery single-version + chapter-scoped reveal timing.
    issues.extend(mystery_reveal_timing_issues(plan, bible, ledger=ledger))

    issues.extend(validate_plan_world_rules(plan, bible))
    return issues


_AUDIO_ONLY_RULE_RE = re.compile(
    r"only through recorded|never appears visually|never\s+(?:appears?|speaks?).{0,40}live|"
    r"manifests?\s+only\s+through|no\s+visual\s+(?:ghost|apparition|manifest)",
    re.IGNORECASE,
)

# Affirmative physical/live manifestation — not "do not appear visually".
_PHYSICAL_MANIFEST_PATTERNS = (
    r"\b(?:ghost|spirit|apparition|dead (?:girl|child|twin)|della)\b.{0,40}\b"
    r"(?:hand on|touches?|appears? (?:beside|before|behind|visually)|stands? beside)\b",
    r"\b(?:hand on (?:her |his )?(?:shoulder|arm|wrist|back))\b.{0,30}\b"
    r"(?:ghost|spirit|apparition|cold|no one (?:is|was) there)\b",
    r"\bphysical (?:apparition|manifest(?:ation)?)\b",
    r"\b(?:child(?:'s)?|girl(?:'s)?|ghost(?:'s)?)\s+(?:hand|fingers)\s+"
    r"(?:on|touch(?:es|ing)?|grip(?:s|ped)?)\b",
    r"\bspeaks?\s+(?:beside her|from the (?:empty )?room|from the dark)\b",
    r"\blive (?:voice|speech)\s+(?:not on|outside|without)\s+(?:the\s+)?(?:tape|recording)\b",
    r"\bvisual (?:apparition|ghost)\b",
)


def validate_plan_world_rules(plan: dict, bible: dict) -> list[str]:
    """Hard heuristics from bible.world_rules — fail plan beats that contradict them."""
    issues: list[str] = []
    ch = plan.get("chapter", 0)
    rules = [str(r) for r in (bible.get("world_rules") or []) if str(r).strip()]
    if not rules:
        return issues
    blob = _plan_affirmative_blob(plan)
    audio_only = any(_AUDIO_ONLY_RULE_RE.search(r) for r in rules)
    if audio_only:
        for pat in _PHYSICAL_MANIFEST_PATTERNS:
            if re.search(pat, blob, re.IGNORECASE):
                issues.append(f"ch{ch}:world_rule:audio_only_manifestation_violated")
                break
    return issues
