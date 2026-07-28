"""Python fidelity gates for the sequential locked chain (G0–G4)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from factory.engine.lib.intent_manifest import (
    PLACEHOLDER_LEADS,
    chapter_entry,
    concept_digest,
    load_intent_manifest,
    must_include_for_chapter,
    validate_manifest,
)
from factory.engine.lib.narrative_schema import load_concept, narrative_dir
from factory.engine.lib.prompt_builder import load_direction

_WORD_RE = re.compile(r"[a-zA-Zà-ỹÀ-Ỹ0-9']{4,}")


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")}


def _coverage_ratio(required: str, haystack: str) -> float:
    req = _tokens(required)
    if not req:
        return 1.0
    have = _tokens(haystack)
    if not have:
        return 0.0
    hit = len(req & have)
    return hit / max(1, len(req))


def seal_plans_to_intent(
    ws: Path,
    plans: list[dict],
    *,
    book: int | None = None,
) -> tuple[list[dict], list[str]]:
    """Project each approved chapter-map beat into its plan deterministically.

    The chapter map is the primary story lock.  An Outliner/fixer may elaborate
    it, but may not silently replace it with a different event.  When lexical
    coverage is weak, append the exact compiler-owned beat to ``must_happen``;
    this gives the Writer an executable canonical instruction and keeps G3 from
    depending on model paraphrase quality.
    """
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    manifest = load_intent_manifest(ws, book_num)
    if not manifest or manifest.get("status") != "approved":
        return plans, []

    beats = {
        int(entry.get("chapter") or 0): str(entry.get("beat") or "").strip()
        for entry in (manifest.get("chapter_map") or [])
        if int(entry.get("chapter") or 0) > 0
    }
    out: list[dict] = []
    notes: list[str] = []
    for original in plans:
        plan = dict(original)
        ch = int(plan.get("chapter") or 0)
        beat = beats.get(ch, "")
        if plan.get("locked") or not beat:
            out.append(plan)
            continue
        must_happen = [str(x) for x in (plan.get("must_happen") or [])]
        blob = " ".join(must_happen)
        # Use the stricter whole-plan G3 threshold.  The exact canonical line
        # then satisfies both chapter_map_not_covered (0.28) and
        # must_happen_betrays_map (0.22).
        if _coverage_ratio(beat, blob) < 0.28:
            must_happen.append(f"[INTENT LOCK] {beat}")
            plan["must_happen"] = must_happen
            notes.append(f"ch{ch}:intent_beat_restored")
        out.append(plan)
    return out, notes


def g0_intent_errors(ws: Path, book: int | None = None) -> list[str]:
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    man = load_intent_manifest(ws, book_num)
    errs = validate_manifest(man)
    if man.get("status") != "approved":
        errs.append("intent:not_approved")
    concept = load_concept(ws)
    if man and concept and man.get("concept_digest") != concept_digest(concept):
        errs.append("intent:stale_concept_digest")
    return errs


def g1_narrative_fidelity_errors(ws: Path, book: int | None = None) -> list[str]:
    """Lock1: narrative pack must not contradict approved intent/concept."""
    errors: list[str] = []
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    man = load_intent_manifest(ws, book_num)
    if not man or man.get("status") != "approved":
        # Without intent, fall back to concept surface/true only
        concept = load_concept(ws)
        surface = str(concept.get("surface_plot") or "")
        true = str(concept.get("true_plot") or "")
    else:
        surface = str(man.get("surface_plot") or "")
        true = str(man.get("true_plot") or "")

    nd = narrative_dir(ws)
    ledger_path = nd / "mystery_ledger.json"
    if man and ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        expected_reveal = man.get("canonical_reveal_chapter")
        actual_reveal = ledger.get("canonical_reveal_chapter")
        if (
            expected_reveal is not None
            and actual_reveal is not None
            and int(expected_reveal) != int(actual_reveal)
        ):
            errors.append(
                "narrative:G1:canonical_reveal_mismatch:"
                f"intent_ch{int(expected_reveal)}!=ledger_ch{int(actual_reveal)}"
            )
    kernel_path = nd / "kernel.json"
    if kernel_path.exists():
        kernel = json.loads(kernel_path.read_text(encoding="utf-8"))
        true_case = str(kernel.get("true_case") or "")
        surface_case = str(kernel.get("surface_case") or "")
        if true and true_case and _coverage_ratio(true, true_case) < 0.15 and _coverage_ratio(true_case, true) < 0.15:
            # Very weak overlap either direction → likely rewrite drift
            if len(_tokens(true)) >= 8 and len(_tokens(true_case)) >= 8:
                errors.append("narrative:G1:true_case_diverges_from_concept")
        if surface and surface_case and _coverage_ratio(surface, surface_case) < 0.12:
            if len(_tokens(surface)) >= 8 and len(_tokens(surface_case)) >= 8:
                errors.append("narrative:G1:surface_case_diverges_from_concept")

    # Chapter map vs book_arc / ledger plant chapters — detect relocated locked beats
    if man and (man.get("chapter_map") or []):
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            # If a map beat for chapter N is strongly unique and only appears in ledger at far chapter, flag
            for entry in man.get("chapter_map") or []:
                ch = int(entry.get("chapter") or 0)
                beat = str(entry.get("beat") or "")
                if ch <= 0 or len(_tokens(beat)) < 6:
                    continue
                # Find best plant chapter among clues by token overlap with beat
                best_ch, best_ratio = 0, 0.0
                for clue in ledger.get("clues") or []:
                    content = str(clue.get("content") or "")
                    ratio = _coverage_ratio(beat, content)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_ch = int(clue.get("plant_chapter") or clue.get("payoff_chapter") or 0)
                if best_ratio >= 0.35 and best_ch and abs(best_ch - ch) >= 3:
                    errors.append(
                        f"narrative:G1:beat_relocated map_ch{ch}->ledger_ch{best_ch}"
                    )
    return errors


def g3_plan_fidelity_errors(
    ws: Path,
    plans: list[dict],
    book: int | None = None,
) -> list[str]:
    """Plan[n] must cover intent chapter_map[n]; no placeholder leads; ending on final ch."""
    errors: list[str] = []
    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    man = load_intent_manifest(ws, book_num)
    if not man or man.get("status") != "approved":
        errors.append("plan:G3:intent_not_approved")
        return errors

    by_ch = {int(p.get("chapter") or 0): p for p in plans if int(p.get("chapter") or 0) > 0}
    chapter_count = int(man.get("chapter_count") or 0)
    ending = str(man.get("ending_book1") or "").strip()
    must_avoid = [a.lower() for a in (man.get("must_avoid") or [])]

    for entry in man.get("chapter_map") or []:
        ch = int(entry.get("chapter") or 0)
        if ch <= 0:
            continue
        plan = by_ch.get(ch)
        if not plan:
            errors.append(f"plan:G3:missing_chapter_plan:{ch}")
            continue
        beat = str(entry.get("beat") or "")
        required_bits = list(entry.get("must_happen") or []) + must_include_for_chapter(man, ch)
        hay = " ".join(
            [
                str(plan.get("beat_summary") or ""),
                str(plan.get("chapter_task") or ""),
                str(plan.get("one_line_summary") or ""),
                " ".join(str(x) for x in (plan.get("must_happen") or [])),
            ]
        )
        if beat and _coverage_ratio(beat, hay) < 0.28 and len(_tokens(beat)) >= 8:
            errors.append(f"plan:G3:chapter_map_not_covered:ch{ch}")
        # Plan must_happen must also cover the locked beat (machine-generated contract).
        mh_hay = " ".join(str(x) for x in (plan.get("must_happen") or []))
        if beat and mh_hay and _coverage_ratio(beat, mh_hay) < 0.22 and len(_tokens(beat)) >= 8:
            errors.append(f"plan:G3:must_happen_betrays_map:ch{ch}")
        for req in required_bits:
            if req and _coverage_ratio(req, hay) < 0.2 and len(_tokens(req)) >= 5:
                errors.append(f"plan:G3:must_include_missing:ch{ch}:{req[:48]}")

        blob_lower = hay.lower()
        # Strip negated / instructional uses so "no male lead exists" does not
        # trip the placeholder detector.
        blob_for_placeholder = re.sub(
            r"\bno\s+(?:male|female)\s+lead\b[^.!\n]*",
            " ",
            blob_lower,
        )
        blob_for_placeholder = re.sub(
            r"\b(?:without|forbid(?:s|den)?|avoid)\s+(?:a\s+)?(?:male|female)\s+lead\b",
            " ",
            blob_for_placeholder,
        )
        for phrase in (
            "female lead",
            "male lead",
            "female_lead",
            "male_lead",
            "[name]",
            "pov lead",
        ):
            if phrase in blob_for_placeholder:
                errors.append(f"plan:G3:placeholder_lead:ch{ch}:{phrase}")

        for avoid in must_avoid:
            # Only flag obvious contradictions when avoid phrase is short and appears as requirement
            if avoid and len(avoid) >= 8 and avoid in blob_lower and "must not" not in blob_lower:
                # soft: skip — too noisy for free text
                pass

    if ending and chapter_count:
        last = by_ch.get(chapter_count)
        if last:
            hay = " ".join(
                [
                    str(last.get("beat_summary") or ""),
                    str(last.get("chapter_task") or ""),
                    " ".join(str(x) for x in (last.get("must_happen") or [])),
                ]
            )
            if _coverage_ratio(ending, hay) < 0.12 and len(_tokens(ending)) >= 8:
                errors.append(f"plan:G3:ending_not_on_final_chapter:ch{chapter_count}")
        else:
            errors.append(f"plan:G3:missing_final_chapter_plan:{chapter_count}")

    return errors


def prompt_projection_digest(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]


# Operator opt-in: hand-edited disk prompt is SoT; skip live rebuild equality check.
# Put this on line 1 of prompts/ch_NNN.txt (exact token).
PROMPT_HAND_LOCK_TOKEN = "PROMPT_HAND_LOCK"


def is_prompt_hand_locked(prompt_text: str) -> bool:
    """True when operator marked the disk prompt as intentionally hand-edited."""
    for line in (prompt_text or "").splitlines()[:8]:
        s = line.strip()
        if not s:
            continue
        if PROMPT_HAND_LOCK_TOKEN in s:
            return True
        # First non-empty line is not a lock comment → not locked
        if s.startswith("#") or s.startswith("//"):
            continue
        return False
    return False


def strip_prompt_hand_lock_banner(prompt_text: str) -> str:
    """Remove hand-lock banner lines before sending text to the Writer model."""
    lines = (prompt_text or "").splitlines(keepends=True)
    out: list[str] = []
    skipping = True
    for line in lines:
        if skipping:
            s = line.strip()
            if not s:
                continue
            if PROMPT_HAND_LOCK_TOKEN in s:
                continue
            skipping = False
            out.append(line)
        else:
            out.append(line)
    return "".join(out)


def g4_prompt_errors(
    ws: Path,
    book: int,
    chapter: int,
    prompt_text: str,
    *,
    disk_text: str | None = None,
) -> list[str]:
    """Prompt must be projection of plan+manifest; no full-book must_include dump."""
    errors: list[str] = []
    man = load_intent_manifest(ws, book)
    if man and man.get("status") == "approved":
        book_level = man.get("must_include_book") or []
        # If many book-level items all appear AND chapter-local list is empty → dump smell
        local = must_include_for_chapter(man, chapter)
        if book_level and len(book_level) >= 3 and not local:
            hits = sum(1 for item in book_level if str(item) and str(item) in prompt_text)
            if hits >= max(3, len(book_level) - 1) and chapter < int(man.get("chapter_count") or 99):
                errors.append(f"prompt:G4:full_book_must_include_dump:ch{chapter}")

        # World-rule spoil: true_plot large fragment in early chapter
        true = str(man.get("true_plot") or "")
        if chapter <= 2 and true and len(_tokens(true)) >= 12:
            if _coverage_ratio(true, prompt_text) >= 0.45:
                errors.append(f"prompt:G4:true_plot_spoil_early:ch{chapter}")

        # POV self-contradiction: first_person intent + hard ban on I/my/me in same prompt
        pov = str(man.get("pov") or "").lower().replace("-", "_")
        low = prompt_text.lower()
        if "first" in pov:
            if "no first-person" in low or "third-person limited locked" in low:
                errors.append(f"prompt:G4:pov_self_contradiction:ch{chapter}")
            if "pov: first_person" in low and "third-person limited locked" in low:
                errors.append(f"prompt:G4:pov_mixed_instructions:ch{chapter}")

    # Hand-locked disk is operator SoT — do not require live rebuild equality.
    if disk_text is not None and is_prompt_hand_locked(disk_text):
        return errors
    if disk_text is not None and disk_text.strip() and prompt_text.strip():
        if prompt_projection_digest(disk_text) != prompt_projection_digest(prompt_text):
            errors.append(f"prompt:G4:disk_mismatch:ch{chapter}")
    return errors


def assert_prompt_matches_disk(disk_text: str, live_text: str, chapter: int) -> None:
    if is_prompt_hand_locked(disk_text):
        return
    if prompt_projection_digest(disk_text) != prompt_projection_digest(live_text):
        raise RuntimeError(
            f"prompt SoT mismatch ch{chapter}: disk prompts/ch_{chapter:03d}.txt "
            "differs from live rebuild — re-run render-prompts or fix prompt builder "
            f"(or add '# {PROMPT_HAND_LOCK_TOKEN}' on line 1 to trust your hand edit)"
        )
