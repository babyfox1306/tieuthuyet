"""Hard regen Meridian ch22 only — Lund/Okafor gender+role locks + EG-21."""
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
    check_eg21_character_identity,
)
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.lib.prose_sanitize import sanitize_prose
from factory.engine.paths import load_config, workspace_dir

WS = "the-meridian-spine"
CAT = Path("catalog/the-meridian-spine/books/01-the-meridian-spine/chapters")
SC = Path("catalog/the-meridian-spine/spot_check")
PIPE = Path("factory/workspaces/the-meridian-spine/books/01/pipeline/ready")
CH = 22
SLUG = "the-unfinished-thread"
TITLE = "The Unfinished Thread"

CANONICAL = (
    "Stellan Marsh architected the National Integrity Directorate as a capture "
    "instrument: the reform built to prevent the next Kessler is the mechanism "
    "by which he and the co-owners who financed Renn now control national "
    "procurement, laundering the same fraud at the scale of a country behind "
    "the credibility of the body meant to stop it."
)

SYSTEM = f"""You write third-person limited past-tense English conspiracy thriller.
POV: Iris Kane only (she/her). NEVER first-person narration.
Journalist: Celia Ward only (she/her).

CHARACTER IDENTITY LOCK (instant fail if broken):
- Petra Lund = WOMAN (she/her/hers). Role = materials certifier who forged Meridian load coupons using the override tool-mark. NEVER he/him/his for Lund. NEVER call her investigator/partner/architect.
- Nadia Okafor = WOMAN (she/her/hers). Role = investigative partner who steered Iris's investigation. NEVER he/him/his for Okafor. NEVER call her materials certifier or coupon forger.
- Stellan Marsh = MAN (he/him). Role = architect villain in federal custody / processing. NEVER Special Agent Marsh / Agent Marsh / investigator hosting press.
- Gerald Halveston = MAN (he/him). Financier who signed off; not the architect.

ACCOUNTING ORDER in epilogue: Lund (coupon forger/certifier) → Okafor (steering partner) → Halveston (financier) → Marsh (architect).

Tool-mark ONE signature only: seven compression points + fifth-position drag + asymmetric guide bite. Optional secondary: damaged manufacturer die on jig plate. Do NOT invent a second competing signature system.

HARD BANS:
- Marsh confessed / Marsh speaking full capture sentence as confession
- Chapter N: headings; Chapters N and M; Book 1/2; Kessler Bridge; Kessler coupon
- Markdown; meta preambles; "C011 holds up"; "canonical finding" as dialogue label
- Swapping Lund/Okafor genders or roles

Iris may state the capture conclusion once in her own voice:
"{CANONICAL}"

Output: chapter prose only. No # title. No preamble.
"""

TASK = f"""Write Chapter 22 (~1600 words) epilogue — The Unfinished Thread.

MUST:
1. Iris with Celia Ward on air / secure interview. Evidence = recording package + forensic audit (describe by content, not clue-code "C011 holds up").
2. Frame: Marsh confirmed specific routes on record; Iris's finding states the capture architecture. NEVER "Marsh confessed the plan".
3. Correct cast accounting with CORRECT pronouns and roles:
   - Petra Lund (she): materials certifier; forged coupons; in custody/processing
   - Nadia Okafor (she): investigative partner who steered the case; accounted for her steering
   - Gerald Halveston (he): financier sign-off
   - Stellan Marsh (he): architect in federal processing — NOT an agent
4. Iris resigns rather than inherit the captured institution.
5. Redacted Kessler co-owners page still incomplete — unfinished thread.
6. One tool-mark signature only (seven / fifth drag / asymmetric bite).

Return full chapter prose only.
"""


def strip_noise(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^#\s*Chapter\s+\d+\s*:?\s*.*\n+", "", t, count=1, flags=re.I)
    t = re.sub(r"^(Certainly|Here is|Sure|Of course)[^\n]*\n+", "", t, flags=re.I)
    t = re.sub(r"(?m)^Chapter\s+\d+\s*:.*\n+", "", t)
    return sanitize_prose(t).strip() + "\n"


def gate_bad(body: str) -> list[str]:
    cfg = load_config()
    min_pub = int(cfg.get("min_publish_words") or 1250)
    bad: list[str] = []
    for c in (
        [check_eg08_short(body, CH, min_pub)]
        + check_eg13_engine_tokens(body, CH)
        + check_eg19_inherited_canon(body, CH, workspace_id=WS)
        + check_eg20_reveal_order_role(body, CH, workspace_id=WS)
        + check_eg21_character_identity(body, CH, workspace_id=WS)
    ):
        if not c.get("passed"):
            bad.append(f"{c['id']}:{c.get('detail')}")
    low = body.lower()
    if re.search(r"\blund\b.{0,80}\b(?:he|him|his|himself)\b", body, re.I | re.S):
        bad.append("manual:lund_male")
    if re.search(r"\bokafor\b.{0,80}\b(?:he|him|his|himself)\b", body, re.I | re.S):
        bad.append("manual:okafor_male")
    if "special agent marsh" in low or re.search(r"\bagent\s+marsh\b", low):
        bad.append("manual:marsh_agent")
    if re.search(r"(?m)^(I |I've |I'm |My )", body):
        bad.append("manual:first_person")
    return bad


def save(body: str) -> None:
    meta = {
        "series": WS,
        "book": 1,
        "chapter": CH,
        "title": TITLE,
        "spice": 1,
        "word_count": word_count_vi(body),
        "status": "draft",
        "needs_fix": [],
    }
    path = CAT / f"{CH:02d}-{SLUG}.md"
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
    PIPE.joinpath(f"ch_{CH:03d}.txt").write_text(
        f"# Chapter {CH}: {TITLE}\n\n{body.strip()}\n", encoding="utf-8"
    )
    print(f"saved ch{CH} words={meta['word_count']}")


def main() -> None:
    direction = load_direction(workspace_dir(WS))
    print("[hard-regen] ch22…")
    text, _ = call_9router(
        "writer",
        TASK,
        direction=direction,
        system_override=SYSTEM,
        max_tokens=5500,
    )
    body = strip_noise(text)
    bad = gate_bad(body)
    attempt = 1
    while bad and attempt < 4:
        print(f"  fail attempt{attempt}: {bad[:8]}")
        repair = (
            "REWRITE the FULL chapter fixing ONLY these violations. Keep plot locks.\n"
            "CRITICAL: Petra Lund = she/her (materials certifier / coupon forger). "
            "Nadia Okafor = she/her (investigative partner). Marsh = accused architect, not agent.\n"
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
        bad = gate_bad(body)
        attempt += 1
    if bad:
        print(f"STILL BAD ch22: {bad}")
    else:
        print("PASS ch22")
    save(body)


if __name__ == "__main__":
    main()
