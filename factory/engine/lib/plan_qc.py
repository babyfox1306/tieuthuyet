"""QC chapter_plans trước khi render prompts — ép kỹ thuật ở tầng PLAN."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from factory.engine.lib.language import language_profile, target_language, word_count_patch
from factory.engine.lib.plan_normalize import (
    coerce_text_field,
    coerce_text_list,
    normalize_chapter_plan,
    validate_duplicate_beats,
    validate_plan_language,
)
from factory.engine.lib.narrative_compiler import (
    iter_must_not_know_before,
    load_knowledge_matrix,
    load_ledger,
    min_clues_for_reveal,
    narrative_compiler_enabled,
)
from factory.engine.lib.prompt_builder import spice_for_chapter

import yaml

# Mở cảnh = FAIL (mâu thuẫn rule Writer)
SCENE_OPEN_PATTERNS = [
    r"bước vào",
    r"đứng trước",
    r"ngỡ ngàng",
    r"ngần ngại",
    r"văn phòng sang",
    r"mùi hương",
    r"ánh nắng",
    r"không khí",
    r"cánh cổng",
]

GENERIC_SIGNATURE = ["nhẫn", "xe sang", "đồng hồ", "kim cương", "biệt thự lớn"]

REQUIRED_FIELDS = [
    "chapter",
    "title",
    "slug",
    "one_line_summary",
    "beat_summary",
    "must_happen",
    "must_not",
    "opens_with",
    "cliffhanger",
    "signature_detail_hint",
    "spice",
    "chapter_task",
]

# Locked chapter plans live in workspace bible/locked_chapter_plans.json (data, not code).


def chapter_plan_structurally_complete(plan: dict) -> bool:
    """True when required planning fields are present (QC structural bar).

    Used by resume/merge so half-broken chapter objects are never treated as done
    and never overwrite a complete chapter.
    """
    plan = normalize_chapter_plan(plan)
    for field in REQUIRED_FIELDS:
        if field not in plan or plan[field] in (None, "", []):
            return False
    mh = plan.get("must_happen", [])
    if not isinstance(mh, list) or len(mh) < 3:
        return False
    if len(str(plan.get("cliffhanger") or "")) < 15:
        return False
    return True


def prefer_richer_chapter_plan(existing: dict | None, incoming: dict) -> dict:
    """Merge chapter plans without downgrading a structurally complete chapter."""
    incoming = normalize_chapter_plan(incoming)
    if not existing:
        return incoming
    existing = normalize_chapter_plan(existing)
    e_ok = chapter_plan_structurally_complete(existing)
    n_ok = chapter_plan_structurally_complete(incoming)
    if e_ok and not n_ok:
        return existing
    if n_ok:
        return incoming
    # Both incomplete: keep non-empty fields from whichever side has them.
    out = dict(existing)
    for key, val in incoming.items():
        if val in (None, "", []):
            continue
        cur = out.get(key)
        if cur in (None, "", []):
            out[key] = val
            continue
        if key in ("must_happen", "must_not") and isinstance(val, list) and isinstance(cur, list):
            if len(val) > len(cur):
                out[key] = val
            continue
        if isinstance(val, str) and isinstance(cur, str) and len(val.strip()) > len(cur.strip()):
            out[key] = val
    return normalize_chapter_plan(out)


def _has_romance_micro_beat(plan: dict) -> bool:
    mh = plan.get("must_happen", [])
    if isinstance(mh, list):
        for item in mh:
            if str(item).strip().upper().startswith("[ROMANCE]"):
                return True
    combined = " ".join(
        str(plan.get(k, "")) for k in ("beat_summary", "chapter_task", "one_line_summary")
    ).upper()
    return "[ROMANCE]" in combined


def _ledger_clue_index(ledger: dict[str, Any]) -> dict[str, dict]:
    return {
        str(c["id"]): c
        for c in (ledger.get("clues") or [])
        if isinstance(c, dict) and c.get("id")
    }


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


def _plan_narrative_blob(plan: dict) -> str:
    parts = [
        str(plan.get(k, ""))
        for k in (
            "title",
            "one_line_summary",
            "beat_summary",
            "must_happen",
            "opens_with",
            "cliffhanger",
        )
    ]
    # Omit must_not — "Do not reveal X" is not knowing/stating X.
    narr = plan.get("narrative") if isinstance(plan.get("narrative"), dict) else {}
    for rev in narr.get("reveals") or []:
        if isinstance(rev, dict):
            parts.append(str(rev.get("reveal", "")))
        else:
            parts.append(str(rev))
    return " ".join(parts).lower()


_CLUE_STOPWORDS = frozenset(
    {
        "that",
        "with",
        "from",
        "this",
        "her",
        "his",
        "the",
        "and",
        "for",
        "she",
        "has",
        "have",
        "been",
        "into",
        "about",
        "when",
        "what",
        "their",
        "them",
        "than",
        "only",
        "just",
        "more",
        "some",
        "very",
        "also",
        "does",
        "not",
    }
)


def _plan_beat_blob(plan: dict) -> str:
    parts: list[str] = []
    mh = plan.get("must_happen", [])
    if isinstance(mh, list):
        parts.extend(str(x) for x in mh)
    else:
        parts.append(str(mh))
    parts.append(str(plan.get("beat_summary", "")))
    parts.append(str(plan.get("chapter_task", "")))
    return " ".join(parts).lower()


def _significant_words(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z]{4,}", text.lower())
        if w not in _CLUE_STOPWORDS
    ]


def _clue_hint_in_beats(hint: str, beat_blob: str) -> bool:
    hint_l = hint.lower().strip()
    if not hint_l:
        return False
    if len(hint_l) >= 12 and hint_l[: min(36, len(hint_l))] in beat_blob:
        return True
    words = _significant_words(hint_l)
    if not words:
        return hint_l in beat_blob
    hits = sum(1 for w in words[:8] if w in beat_blob)
    return hits >= 2


def _clue_reflected_in_beats(
    cid: str,
    clue_beats: dict,
    clues_idx: dict[str, dict],
    beat_blob: str,
) -> bool:
    if cid.lower() in beat_blob:
        return True
    hint = str(clue_beats.get(cid) or clues_idx.get(cid, {}).get("content") or "")
    return _clue_hint_in_beats(hint, beat_blob)


def _clue_planted_before(all_plans: list[dict], clue_id: str, before_ch: int) -> bool:
    """True if clue appears in clues_plant of any chapter strictly before ``before_ch``."""
    for p in all_plans:
        ch = int(p.get("chapter") or 0)
        if ch >= before_ch:
            continue
        planted = (p.get("narrative") or {}).get("clues_plant") or []
        if clue_id in planted:
            return True
    return False


def _clue_planted_by(all_plans: list[dict], clue_id: str, by_ch: int) -> bool:
    """True if clue is planted in any chapter at or before ``by_ch`` (same-chapter OK)."""
    for p in all_plans:
        ch = int(p.get("chapter") or 0)
        if ch > by_ch:
            continue
        planted = (p.get("narrative") or {}).get("clues_plant") or []
        if clue_id in planted:
            return True
    return False


def _clue_planted_at_or_before(
    all_plans: list[dict],
    clue_id: str,
    ledger: dict[str, Any],
    payoff_ch: int,
) -> bool:
    clues = _ledger_clue_index(ledger)
    meta = clues.get(clue_id, {})
    plant_ch = int(meta.get("plant_chapter") or 0)
    if plant_ch <= 0:
        return False
    if plant_ch > payoff_ch:
        return False
    for p in all_plans:
        ch = int(p.get("chapter") or 0)
        if ch != plant_ch:
            continue
        if clue_id in ((p.get("narrative") or {}).get("clues_plant") or []):
            return True
    return False


def _forbidden_knowledge_at(matrix: dict[str, Any], chapter: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for char_name, data in (matrix.get("characters") or {}).items():
        if not isinstance(data, dict):
            continue
        for fact, before_ch in iter_must_not_know_before(data):
            if int(before_ch) > chapter:
                out.append((str(char_name), str(fact)))
    return out


def _fact_appears_in_text(fact: str, text: str) -> bool:
    fact_l = fact.lower().strip()
    if len(fact_l) < 8:
        return fact_l in text
    # Long facts: match a distinctive substring (first 40 chars or full if shorter)
    needle = fact_l[: min(40, len(fact_l))]
    return needle in text


def validate_narrative_plan(
    plan: dict,
    ws: Path,
    *,
    all_plans: list[dict] | None = None,
    ledger: dict[str, Any] | None = None,
    matrix: dict[str, Any] | None = None,
) -> list[str]:
    """NC-01..NC-07 — only when narrative compiler enabled; skip locked plans."""
    if not narrative_compiler_enabled(ws):
        return []
    if plan.get("locked"):
        return []

    ch = int(plan.get("chapter") or 0)
    if ch <= 0:
        return []

    ledger = ledger if ledger is not None else load_ledger(ws)
    matrix = matrix if matrix is not None else load_knowledge_matrix(ws)
    all_plans = all_plans or []
    narr = plan.get("narrative")
    if not isinstance(narr, dict):
        return [f"ch{ch}:missing:narrative"]

    issues: list[str] = []
    clues_idx = _ledger_clue_index(ledger)
    plant_scheduled = {cid for cid, c in clues_idx.items() if int(c.get("plant_chapter") or 0) == ch}
    payoff_scheduled = {cid for cid, c in clues_idx.items() if int(c.get("payoff_chapter") or 0) == ch}
    actual_plant = set(narr.get("clues_plant") or [])
    actual_payoff = set(narr.get("clues_payoff") or [])

    # NC-01
    for cid in plant_scheduled:
        if cid not in actual_plant:
            issues.append(f"ch{ch}:NC-01:clue_not_scheduled:{cid}")

    # NC-02
    for cid in payoff_scheduled:
        if cid not in actual_payoff:
            issues.append(f"ch{ch}:NC-02:payoff_not_scheduled:{cid}")

    # NC-03
    for cid in actual_payoff:
        meta = clues_idx.get(cid, {})
        plant_ch = int(meta.get("plant_chapter") or 0)
        pay_ch = int(meta.get("payoff_chapter") or 0)
        if plant_ch and pay_ch and pay_ch < plant_ch:
            issues.append(f"ch{ch}:NC-03:payoff_before_plant:{cid}")
        elif not _clue_planted_at_or_before(all_plans, cid, ledger, ch):
            issues.append(f"ch{ch}:NC-03:payoff_unplanted:{cid}")

    # NC-04 / NC-05 — every major_reveal at this chapter
    plan_reveal_ids = set()
    for rev in narr.get("reveals") or []:
        if isinstance(rev, dict):
            plan_reveal_ids.add(str(rev.get("id", "")))
        else:
            plan_reveal_ids.add(str(rev))

    for rev in ledger.get("major_reveals") or []:
        if not isinstance(rev, dict):
            continue
        if int(rev.get("chapter") or 0) != ch:
            continue
        rid = str(rev.get("id", ""))
        if rid and rid not in plan_reveal_ids:
            issues.append(f"ch{ch}:NC-04:reveal_not_scheduled:{rid}")
        required = [str(x) for x in (rev.get("required_clues") or []) if str(x).strip()]
        # Only real clue IDs count — reveal IDs mistakenly listed as clues are ignored here
        # (ledger schema validate flags them separately).
        required = [cid for cid in required if cid in clues_idx]
        weight = str(rev.get("reveal_weight") or "major").lower()
        min_clues = min_clues_for_reveal(weight)
        needed = min(min_clues, len(required)) if required else min_clues
        planted_count = 0
        for cid in required:
            # Same-chapter plant+reveal is allowed (ledger often schedules both on one ch).
            if not _clue_planted_by(all_plans, cid, ch):
                issues.append(f"ch{ch}:NC-04:reveal_missing_plant:{rid}:{cid}")
            else:
                planted_count += 1
        if required and planted_count < needed:
            issues.append(
                f"ch{ch}:NC-05:reveal_insufficient_clues:{rid}:{planted_count}<{needed}"
            )
        elif not required and min_clues > 0:
            # Major/minor reveal with empty required_clues — still flag insufficient setup
            issues.append(
                f"ch{ch}:NC-05:reveal_insufficient_clues:{rid}:0<{min_clues}"
            )

    # NC-06 — knowledge gates in plan prose / reveals (affirmative only).
    blob = _strip_prohibition_clauses(_plan_narrative_blob(plan)).lower()
    for _char, fact in _forbidden_knowledge_at(matrix, ch):
        if _fact_appears_in_text(fact, blob):
            issues.append(f"ch{ch}:NC-06:knowledge_violation:{fact[:48]}")

    # NC-07 — clue plant/payoff must appear in story beats (must_happen / beat_summary)
    beat_blob = _plan_beat_blob(plan)
    clue_beats = narr.get("clue_beats") or {}
    for cid in actual_plant:
        if not _clue_reflected_in_beats(cid, clue_beats, clues_idx, beat_blob):
            issues.append(f"ch{ch}:NC-07:clue_not_in_beats:{cid}")
    for cid in actual_payoff:
        if not _clue_reflected_in_beats(cid, clue_beats, clues_idx, beat_blob):
            issues.append(f"ch{ch}:NC-07:payoff_not_in_beats:{cid}")

    return issues


def _reveal_id(rev: Any) -> str:
    if isinstance(rev, dict):
        return str(rev.get("id") or "").strip()
    return str(rev or "").strip()


def _thread_resolved_chapter(thread: dict[str, Any]) -> int:
    """Close chapter for a thread — prefer resolved_chapter, else must_close_by when closed."""
    for key in ("resolved_chapter", "payoff_chapter"):
        raw = thread.get(key)
        if raw is not None and str(raw).strip() != "":
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    status = str(thread.get("status") or "").lower()
    if status in {"closed", "resolved", "paid_off", "complete"}:
        raw = thread.get("must_close_by")
        if raw is not None and str(raw).strip() != "":
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0
    return 0


def validate_payoff_uniqueness(
    plans: list[dict],
    ws: Path | None = None,
) -> dict[int, list[str]]:
    """NC-09 — each reveal/clue pays off once; closed threads cannot re-payoff.

    Note: prompt C called this NC-07:reveal_payoff_duplicate, but NC-07 already
    means clue_not_in_beats — use NC-09 to avoid colliding subtypes.
    """
    if ws is not None and not narrative_compiler_enabled(ws):
        return {}

    from collections import defaultdict

    reveal_chs: dict[str, list[int]] = defaultdict(list)
    clue_pay_chs: dict[str, list[int]] = defaultdict(list)
    thread_pay_chs: dict[str, list[int]] = defaultdict(list)
    thread_touch_chs: dict[str, list[int]] = defaultdict(list)

    for plan in plans:
        if plan.get("locked"):
            continue
        ch = int(plan.get("chapter") or 0)
        if ch <= 0:
            continue
        narr = plan.get("narrative")
        if not isinstance(narr, dict):
            continue
        for rev in narr.get("reveals") or []:
            rid = _reveal_id(rev)
            if rid:
                reveal_chs[rid].append(ch)
        for cid in narr.get("clues_payoff") or []:
            key = str(cid).strip()
            if key:
                clue_pay_chs[key].append(ch)
        for tid in narr.get("threads_payoff") or []:
            key = str(tid).strip()
            if key:
                thread_pay_chs[key].append(ch)
        for tid in narr.get("threads_touch") or []:
            key = str(tid).strip()
            if key:
                thread_touch_chs[key].append(ch)

    out: dict[int, list[str]] = defaultdict(list)

    for rid, chs in reveal_chs.items():
        uniq = sorted(set(chs))
        if len(uniq) > 1:
            for ch in uniq[1:]:
                out[ch].append(
                    f"ch{ch}:NC-09:reveal_payoff_duplicate:{rid}:also_ch{uniq[0]}"
                )

    for cid, chs in clue_pay_chs.items():
        uniq = sorted(set(chs))
        if len(uniq) > 1:
            for ch in uniq[1:]:
                out[ch].append(
                    f"ch{ch}:NC-09:clue_payoff_duplicate:{cid}:also_ch{uniq[0]}"
                )

    if ws is not None:
        from factory.engine.lib.narrative_compiler import load_threads

        threads_data = load_threads(ws)
        for thread in threads_data.get("threads") or []:
            if not isinstance(thread, dict):
                continue
            tid = str(thread.get("id") or "").strip()
            if not tid:
                continue
            resolved = _thread_resolved_chapter(thread)
            if resolved <= 0:
                continue
            for ch in sorted(set(thread_pay_chs.get(tid) or [])):
                if ch > resolved:
                    out[ch].append(
                        f"ch{ch}:NC-09:thread_payoff_after_close:{tid}:closed_ch{resolved}"
                    )
            # threads_touch after close is also a re-payoff signal when no
            # dedicated threads_payoff field is used.
            if not (thread_pay_chs.get(tid) or []):
                for ch in sorted(set(thread_touch_chs.get(tid) or [])):
                    if ch > resolved:
                        out[ch].append(
                            f"ch{ch}:NC-09:thread_payoff_after_close:{tid}:closed_ch{resolved}"
                        )

    return {ch: issues for ch, issues in out.items() if issues}


def _male_lead_absent(bible: dict | None, ws: Path | None) -> bool:
    from factory.engine.lib.canon_registry import is_absent_male_lead

    if bible:
        from factory.engine.lib.bible_schema import lead_names

        _fn, mn = lead_names(bible)
        if is_absent_male_lead(mn):
            return True
    if ws is not None:
        from factory.engine.lib.canon_registry import canon_registry_path

        reg_path = canon_registry_path(ws)
        if reg_path.exists():
            try:
                decl = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
                male_decl = ((decl.get("characters") or {}).get("male_lead") or {})
                if is_absent_male_lead(str(male_decl.get("canonical") or "")):
                    return True
            except (yaml.YAMLError, OSError, TypeError):
                pass
    return False


def _plan_pov_issues(plan: dict, direction: dict, *, ws: Path | None = None) -> list[str]:
    """Fail plan fields written in first person when POV is third-person limited."""
    from factory.engine.lib.canon_prose_qc import count_first_person_outside_dialogue

    pov = str(direction.get("pov_mode") or "").strip().lower().replace("-", "_")
    if ws is not None:
        from factory.engine.lib.canon_registry import canon_registry_path

        reg_path = canon_registry_path(ws)
        if reg_path.exists():
            try:
                decl = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
                pov = str(decl.get("pov_mode") or pov).strip().lower().replace("-", "_")
            except (yaml.YAMLError, OSError, TypeError):
                pass
    if not pov:
        pov = "third_person_limited"
    if "first" in pov:
        return []

    ch = plan.get("chapter", 0)
    issues: list[str] = []
    # opens/cliff: any first-person hit fails; longer prose fields use threshold 2.
    for field, thresh in (
        ("opens_with", 1),
        ("cliffhanger", 1),
        ("chapter_task", 2),
        ("beat_summary", 2),
        ("one_line_summary", 2),
    ):
        text = str(plan.get(field) or "")
        if not text.strip():
            continue
        n = count_first_person_outside_dialogue(text)
        if n >= thresh:
            issues.append(f"ch{ch}:pov_first_person_in_plan:{field}:{n}")
    return issues


_ROMANCE_WHEN_ABSENT_RE = re.compile(
    r"\blove interest\b|"
    r"\battraction\b|"
    r"\bcaretaker\b.{0,40}\b(?:warmth|touch|hand|glance|fingers|romance)\b|"
    r"\bfingers brush\b|"
    r"\blingering glance\b|"
    r"\bflirt(?:ation|ing)?\b|"
    r"\bromantic (?:subplot|tension|counterpart|figure)\b",
    re.IGNORECASE,
)

_ROMANCE_EXPLICITLY_ABSENT_RE = re.compile(
    r"not applicable|n/?a\b|none\b|no romantic|no romance|no male lead|"
    r"forbids? a (?:love interest|romantic)|male lead (?:is )?absent|"
    r"redirected into|"
    r"\bisolat(?:ion|ed)\b|"
    r"\babsence\b|"
    r"\bno (?:rescuer|lover|witness|partner|ally)\b|"
    r"\bempty (?:room|chair|hotel)\b|"
    r"\balone\b|"
    r"\bnot a (?:person|lover|rescue)\b|"
    r"\[ISOLATION\]",
    re.IGNORECASE,
)

# Concept/direction signals that romance is forbidden (horror, antagonist-only ML, …).
_ROMANCE_FORBIDDEN_RE = re.compile(
    r"\bno romance\b|"
    r"\bromance of any kind\b|"
    r"\bnot a (?:love interest|romance)\b|"
    r"\bno love interest\b|"
    r"\bforbids? romance\b|"
    r"\bwithout romance\b|"
    r"\bno attraction\b|"
    r"\bnot a romance\b|"
    r"\bno romance line\b",
    re.IGNORECASE,
)

# must_avoid entries that ban romance as a category (not "bad romance trope" notes).
_MUST_AVOID_FORBIDS_ROMANCE_RE = re.compile(
    r"^(?:no\s+)?romance(?:\s+of\s+any\s+kind)?\.?$|"
    r"romance of any kind|"
    r"^no (?:romance|love interest|romantic(?:\s+subplot)?)\b|"
    r"^any romance\b|"
    r"^romantic (?:subplot|relationship|arc|line)\b|"
    r"^love interest\b",
    re.IGNORECASE,
)

# Opt-in: workspace wants romance-thriller micro-beats (ceo-contract / glass-meridian).
_ROMANCE_OPT_IN_RE = re.compile(
    r"\bromance[- ]?thriller\b|"
    r"\bwrite\b.{0,40}\bas a\b.{0,40}\bromance\b|"
    r"\bslow[- ]burn romance\b|"
    r"\bmarry first\b|"
    r"\blove interest\b|"
    r"\bromantic subplot\b|"
    r"\bforced proximity\b|"
    r"\bend[- ]of[- ]chapter hooks\b.{0,40}\bromance\b",
    re.IGNORECASE | re.DOTALL,
)


def _load_concept_for_qc(ws: Path | None) -> dict[str, Any]:
    if ws is None:
        return {}
    try:
        from factory.engine.lib.narrative_schema import load_concept

        return load_concept(ws) or {}
    except (OSError, TypeError, ValueError):
        return {}


def _concept_direction_blob(direction: dict, concept: dict) -> str:
    parts: list[str] = [
        str(direction.get("narrative_profile") or ""),
        str(direction.get("goal") or ""),
        str(direction.get("spice_badge") or ""),
        " ".join(str(t) for t in (direction.get("tropes") or [])),
        str(concept.get("author_directive") or ""),
        str(concept.get("notes") or ""),
        str(concept.get("logline") or ""),
        "\n".join(str(x) for x in (concept.get("must_avoid") or [])),
        "\n".join(str(x) for x in (concept.get("must_include") or [])),
    ]
    return "\n".join(parts)


def romance_forbidden(direction: dict, *, ws: Path | None = None) -> bool:
    """True when concept/direction forbids romance of any kind."""
    concept = _load_concept_for_qc(ws)
    for item in concept.get("must_avoid") or []:
        if _MUST_AVOID_FORBIDS_ROMANCE_RE.search(str(item).strip()):
            return True
    blob = _concept_direction_blob(direction, concept)
    if _ROMANCE_FORBIDDEN_RE.search(blob):
        return True
    # Antagonist-only male lead, explicitly not romantic.
    if re.search(
        r"\bNOT a love interest\b|"
        r"\bnot a love interest\b|"
        r"\bnever\b.{0,40}\battraction\b|"
        r"\bno attraction,\s*ever\b",
        blob,
        re.IGNORECASE | re.DOTALL,
    ):
        return True
    return False


def romance_microbeat_required(direction: dict, *, ws: Path | None = None) -> bool:
    """[ROMANCE] micro-beat is OPT-IN from concept/direction — never the default.

    Romance workspaces signal via narrative_profile / directive / tropes.
    Forbidden-romance or absent male lead → never required.
    """
    if romance_forbidden(direction, ws=ws):
        return False
    if _male_lead_absent(None, ws):
        return False

    concept = _load_concept_for_qc(ws)
    profile = str(direction.get("narrative_profile") or "").strip().lower()
    if "romance" in profile:
        return True

    for pool in (
        direction.get("tropes") or [],
        concept.get("must_include") or [],
    ):
        for item in pool:
            if "romance" in str(item).lower() or "slow burn" in str(item).lower():
                return True

    blob = _concept_direction_blob(direction, concept)
    if _ROMANCE_OPT_IN_RE.search(blob):
        return True
    return False


def _forbidden_romance_when_disabled(plan: dict) -> bool:
    """True when plan invents romance despite absent ML / romance-forbidden workspace."""
    for item in plan.get("must_happen") or []:
        s = str(item)
        upper = s.strip().upper()
        if upper.startswith("[ISOLATION]"):
            continue
        if not upper.startswith("[ROMANCE]"):
            continue
        # Isolation/absence beats often keep the [ROMANCE] tag for schema — allow them.
        if _ROMANCE_EXPLICITLY_ABSENT_RE.search(s):
            continue
        if re.search(
            r"\b(?:no male lead|no romantic|not romance|absence|alone|empty)\b",
            s,
            re.IGNORECASE,
        ):
            continue
        return True
    blob = " ".join(
        [
            str(plan.get("spice_note") or ""),
            str(plan.get("chapter_task") or ""),
            str(plan.get("beat_summary") or ""),
            str(plan.get("one_line_summary") or ""),
        ]
    )
    if _ROMANCE_EXPLICITLY_ABSENT_RE.search(blob):
        return False
    if _ROMANCE_WHEN_ABSENT_RE.search(blob):
        return True
    return False


# Back-compat alias for older call sites / tests.
_forbidden_romance_when_no_male_lead = _forbidden_romance_when_disabled


def validate_plan(
    plan: dict,
    direction: dict,
    *,
    bible: dict | None = None,
    all_plans: list[dict] | None = None,
    ws: Path | None = None,
) -> list[str]:
    """Trả list lỗi. Rỗng = pass."""
    plan = normalize_chapter_plan(plan)
    issues: list[str] = []
    ch = plan.get("chapter", 0)

    for field in REQUIRED_FIELDS:
        if field not in plan or plan[field] in (None, "", []):
            issues.append(f"ch{ch}:missing:{field}")

    opens = str(plan.get("opens_with", "")).lower()
    for pat in SCENE_OPEN_PATTERNS:
        if re.search(pat, opens):
            issues.append(f"ch{ch}:opens_scene:{pat}")

    task = str(plan.get("chapter_task", "")).lower()
    if "1250" not in task and "1500" not in task and "1600" not in task and "1700" not in task:
        issues.append(f"ch{ch}:task_no_word_target")

    mh = plan.get("must_happen", [])
    if not isinstance(mh, list) or len(mh) < 3:
        issues.append(f"ch{ch}:must_happen_lt3")

    spice = plan.get("spice", 1)
    expected = spice_for_chapter(direction, ch)
    if spice != expected and not plan.get("locked"):
        issues.append(f"ch{ch}:spice_mismatch:{spice}!={expected}")

    if spice == 3:
        if "chưa vượt" in task or "không vượt" in task:
            issues.append(f"ch{ch}:spice3_but_task_no_explicit")
        note = str(plan.get("spice_note", ""))
        if len(note) < 20:
            issues.append(f"ch{ch}:spice3_note_too_short")

    sig = str(plan.get("signature_detail_hint", "")).lower()
    if any(g in sig for g in GENERIC_SIGNATURE):
        issues.append(f"ch{ch}:signature_generic")

    cliff = str(plan.get("cliffhanger", ""))
    if len(cliff) < 15:
        issues.append(f"ch{ch}:cliffhanger_weak")

    male_absent = _male_lead_absent(bible, ws)
    romance_off = romance_forbidden(direction, ws=ws) or male_absent
    if romance_off:
        if _forbidden_romance_when_disabled(plan):
            code = (
                "forbidden_romance_when_no_male_lead"
                if male_absent
                else "forbidden_romance_when_concept_forbids"
            )
            issues.append(f"ch{ch}:{code}")
    elif romance_microbeat_required(direction, ws=ws):
        if not plan.get("locked") and not _has_romance_micro_beat(plan):
            issues.append(f"ch{ch}:missing_romance_micro_beat")

    issues.extend(_plan_pov_issues(plan, direction, ws=ws))

    if bible:
        from factory.engine.lib.bible_schema import validate_plan_against_canon

        issues.extend(validate_plan_against_canon(plan, bible, all_plans=all_plans))

    lang = target_language(direction)
    issues.extend(validate_plan_language(plan, lang))
    if all_plans:
        issues.extend(validate_duplicate_beats(plan, all_plans))

    if ws is not None:
        issues.extend(
            validate_narrative_plan(plan, ws, all_plans=all_plans or [])
        )

    return issues


def validate_all_plans(
    plans: list[dict],
    direction: dict,
    *,
    bible: dict | None = None,
    ws: Path | None = None,
) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for p in plans:
        ch = p.get("chapter", 0)
        issues = validate_plan(p, direction, bible=bible, all_plans=plans, ws=ws)
        if issues:
            out[ch] = issues
    for ch, issues in validate_payoff_uniqueness(plans, ws=ws).items():
        out.setdefault(ch, []).extend(issues)
    return out


def apply_canon_plans(plans: list[dict], locked: list[dict]) -> list[dict]:
    from factory.engine.lib.plan_normalize import normalize_chapter_plan

    by_ch = {p["chapter"]: normalize_chapter_plan(p) for p in plans}
    for canon in locked:
        by_ch[canon["chapter"]] = normalize_chapter_plan(dict(canon))
    return [by_ch[k] for k in sorted(by_ch)]


def ensure_task_word_count(plan: dict, direction: dict | None = None, cfg: dict | None = None) -> dict:
    """Patch nhẹ nếu thiếu mục tiêu chữ."""
    task = plan.get("chapter_task", "")
    patch = word_count_patch(language_profile(direction=direction, cfg=cfg))
    if "1250" not in task and "1500" not in task and "1600" not in task and "chữ" not in task.lower() and "word" not in task.lower():
        plan = dict(plan)
        plan["chapter_task"] = task.rstrip(".") + ". " + patch
    return plan


def apply_deterministic_plan_fixes(plan: dict, direction: dict) -> dict:
    """Local fixes that must not require LLM (spice, slug, signature, word-count)."""
    plan = ensure_task_word_count(normalize_chapter_plan(plan), direction)
    if plan.get("locked"):
        return plan
    ch = int(plan.get("chapter") or 0)
    expected = spice_for_chapter(direction, ch)
    try:
        cur = int(plan.get("spice"))
    except (TypeError, ValueError):
        cur = -999
    changed = False
    if cur != expected:
        plan = dict(plan)
        plan["spice"] = expected
        changed = True
    if not str(plan.get("signature_detail_hint") or "").strip():
        # Derive a concrete sensory hint from existing plan fields — never block approve
        # solely because the outliner omitted signature_detail_hint.
        for key in ("opens_with", "cliffhanger", "one_line_summary", "beat_summary"):
            candidate = str(plan.get(key) or "").strip()
            if len(candidate) >= 20:
                if not changed:
                    plan = dict(plan)
                plan["signature_detail_hint"] = candidate[:240]
                changed = True
                break
        else:
            if not changed:
                plan = dict(plan)
            plan["signature_detail_hint"] = (
                f"A concrete sensory detail unique to chapter {ch} "
                f"that only this scene could contain."
            )
    return plan
