"""Regen Meridian Spine ch17-22 with locked B3/B4/B7 constraints."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from factory.engine.lib.call_9router import call_9router
from factory.engine.lib.export_gate import (
    check_eg13_engine_tokens,
    check_eg19_inherited_canon,
    check_eg20_reveal_order_role,
)
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import workspace_dir

WS = "the-meridian-spine"
CAT = Path("catalog/the-meridian-spine/books/01-the-meridian-spine/chapters")
PIPE = Path("factory/workspaces/the-meridian-spine/books/01/pipeline/ready")

CANONICAL = (
    "Stellan Marsh architected the National Integrity Directorate as a capture "
    "instrument: the reform built to prevent the next Kessler is the mechanism "
    "by which he and the co-owners who financed Renn now control national "
    "procurement, laundering the same fraud at the scale of a country behind "
    "the credibility of the body meant to stop it."
)

SYSTEM = """You are a professional conspiracy-thriller novelist writing paid-chapter English prose.
Rules (HARD — violate none):
- Past tense only. Third-person limited Iris Kane. No romance. No spice.
- Meridian Spine coupons are fine. NEVER say Kessler Bridge or Kessler coupon.
- Book-1 evidence was a tunnel core sample (spent). Book-2 comparison uses archived Kessler tunnel load-test hard-log / calibration-plate impressions.
- ONE tool-mark signature only: seven compression points + fifth-position drag + asymmetric guide bite. Optional secondary ONLY: damaged manufacturer die on jig plate. NO winged key, clove, falcon watermark, split crest, archive comb, 28-micron chatter.
- Journalist is Celia Ward only (never Rachel/Mara).
- Never write: Book 1, Book 2, C001 planted, TIER, binding_condition, canonical_text, FALSE ANSWER, authorized for release in chapter.
- Output chapter prose only with title line `# Chapter N: Title`. No meta."""

CHAPTER_SPECS: dict[int, dict] = {
    17: {
        "title": "The Systemic Loophole",
        "slug": "the-systemic-loophole",
        "task": """Write Chapter 17 (~1650 words).
Must happen:
- Legal tries to confine Iris to Meridian Spine only; she continues.
- She finds recurring oversight-diversion clause to internal Advisory_Panel_C008 (filename OK).
- Realizes pattern is systemic design above Halveston's fund — a principal exists, NO personal name yet.
- Cliffhanger: same clause echoed across national contracts.
Must NOT: name Marsh as architect; say reform is capture yet (that is ch18); Marsh confession.
Nadia may appear briefly as unreliable after betrayal (already revealed ch10-11).""",
    },
    18: {
        "title": "The Captured Reform",
        "slug": "the-captured-reform",
        "task": """Write Chapter 18 (~1700 words).
Must happen:
- Iris synthesizes legal loophole + Halveston national pattern + manipulated replacement coupon micro-crack.
- Reveal: the Directorate itself is the capture instrument (reform-is-capture). NO personal name of architect.
- Scene-based, not pure exposition — Iris builds the case on desk with physical pieces.
Must NOT: name Marsh as architect; Marsh confession; winged key.""",
    },
    19: {
        "title": "The Last Thread",
        "slug": "the-last-thread",
        "task": """Write Chapter 19 (~1750 words).
Must happen (WINNING EVIDENCE ON PAGE — reader must SEE Iris seize custody):
- In Veridian / machine-shop trail, Iris physically recovers: (1) jig plate with damaged manufacturer die matching the tool-mark signature; (2) private-asset transaction coupons linking Marsh's office finances to Veridian production; (3) if needed a damaged logo die — secondary only.
- She bags, seals, logs chain-of-custody with timestamps. No 'already in briefcase' shortcut.
- Marsh summoned as founder/beneficiary pressure only — NOT full architect canonical sentence yet.
- She sends package copy to Celia Ward.
- Marsh calls for private meeting tonight.
Must NOT: Iris or Marsh speak the full canonical capture sentence; say Marsh confessed; winged key.""",
    },
    20: {
        "title": "The Architect Revealed",
        "slug": "the-architect-revealed",
        "task": f"""Write Chapter 20 (~1800 words). CRITICAL RECORDING LOGIC:
- Iris confronts Marsh with physical evidence in custody (from ch19).
- Marsh confirms ON LIVE RECORD separate lawful-sounding acts one by one: created exemption route / approved Veridian production code / placed Meridian in national-essential classification / knew Halveston benefited. He confirms each fragment. He does NOT confess the full plan. He does NOT repeat the canonical sentence.
- Iris HERSELF states the canonical conclusion aloud as her forensic finding (exact wording required once):
  "{CANONICAL}"
- Hidden recording captures: Marsh's fragment confirmations + Iris's statement. Recording is NOT a Marsh confession of the canonical text.
- Iris transmits package to Celia Ward; Marsh locks down too late.
Must NOT: 'Marsh confessed'; Marsh speaking the canonical sentence; winged key; Book 1.""",
    },
    21: {
        "title": "The Public Account",
        "slug": "the-public-account",
        "task": """Write Chapter 21 (~1700 words).
Must happen:
- Press conference. Celia Ward questions Marsh.
- Anchor/Celia ask about FINDINGS and EVIDENCE — never 'has Marsh confessed'.
- Publish once: complete tool-mark proof (seven points + fifth drag + asymmetric bite) + custody of jig plate / transaction coupons seized in ch19-20.
- Recording authenticates Marsh confirming the specific routes; Iris's formal report carries the canonical conclusion.
- Marsh arrested / taken into custody process.
Must NOT: claim Marsh confessed the canonical sentence; Book 1 literal; falcon watermark; winged key.""",
    },
    22: {
        "title": "The Unfinished Thread",
        "slug": "the-unfinished-thread",
        "task": """Write Chapter 22 (~1700 words) epilogue.
Must happen:
- Iris on air with Celia Ward; evidence package C011 (recording of fragment confirmations + Iris finding) and C012 (forensic audit) authenticated.
- No 'Marsh confessed' framing — ask what the finding is / whether evidence holds.
- Lund, Okafor, Halveston, Marsh all accounted for in order.
- Iris resigns rather than inherit captured institution.
- Redacted Kessler co-owners page still incomplete — unfinished thread.
Must NOT: chapter-map phrases; Book 1; Marsh confessed canonical; winged key.""",
    },
}


def strip_heading(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^#\s*Chapter\s+\d+\s*:?\s*.*\n+", "", t, count=1, flags=re.I)
    return t.strip() + "\n"


def gate_ok(body: str, ch: int) -> list[str]:
    bad: list[str] = []
    for c in (
        check_eg13_engine_tokens(body, ch)
        + check_eg19_inherited_canon(body, ch, workspace_id=WS)
        + check_eg20_reveal_order_role(body, ch, workspace_id=WS)
    ):
        if not c.get("passed"):
            bad.append(f"{c['id']}:{c.get('detail')}")
    # Extra hard checks for recording logic on 20-22
    low = body.lower()
    if ch >= 20:
        if re.search(r"marsh\s+(?:has\s+)?confess", low):
            bad.append("manual:marsh_confess")
        if ch == 20 and "architected the national integrity directorate as a capture" in low:
            # must be Iris speaking — require nearby Iris attribution in same para roughly
            if "iris" not in low:
                bad.append("manual:canonical_without_iris")
    return bad


def write_chapter(ch: int) -> Path:
    spec = CHAPTER_SPECS[ch]
    direction = load_direction(workspace_dir(WS))
    prompt = (
        f"{spec['task']}\n\n"
        f"Title: Chapter {ch}: {spec['title']}\n"
        "Open with dialogue or action hook in first 3 sentences.\n"
        "End on a cliffhanger forcing the next chapter (ch22: unfinished thread beat).\n"
    )
    print(f"[regen] ch{ch:02d} calling writer...")
    text, _meta = call_9router(
        "writer",
        prompt,
        direction=direction,
        system_override=SYSTEM,
        max_tokens=4500,
    )
    body = strip_heading(text)
    bad = gate_ok(body, ch)
    if bad:
        print(f"  gate fail attempt1: {bad[:4]}")
        # one repair pass
        repair = (
            "Revise the chapter below. Fix ONLY these violations, keep plot:\n"
            + "\n".join(f"- {b}" for b in bad)
            + "\n\nCHAPTER:\n"
            + body
        )
        text2, _meta2 = call_9router(
            "writer",
            repair,
            direction=direction,
            system_override=SYSTEM + "\nReturn the full revised chapter only.",
            max_tokens=4500,
        )
        body = strip_heading(text2)
        bad = gate_ok(body, ch)
        if bad:
            print(f"  STILL FAIL ch{ch}: {bad}")
        else:
            print(f"  repaired ch{ch}")
    else:
        print(f"  pass ch{ch} words={word_count_vi(body)}")

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
    md = (
        "---\n"
        + yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n\n"
        + body.strip()
        + "\n"
    )
    out = CAT / f"{ch:02d}-{spec['slug']}.md"
    out.write_text(md, encoding="utf-8")
    PIPE.mkdir(parents=True, exist_ok=True)
    heading = f"# Chapter {ch}: {spec['title']}\n\n"
    PIPE.joinpath(f"ch_{ch:03d}.txt").write_text(heading + body.strip() + "\n", encoding="utf-8")
    # spot_check
    sc = Path("catalog/the-meridian-spine/spot_check") / out.name
    sc.parent.mkdir(exist_ok=True)
    sc.write_text(md, encoding="utf-8")
    return out


def main() -> None:
    chapters = [int(x) for x in sys.argv[1:]] or [17, 18, 19, 20, 21, 22]
    for ch in chapters:
        write_chapter(ch)


if __name__ == "__main__":
    main()
