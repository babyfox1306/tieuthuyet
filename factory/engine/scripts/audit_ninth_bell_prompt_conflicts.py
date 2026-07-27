"""Deep contradiction audit for the-ninth-bell prompts Ch1-10."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "factory" / "workspaces" / "the-ninth-bell"


def add(findings: list, sev: str, ch: int, code: str, detail: str) -> None:
    findings.append((sev, ch, code, detail))


def extract_section(text: str, start: str, end_markers: list[str]) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    rest = text[i + len(start) :]
    ends = [rest.find(m) for m in end_markers if rest.find(m) >= 0]
    j = min(ends) if ends else len(rest)
    return rest[:j]


def main() -> None:
    man = json.loads((WS / "books" / "01" / "intent_manifest.json").read_text(encoding="utf-8"))
    cmap = {int(x["chapter"]): x for x in man.get("chapter_map") or []}
    findings: list[tuple[str, int, str, str]] = []

    for ch in range(1, 11):
        path = WS / "books" / "01" / "prompts" / f"ch_{ch:03d}.txt"
        t = path.read_text(encoding="utf-8")
        low = t.lower()

        # --- Structural: MUST INCLUDE nested under MUST AVOID ---
        avoid_block = extract_section(
            t,
            "Content boundaries (MUST AVOID):",
            [
                "Required this chapter (MUST INCLUDE):",
                "Bắt buộc chương này (MUST INCLUDE):",
                "If any instruction below",
                "## CHARACTER BIBLE",
                "NOTE:",
            ],
        )
        if "MUST INCLUDE" in avoid_block:
            add(
                findings,
                "HIGH",
                ch,
                "must_include_under_must_avoid",
                "MUST INCLUDE bullets sit inside MUST AVOID list — model may treat required beats as forbidden",
            )

        # --- POV ---
        if "first_person" in low and ("no first-person" in low or "third-person limited locked" in low):
            add(findings, "HIGH", ch, "pov_self_contradict", "first_person + third/ban first")

        # --- Spice ---
        if ("max level 0" in low or "## [spice] level 0" in low) and "fade to black beyond kiss" in low:
            add(findings, "MED", ch, "spice_kiss_vs_l0", "Level 0 none + fade-to-black/kiss wording")
        if "## [spice] level 0" in low and ("no kissing" in low or "no romance heat" in low):
            if "kiss/tension" in low:
                add(findings, "MED", ch, "spice_internal_conflict", "kiss allowed-ish vs no kissing")

        # --- Markdown vs plain ---
        if "plain text only" in low and ("title `# chapter" in low or "(`# chapter" in low):
            add(findings, "HIGH", ch, "md_title_vs_plain", "bans markdown/# headings but requires title `# Chapter N`")

        # --- Final chapter cliffhanger ---
        if ch == 10 and "end on a cliffhanger that forces the next chapter" in low:
            add(findings, "HIGH", ch, "final_ch_cliffhanger_req", "Ch10 is final but tech req demands next-chapter cliffhanger")

        # --- Afterlife / coda ---
        if (
            ch == 10
            and "elin secretly alive" in low
            and ("elin whisper" in low or "you came back" in low)
            and "not proof of secret survival" not in low
            and "không chứng minh còn sống" not in low
        ):
            add(
                findings,
                "MED",
                ch,
                "coda_vs_alive_ban",
                "MUST AVOID Elin secretly alive + MUST INCLUDE Elin whisper coda — needs clear non-alive framing",
            )

        # --- Futuristic tech ban vs acoustic surveillance (late chapters) ---
        if "futuristic or magical technology" in low and ch >= 7:
            if "acoustic surveillance" in low or "surveillance system" in low:
                add(
                    findings,
                    "LOW",
                    ch,
                    "tech_ban_vs_system",
                    "ban futuristic tech + must establish acoustic surveillance (usually OK if analog 1990s)",
                )

        # --- Arc end spoiler in every bible ---
        if "finally rejecting the false responsibility" in low and ch <= 6:
            add(
                findings,
                "MED",
                ch,
                "bible_arc_endgame_spoiler",
                "character Internal arc dumps end-state resolution into early/mid prompts",
            )

        # --- Never write (none) ---
        if "never write: (none)" in low:
            add(findings, "LOW", ch, "empty_alias_boilerplate", "Never write: (none) is empty alias noise")

        # --- Cast relation grammar ---
        if " of clara vale (" in low or "sister of clara vale" in low:
            add(findings, "LOW", ch, "cast_relation_grammar", "awkward relation suffix of Clara Vale")

        # --- Elin status ---
        if "deceased / unknown" in low:
            add(findings, "LOW", ch, "elin_status_ambiguous", "status deceased/unknown undercuts dead-sister premise")

        # --- Parse must/forbid ---
        mi = re.findall(r"(?:MUST INCLUDE \(this chapter\):|- )\s*(.+)", t)
        # Prefer dedicated MUST INCLUDE section bullets
        inc_sec = extract_section(
            t,
            "Required this chapter (MUST INCLUDE):",
            ["If any instruction below", "## CHARACTER BIBLE", "NOTE:"],
        )
        if inc_sec:
            mi = [ln[2:].strip() for ln in inc_sec.splitlines() if ln.startswith("- ")]
        else:
            mi = re.findall(r"MUST INCLUDE \(this chapter\):\s*(.+)", t)
        mh_m = re.search(r"\*\*Must happen:\*\*\s*(.+)", t)
        fb_m = re.search(r"\*\*Forbidden / must not contradict:\*\*\s*(.+)", t)
        must_h = [x.strip() for x in (mh_m.group(1).split(";") if mh_m else []) if x.strip()]
        forb = [x.strip() for x in (fb_m.group(1).split(";") if fb_m else []) if x.strip()]

        # Ch1: forbid introduce Thomas vs cast lists him (OK) — check must
        if ch == 1:
            for a in mi + must_h:
                if re.search(r"\bthomas\b", a, re.I):
                    add(findings, "HIGH", ch, "ch1_thomas_must", a[:80])

        # Intent map fidelity
        entry = cmap.get(ch)
        if entry:
            for beat in entry.get("must_happen") or []:
                toks = [
                    w
                    for w in re.findall(r"[A-Za-z]{5,}", beat)
                    if w.lower()
                    not in {"clara", "would", "there", "which", "their", "after", "before", "rather"}
                ]
                hits = sum(1 for w in toks[:10] if w.lower() in low)
                if toks and hits < max(2, min(4, len(toks[:10]) // 2)):
                    add(findings, "MED", ch, "beat_weak_in_prompt", beat[:90])

            intent_end = (entry.get("ending") or entry.get("final_line") or "").strip()
            cliff_m = re.search(r"End cliffhanger:\s*(.+)", t)
            final_m = re.search(r"Final line:\s*'([^']+)'", t)
            if intent_end and cliff_m:
                # soft check token overlap
                it = set(re.findall(r"[a-z]{5,}", intent_end.lower()))
                ct = set(re.findall(r"[a-z]{5,}", cliff_m.group(1).lower()))
                if it and len(it & ct) < max(1, len(it) // 4) and ch < 10:
                    add(
                        findings,
                        "MED",
                        ch,
                        "ending_drift",
                        f"intent ending weakly reflected in cliff | intent={intent_end[:70]}",
                    )
            if ch == 10 and entry.get("final_line"):
                fl = entry["final_line"]
                if fl.lower() not in low:
                    add(findings, "HIGH", ch, "missing_final_line", fl)

        # Must happen vs forbidden semantic clash (keyword)
        for a in must_h + mi:
            al = a.lower()
            for b in forb:
                bl = b.lower()
                # Aligned: must says does-not-forgive / refuses-to-forgive vs forbid "have Clara forgive"
                if "forgive" in al and ("not" in al or "refuse" in al or "without forgiving" in al):
                    continue
                if (
                    "forgive" in al
                    and "not" not in al
                    and "refuse" not in al
                    and "have clara forgive" in bl
                ):
                    add(findings, "HIGH", ch, "must_forbid_forgive", a[:60])

        # Hook vs tech: weather ban vs mist in ch1 hook
        if ch == 1 and "no scene-setting / weather openers" in low and "mist" in low:
            hook = re.search(r"Open with hook:\s*(.+)", t)
            if hook and "mist" in hook.group(1).lower():
                add(
                    findings,
                    "LOW",
                    ch,
                    "hook_weather_tension",
                    "hook mentions mist while weather openers banned (dialogue-led — soft)",
                )

        # Romance ban vs no ML — consistent
        if "romance writer" in low or "goodnovel" in low:
            add(findings, "HIGH", ch, "wrong_persona", "romance persona")

        # Ch10: resolve human mystery vs fully explaining final supernatural — OK
        # Ch10: tech req cliffhanger already flagged

        # Check LOCKED CANON says THIS BLOCK WINS but then task may conflict with avoid list structure
        if "this block wins" in low and "must include (this chapter)" in avoid_block.lower():
            pass  # already HIGH

    print("TOTAL", len(findings))
    print("by_sev", dict(Counter(s for s, *_ in findings)))
    print("by_code", dict(Counter(c for _, _, c, _ in findings)))
    print("---")
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    for sev, ch, code, detail in sorted(findings, key=lambda x: (order[x[0]], x[1], x[2])):
        print(f"[{sev}] ch{ch:02d} {code}: {detail}")


if __name__ == "__main__":
    main()
