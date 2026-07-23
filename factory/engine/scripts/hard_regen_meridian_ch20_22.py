"""Hard regen Meridian ch20-22 — Marsh villain lock, no chapter-map, recording logic."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from factory.engine.lib.call_9router import call_9router
from factory.engine.lib.export_gate import (
    check_eg08_short,
    check_eg13_engine_tokens,
    check_eg19_inherited_canon,
    check_eg20_reveal_order_role,
)
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.lib.prose_sanitize import sanitize_prose
from factory.engine.paths import load_config, workspace_dir

WS = "the-meridian-spine"
CAT = Path("catalog/the-meridian-spine/books/01-the-meridian-spine/chapters")
SC = Path("catalog/the-meridian-spine/spot_check")
PIPE = Path("factory/workspaces/the-meridian-spine/books/01/pipeline/ready")

CANONICAL = (
    "Stellan Marsh architected the National Integrity Directorate as a capture "
    "instrument: the reform built to prevent the next Kessler is the mechanism "
    "by which he and the co-owners who financed Renn now control national "
    "procurement, laundering the same fraud at the scale of a country behind "
    "the credibility of the body meant to stop it."
)

SYSTEM = f"""You write third-person limited past-tense English conspiracy thriller.
POV: Iris Kane only (she/her). NEVER first-person narration.
Journalist: Celia Ward only.
Tool-mark signature ONLY: seven compression points + fifth-position drag + asymmetric guide bite.
Optional secondary: damaged manufacturer die on jig plate.
HARD BANS (instant fail):
- Marsh as Special Agent / federal agent / investigator / podium host / press brief host
- Marsh arresting anyone else; anonymous "primary suspect" replacing Marsh
- "Marsh confessed" / Marsh speaking the full capture sentence
- "Chapter N:" headings in body; "Chapters 19 and 20" / any chapter-map speech
- Book 1 / Book 2 / Kessler Bridge / Kessler coupon / winged key / falcon watermark
- Markdown; meta preambles ("Certainly—here is…"); "C011 holds up"
- The phrase "canonical finding" as spoken dialogue (Iris may state the conclusion in her own voice without that label)
CAST LOCK: Marsh is the architect villain being exposed and taken into custody by others — NEVER the investigator.
Output: chapter prose only. No # title line. No preamble.
Canonical sentence Iris may speak once (ch20 only), as HER conclusion, not reading a document aloud:
"{CANONICAL}"
"""

SPECS = {
    20: {
        "title": "The Architect Revealed",
        "slug": "the-architect-revealed",
        "task": f"""Write Chapter 20 (~1600 words).

PRIOR: End of ch19 Iris already primed her hidden recorder (battery green). She goes alone to Marsh's office with jig plate + transaction coupons in custody.

MUST:
1. Activate the primed recorder early — BEFORE questioning (not a surprise gadget invent mid-scene).
2. Marsh confirms ON RECORD, separately: Veridian production code approval; exemption route; Meridian national-essential classification; knew Halveston benefited. He confirms fragments. He does NOT confess the capture plan.
3. Iris states the full capture conclusion ONCE in her own voice (exact words below) as what the evidence proves — NOT "let me summarize the canonical finding" document-speak:
"{CANONICAL}"
4. Marsh deflects ("ambitious connection of dots") — does not repeat the sentence.
5. Iris leaves, transmits package to Celia Ward; Marsh starts lockdown too late.
Cliffhanger: Directorate alarms / containment closing.""",
    },
    21: {
        "title": "The Public Account",
        "slug": "the-public-account",
        "task": """Write Chapter 21 (~1650 words).

MUST:
1. Public press moment. Celia Ward present. Iris may be present or watching secure feed.
2. MARSH IS THE SUBJECT BEING EXPOSED — in custody process or forced to answer as the architect under investigation. He is NOT "Special Agent Marsh" and NOT hosting the briefing as law enforcement.
3. Celia asks about FINDINGS and EVIDENCE (recording of fragment confirmations + Iris's formal report + tool-mark package). NEVER "has Marsh confessed". NEVER "Chapters 19 and 20".
4. Publish once: tool-mark proof (seven points / fifth drag / asymmetric bite) + custody of jig plate / coupons from Veridian.
5. Recording authenticates Marsh confirming the lawful-sounding routes; Iris's report carries the capture conclusion.
6. Marsh is removed into federal custody (handcuffs / escort). NO anonymous tall wiry "primary suspect" instead of Marsh.
Cliffhanger: public has the package; unfinished redacted co-owners still haunt Iris.""",
    },
    22: {
        "title": "The Unfinished Thread",
        "slug": "the-unfinished-thread",
        "task": """Write Chapter 22 (~1600 words) epilogue.

MUST:
1. Iris with Celia Ward on air / secure interview. Evidence: the recording package + forensic audit — describe by content (recording / audit), not "C011 holds up" as a clue-code sentence. Custody labels OK if framed as evidence inventory names readers already understand.
2. Frame: Marsh confirmed specific routes on record; Iris's finding states the capture architecture. NEVER "Marsh confessed the plan".
3. Lund, Okafor, Halveston, Marsh accounted in order. Marsh in federal processing as the architect.
4. Iris resigns rather than inherit the captured institution.
5. Redacted Kessler co-owners page still incomplete — unfinished thread.
NO chapter-map language. NO Marsh as agent.""",
    },
}


def strip_noise(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^#\s*Chapter\s+\d+\s*:?\s*.*\n+", "", t, count=1, flags=re.I)
    t = re.sub(r"^(Certainly|Here is|Sure|Of course)[^\n]*\n+", "", t, flags=re.I)
    t = re.sub(r"(?m)^Chapter\s+\d+\s*:.*\n+", "", t)
    return sanitize_prose(t).strip() + "\n"


def manual_bad(body: str, ch: int) -> list[str]:
    bad: list[str] = []
    low = body.lower()
    if re.search(r"special\s+agent\s+marsh|agent\s+marsh", low):
        bad.append("manual:marsh_as_agent")
    if ch == 21 and re.search(r"primary\s+suspect", low) and "marsh" not in low[max(0, low.find("primary suspect") - 80) : low.find("primary suspect") + 80]:
        # suspect mentioned without Marsh nearby — soft check
        if "marsh" not in low[low.find("suspect") : low.find("suspect") + 200]:
            bad.append("manual:anonymous_suspect")
    if re.search(r"marsh\s+(?:has\s+)?confess", low):
        bad.append("manual:marsh_confess")
    if re.search(r"(?m)^chapter\s+\d+\s*:", body, re.I):
        bad.append("manual:chapter_heading")
    if re.search(r"\bchapters?\s+\d+(?:\s+and\s+\d+)?\b", low):
        bad.append("manual:chapter_map_phrase")
    if "c011 holds up" in low:
        bad.append("manual:c011_holds_up")
    if ch == 20 and "architected the national integrity directorate as a capture" not in low:
        bad.append("manual:missing_canonical")
    if re.search(r"(?m)^(I |I've |I'm |My )", body):
        bad.append("manual:first_person")
    return bad


def gate_bad(body: str, ch: int) -> list[str]:
    cfg = load_config()
    min_pub = int(cfg.get("min_publish_words") or 1250)
    bad: list[str] = []
    for c in (
        [check_eg08_short(body, ch, min_pub)]
        + check_eg13_engine_tokens(body, ch)
        + check_eg19_inherited_canon(body, ch, workspace_id=WS)
        + check_eg20_reveal_order_role(body, ch, workspace_id=WS)
    ):
        if not c.get("passed"):
            bad.append(f"{c['id']}:{c.get('detail')}")
    bad.extend(manual_bad(body, ch))
    return bad


def save(ch: int, body: str) -> Path:
    spec = SPECS[ch]
    meta = {
        "series": WS,
        "book": 1,
        "chapter": ch,
        "title": spec["title"],
        "spice": 1,
        "word_count": word_count_vi(body),
        "status": "draft",
        "needs_fix": [],
    }
    path = CAT / f"{ch:02d}-{spec['slug']}.md"
    path.write_text(
        "---\n"
        + yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n\n"
        + body.strip()
        + "\n",
        encoding="utf-8",
    )
    SC.mkdir(exist_ok=True)
    shutil.copy2(path, SC / path.name)
    PIPE.mkdir(parents=True, exist_ok=True)
    PIPE.joinpath(f"ch_{ch:03d}.txt").write_text(
        f"# Chapter {ch}: {spec['title']}\n\n{body.strip()}\n", encoding="utf-8"
    )
    print(f"  saved ch{ch} words={meta['word_count']}")
    return path


def write_one(ch: int, direction: dict) -> None:
    spec = SPECS[ch]
    print(f"[hard-regen] ch{ch:02d}…")
    text, _ = call_9router(
        "writer",
        spec["task"] + "\n\nReturn full chapter prose only.",
        direction=direction,
        system_override=SYSTEM,
        max_tokens=5500,
    )
    body = strip_noise(text)
    bad = gate_bad(body, ch)
    attempt = 1
    while bad and attempt < 3:
        print(f"  fail attempt{attempt}: {bad[:6]}")
        repair = (
            "REWRITE the FULL chapter fixing ONLY these violations. Keep plot locks.\n"
            + "\n".join(f"- {b}" for b in bad)
            + "\n\nPrior draft:\n"
            + body
        )
        text, _ = call_9router(
            "writer",
            repair,
            direction=direction,
            system_override=SYSTEM + "\nReturn full revised chapter only. No preamble.",
            max_tokens=5500,
        )
        body = strip_noise(text)
        bad = gate_bad(body, ch)
        attempt += 1
    if bad:
        print(f"  STILL BAD ch{ch}: {bad}")
    else:
        print(f"  PASS ch{ch}")
    save(ch, body)


def main() -> None:
    direction = load_direction(workspace_dir(WS))
    for ch in (20, 21, 22):
        write_one(ch, direction)
    print("DONE hard regen 20-22")


if __name__ == "__main__":
    main()
