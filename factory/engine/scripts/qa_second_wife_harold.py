"""QA evidence table — real greps for the-second-wife rewrite."""
from __future__ import annotations

import json
import re
from pathlib import Path

from factory.engine.lib.export_gate import find_cliffhanger_paste
from factory.engine.lib.language import find_foreign_chars
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prose_sanitize import find_markdown_artifacts
from factory.engine.lib.export_gate import check_eg02_markers

ROOT = Path("factory/workspaces/the-second-wife/books/01")
READY = ROOT / "pipeline" / "ready"
MIN = 1250

plan = json.loads((ROOT / "master_plan.json").read_text(encoding="utf-8"))
cliffs = {int(p["chapter"]): p.get("cliffhanger") or "" for p in plan["chapter_plans"]}
state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))

print("STATE locked_names:", state.get("locked_names"))
print("STATE Harold count:", json.dumps(state).count("Harold"))
print("STATE Emily count:", json.dumps(state).count("Emily"))
print()

print("| ch | Harold | Marcus | Emily | Clara | SarahMills | Anna | EG16b | WC | CJK | MD | MARKER | overall |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")

all_ok = True
totals = {"Harold": 0, "Marcus": 0, "Emily": 0, "SarahMills": 0}
for ch in range(1, 11):
    text = (READY / f"ch_{ch:03d}.txt").read_text(encoding="utf-8")
    harold = len(re.findall(r"\bHarold\b", text))
    marcus = len(re.findall(r"\bMarcus\b", text))
    emily = len(re.findall(r"\bEmily\b", text))
    clara = len(re.findall(r"\bClara\b", text))
    sarah = len(re.findall(r"\bSarah\s+Mills\b", text))
    anna = len(re.findall(r"\bAnna\b", text))
    totals["Harold"] += harold
    totals["Marcus"] += marcus
    totals["Emily"] += emily
    totals["SarahMills"] += sarah

    eg = "FAIL" if find_cliffhanger_paste(text, cliffs.get(ch, "")) else "PASS"
    wc = word_count_vi(text)
    wc_s = "PASS" if wc >= MIN else "FAIL"
    cjk = "FAIL" if find_foreign_chars(text, "en") else "PASS"
    md = "FAIL" if find_markdown_artifacts(text) else "PASS"
    markers = [c for c in check_eg02_markers(text, ch) if not c.get("passed")]
    mark = "FAIL" if markers else "PASS"

    fails = []
    if harold:
        fails.append("Harold")
    if emily:
        fails.append("Emily")
    if sarah:
        fails.append("SarahMills")
    if eg == "FAIL":
        fails.append("EG16b")
    if wc_s == "FAIL":
        fails.append("WC")
    if cjk == "FAIL":
        fails.append("CJK")
    if md == "FAIL":
        fails.append("MD")
    if mark == "FAIL":
        fails.append("MARKER")
    overall = "PASS" if not fails else "FAIL"
    if overall == "FAIL":
        all_ok = False
    print(
        f"| {ch} | {harold} | {marcus} | {emily} | {clara} | {sarah} | {anna} | "
        f"{eg} | {wc}/{wc_s} | {cjk} | {md} | {mark} | {overall} |"
    )

print()
print("TOTALS:", totals)
print("ALL:", "PASS" if all_ok and totals["Harold"] == 0 else "FAIL")
