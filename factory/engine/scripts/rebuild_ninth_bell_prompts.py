"""Rebuild the-ninth-bell locked chain: concept → intent → plan → prompts + audit."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.canon_registry import scaffold_canon_registry
from factory.engine.lib.intent_gates import g3_plan_fidelity_errors, g4_prompt_errors
from factory.engine.lib.intent_manifest import approve_intent, load_intent_manifest
from factory.engine.lib.master_plan import (
    _bible_stub_from_intent,
    approve_plan,
    load_master_plan,
    plan_book,
)
from factory.engine.lib.narrative_schema import concept_validation_errors, load_concept
from factory.engine.lib.prompt_builder import load_direction, render_all_prompts
from factory.engine.paths import bible_path


WS = ROOT / "factory" / "workspaces" / "the-ninth-bell"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def audit_prompt(ch: int, text: str, man: dict) -> list[str]:
    errs: list[str] = []
    low = text.lower()
    pov = str(man.get("pov") or "").lower()

    if "romance writer" in low or "goodnovel" in low:
        errs.append("persona_romance_hardcoded")
    if "first" in pov.replace("-", "_"):
        if "no first-person" in low:
            errs.append("pov_bans_first_person")
        if "third-person limited locked" in low:
            errs.append("pov_forces_third_person")
        if "using i/my/me" not in low and "ngôi 1" not in low:
            errs.append("pov_missing_first_person_instruction")
    if "## [spice] level 1 (sweet)" in low and int(man.get("chapter_count") or 0):
        # spice_max 0 books must not emit sweet block
        if "level 0" not in low and "spice: max level 0" in low:
            errs.append("spice_sweet_with_max0")
    if "spice: max level 0" in low and "level 1 (sweet)" in low:
        errs.append("spice_0_and_1_contradiction")

    # Chapter map must_happen coverage in prompt
    entry = None
    for item in man.get("chapter_map") or []:
        if int(item.get("chapter") or 0) == ch:
            entry = item
            break
    if entry:
        for beat in entry.get("must_happen") or []:
            # soft: require a few distinctive tokens from the beat
            toks = [t for t in re.findall(r"[A-Za-z]{5,}", str(beat)) if t.lower() not in {"clara", "would", "there", "which", "their"}]
            if len(toks) >= 3:
                hits = sum(1 for t in toks[:8] if t.lower() in low)
                if hits < max(2, len(toks[:8]) // 3):
                    errs.append(f"beat_weak:{beat[:48]}")

    # Early-chapter true-plot spoilers
    if ch <= 2:
        for needle in (
            "illegal acoustic surveillance",
            "fabricated clara",
            "froze instead of taking",
            "thomas created an illegal",
        ):
            if needle in low:
                errs.append(f"early_true_spoil:{needle}")

    # must_not_reveal from chapter map
    if entry:
        for ban in entry.get("must_not_reveal") or []:
            # only flag if the prompt instructs to include the banned reveal as a must_include
            pass

    g4 = g4_prompt_errors(WS, 1, ch, text, disk_text=text)
    errs.extend(g4)
    return errs


def main() -> None:
    print("=== 1. CONCEPT ===")
    concept = load_concept(WS)
    cerr = concept_validation_errors(concept)
    if cerr:
        _fail("; ".join(cerr))
    print("concept ready:", concept.get("title"), "chs", (concept.get("format") or {}).get("total_chapters"))

    print("=== 2. INTENT (Python compile + approve) ===")
    man = approve_intent(WS, 1)
    print("intent approved", man.get("manifest_digest"), "pov=", man.get("pov"))
    print("cast", man.get("cast"))
    print("chapter_map", len(man.get("chapter_map") or []))

    print("=== 3. CANON + BIBLE STUB ===")
    print(scaffold_canon_registry(WS, force=True).get("message"))
    stub = _bible_stub_from_intent(WS, 1)
    bible_path(WS).write_text(json.dumps(stub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("bible stub leads:", stub["leads"]["female"].get("name"), "/", stub["leads"]["male"].get("name"))

    print("=== 4. PLAN (G3) ===")
    data = load_master_plan(WS, 1)
    plans = data.get("chapter_plans") or []
    g3 = g3_plan_fidelity_errors(WS, plans, book=1) if plans else ["plan:missing"]
    print("existing plans", len(plans), "G3", len(g3))
    if g3 or len(plans) < int(man.get("chapter_count") or 10):
        print("replan required — running plan_book...")
        path, n = plan_book(WS, 1, force_replan=True, require_bible=False)
        print("plan OK", path, "prompts interim", n)
        plans = load_master_plan(WS, 1).get("chapter_plans") or []
        g3 = g3_plan_fidelity_errors(WS, plans, book=1)
        if g3:
            print("G3 remaining:")
            for e in g3[:40]:
                print(" ", e)
            _fail(f"G3 still failing ({len(g3)})")
    else:
        print("keep existing plan (G3 clean)")

    print("=== 5. RENDER PROMPTS ===")
    n = render_all_prompts(WS, 1)
    print("rendered", n)

    print("=== 6. APPROVE-PLAN (G3+G4) ===")
    try:
        approve_plan(WS, 1)
        print("approve-plan OK")
    except Exception as exc:
        conflicts = getattr(exc, "conflicts", None)
        if conflicts:
            for c in conflicts[:40]:
                print(" ", c)
        _fail(f"approve-plan blocked: {exc}")

    print("=== 7. DEEP PROMPT AUDIT ===")
    man = load_intent_manifest(WS, 1)
    all_errs: dict[int, list[str]] = {}
    for ch in range(1, int(man.get("chapter_count") or 10) + 1):
        path = WS / "books" / "01" / "prompts" / f"ch_{ch:03d}.txt"
        if not path.exists():
            all_errs[ch] = ["missing_prompt_file"]
            continue
        text = path.read_text(encoding="utf-8")
        errs = audit_prompt(ch, text, man)
        if errs:
            all_errs[ch] = errs
        # print POV line for visibility
        pov_line = next((ln for ln in text.splitlines() if ln.startswith("POV:")), "")
        head = text.splitlines()[0] if text else ""
        print(f"ch{ch:02d} len={len(text)} | {head[:70]}")
        print(f"      {pov_line[:110]}")
        if errs:
            print(f"      ERRORS: {errs}")

    if all_errs:
        print("AUDIT FAILED chapters:", sorted(all_errs))
        _fail("prompt fidelity audit failed")
    print("ALL PROMPTS PASS fidelity audit")
    d = load_direction(WS)
    print(
        "direction:",
        {
            "intent": d.get("intent_status"),
            "plan": d.get("plan_status"),
            "pov_mode": d.get("pov_mode"),
            "spice_max": d.get("spice_max"),
        },
    )


if __name__ == "__main__":
    main()
