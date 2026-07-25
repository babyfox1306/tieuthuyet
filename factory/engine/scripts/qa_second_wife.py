"""QA table for the-second-wife rewrite — no EPUB."""
from __future__ import annotations

import json
import re
from pathlib import Path

from factory.engine.lib.export_gate import (
    check_eg02_markers,
    check_eg16_cliffhanger_paste,
    find_cliffhanger_paste,
)
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prose_sanitize import find_markdown_artifacts
from factory.engine.lib.language import find_foreign_chars

ROOT = Path("factory/workspaces/the-second-wife/books/01")
READY = ROOT / "pipeline" / "ready"
MIN_WORDS = 1250

plan = json.loads((ROOT / "master_plan.json").read_text(encoding="utf-8"))
cliffs = {int(p["chapter"]): p.get("cliffhanger") or "" for p in plan["chapter_plans"]}
state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))

print("STATE locked_names:", state.get("locked_names"))
print("STATE Emily:", "Emily" in json.dumps(state))
print("STATE Harold:", "Harold" in json.dumps(state))
print("STATE Sarah Mills:", "Sarah" in json.dumps(state))
print()

rows = []
all_pass = True
for ch in range(1, 11):
    path = READY / f"ch_{ch:03d}.txt"
    if not path.exists():
        rows.append((ch, "EXISTS", "FAIL", "missing ready"))
        all_pass = False
        continue
    text = path.read_text(encoding="utf-8")
    checks = {}

    # names: previous housekeeper
    emily_hk = bool(
        re.search(r"\bEmily(?:\s+Morrison)?\b", text)
        and re.search(r"housekeeper|carer|name tag", text, re.I)
    ) or bool(re.search(r"housekeeper named Emily|Emily Morrison,\s+a\s+(?:former\s+)?housekeeper", text, re.I))
    emily_any = bool(re.search(r"\bEmily\b", text))
    clara = bool(re.search(r"\bClara\b", text))
    # For housekeeper role: fail if Emily used as housekeeper; Clara OK when present after reveal ch
    checks["hk_names"] = ("PASS", f"Clara={clara} Emily={emily_any}") if not emily_hk else ("FAIL", "Emily as housekeeper")

    # narrator alias
    sarah = bool(re.search(r"\bSarah\s+Mills\b", text))
    anna = bool(re.search(r"\bAnna\b", text))
    checks["alias"] = ("FAIL", "Sarah Mills present") if sarah else ("PASS", f"Anna={anna} SarahMills=0")

    # E.M. not expanded
    em_full = bool(re.search(r"\bEmily\s+Morrison\b", text))
    checks["EM"] = ("FAIL", "Emily Morrison invented") if em_full else ("PASS", "no full-name invent")

    # EG-16b
    hit = find_cliffhanger_paste(text, cliffs.get(ch, ""))
    checks["EG16b"] = ("FAIL", str(hit)) if hit else ("PASS", "no paste")

    # word count
    wc = word_count_vi(text)
    checks["WC"] = ("PASS", str(wc)) if wc >= MIN_WORDS else ("FAIL", str(wc))

    # CJK
    cjk = find_foreign_chars(text, "en")
    checks["CJK"] = ("FAIL", str(cjk[:5])) if cjk else ("PASS", "0")

    # markdown
    md = find_markdown_artifacts(text)
    checks["MD"] = ("FAIL", str(len(md))) if md else ("PASS", "0")

    # markers EG-02
    eg02 = [c for c in check_eg02_markers(text, ch) if not c.get("passed")]
    checks["MARKER"] = ("FAIL", str(eg02[0].get("detail"))) if eg02 else ("PASS", "0")

    for k, (st, ev) in checks.items():
        if st == "FAIL":
            all_pass = False
        rows.append((ch, k, st, ev))

print("| ch | check | result | evidence |")
print("|---|---|---|---|")
for ch, k, st, ev in rows:
    ev_s = str(ev).replace("|", "/")[:100]
    print(f"| {ch} | {k} | {st} | {ev_s} |")

print()
print("ALL_CHAPTER_CHECKS:", "PASS" if all_pass else "FAIL")

# Aggregate per chapter
print()
print("| ch | overall | fails |")
print("|---|---|---|")
for ch in range(1, 11):
    fails = [f"{k}" for c, k, st, _ in rows if c == ch and st == "FAIL"]
    print(f"| {ch} | {'PASS' if not fails else 'FAIL'} | {', '.join(fails) or '-'} |")
