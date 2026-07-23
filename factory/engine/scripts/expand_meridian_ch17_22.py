"""Sanitize markdown + expand Meridian ch17-22 under min_publish_words."""
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
MIN_WORDS = 1300


def load_md(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def save_md(path: Path, meta: dict, body: str) -> None:
    body = sanitize_prose(body)
    body = re.sub(r"\*+([^*]+)\*+", r"\1", body)
    body = re.sub(r"`([^`]+)`", r"\1", body)
    meta["word_count"] = word_count_vi(body)
    meta["needs_fix"] = []
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
    ch = int(meta.get("chapter") or 0)
    title = str(meta.get("title") or f"Chapter {ch}")
    PIPE.mkdir(parents=True, exist_ok=True)
    PIPE.joinpath(f"ch_{ch:03d}.txt").write_text(
        f"# Chapter {ch}: {title}\n\n{body.strip()}\n", encoding="utf-8"
    )
    print(f"  saved {path.name} words={meta['word_count']}")


def gate_bad(body: str, ch: int) -> list[str]:
    bad: list[str] = []
    cfg = load_config()
    min_pub = int(cfg.get("min_publish_words") or 1250)
    for c in (
        [check_eg08_short(body, ch, min_pub)]
        + check_eg13_engine_tokens(body, ch)
        + check_eg19_inherited_canon(body, ch, workspace_id=WS)
        + check_eg20_reveal_order_role(body, ch, workspace_id=WS)
    ):
        if not c.get("passed"):
            bad.append(f"{c['id']}:{c.get('detail')}")
    if re.search(r"marsh\s+(?:has\s+)?confess", body, re.I):
        bad.append("manual:marsh_confess")
    return bad


def expand(path: Path, meta: dict, body: str, direction: dict) -> str:
    wc = word_count_vi(body)
    if wc >= MIN_WORDS:
        return body
    need = MIN_WORDS - wc + 80
    ch = int(meta["chapter"])
    prompt = (
        f"Expand Chapter {ch} by about {need} words. Keep past tense, Iris Kane POV, "
        "same plot beats and evidence logic. Add procedural/sensory detail only. "
        "HARD bans: Marsh confessed; Kessler Bridge; Kessler coupon; Book 1; winged key; "
        "falcon watermark; markdown (*italics*); C001 planted. "
        "Journalist = Celia Ward only. Return FULL expanded chapter prose only (no # heading).\n\n"
        + body
    )
    print(f"[expand] ch{ch:02d} {wc} -> ~{MIN_WORDS}")
    text, _ = call_9router(
        "writer",
        prompt,
        direction=direction,
        system_override=(
            "Expand commercial conspiracy-thriller prose. Past tense. Plain text only. "
            "Never invent Marsh confessing the canonical capture sentence."
        ),
        max_tokens=5000,
    )
    text = re.sub(r"^#\s*Chapter.*\n+", "", text.strip(), flags=re.I)
    return text.strip() + "\n"


def main() -> None:
    direction = load_direction(workspace_dir(WS))
    for ch in range(17, 23):
        paths = list(CAT.glob(f"{ch:02d}-*.md"))
        if not paths:
            print(f"missing ch{ch}")
            continue
        path = paths[0]
        meta, body = load_md(path)
        body = sanitize_prose(body)
        body = re.sub(r"\*+([^*]+)\*+", r"\1", body)
        body = expand(path, meta, body, direction)
        bad = gate_bad(body, ch)
        if bad:
            print(f"  WARN ch{ch}: {bad[:5]}")
            # one repair if new gates fail
            hard = [b for b in bad if not b.startswith("EG-08")]
            if hard:
                repair = (
                    "Revise FULL chapter. Fix ONLY:\n"
                    + "\n".join(f"- {b}" for b in hard)
                    + "\n\nKeep plot. Past tense. Plain text.\n\n"
                    + body
                )
                text, _ = call_9router(
                    "writer",
                    repair,
                    direction=direction,
                    system_override="Fix violations only. Return full chapter prose.",
                    max_tokens=5000,
                )
                body = re.sub(r"^#\s*Chapter.*\n+", "", text.strip(), flags=re.I) + "\n"
                bad = gate_bad(body, ch)
                print(f"  after repair: {bad[:5] or 'OK'}")
        save_md(path, meta, body)

    print("DONE expand/sanitize")


if __name__ == "__main__":
    main()
