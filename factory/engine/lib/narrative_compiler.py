"""Compile per-chapter narrative constraints from mystery_ledger + knowledge_matrix.

Source of truth for (a) plan merge and (b) prompt injection — both read from here,
never from each other. See architecture: compiler is the spine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.narrative_schema import PROFILE_REQUIRED, narrative_dir
from factory.engine.paths import workspace_dir

# Profiles whose required_files include mystery ledger + knowledge matrix.
# Enablement itself is asset-driven (narrative_compiler_enabled) — not this set.
NARRATIVE_COMPILER_PROFILES = frozenset(
    name
    for name, files in PROFILE_REQUIRED.items()
    if "mystery_ledger.json" in files and "knowledge_matrix.json" in files
)

# Archived workspaces — prefer direction.yaml ``workspace_mode: archive``.
ARCHIVE_WORKSPACES = frozenset()

REVEAL_WEIGHT_MAJOR = "major"
REVEAL_WEIGHT_MINOR = "minor"
MIN_CLUES_BY_REVEAL_WEIGHT = {
    REVEAL_WEIGHT_MAJOR: 2,
    REVEAL_WEIGHT_MINOR: 1,
}


def min_clues_for_reveal(reveal_weight: str) -> int:
    return MIN_CLUES_BY_REVEAL_WEIGHT.get(reveal_weight, MIN_CLUES_BY_REVEAL_WEIGHT[REVEAL_WEIGHT_MAJOR])


def narrative_compiler_enabled(ws: Path, direction: dict | None = None) -> bool:
    """True when mystery narrative assets exist and narrative is approved.

    Driven by workspace data from the user's concept pipeline — NOT by hardcoding
    a genre (gothic/thriller/…). If concept → profile produced ledger+matrix and
    the operator approved narrative, the compiler runs. Kill switches:
    ``narrative_compiler: false`` or ``workspace_mode: archive``.
    """
    if direction is None:
        direction = _load_direction(ws)
    if direction.get("narrative_compiler") is False:
        return False
    if direction.get("workspace_mode") == "archive":
        return False
    if ws.name in ARCHIVE_WORKSPACES:
        return False
    if (direction.get("narrative_status") or "draft") != "approved":
        return False
    nd = narrative_dir(ws)
    return (nd / "mystery_ledger.json").exists() and (nd / "knowledge_matrix.json").exists()


def _load_direction(ws: Path) -> dict:
    path = ws / "direction.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_ledger(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "mystery_ledger.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_knowledge_matrix(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "knowledge_matrix.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_knowledge_matrix(raw)


def _coerce_chapter_number(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            return int(s)
        m = re.match(r"^ch(\d+)$", s, re.I)
        if m:
            return int(m.group(1))
    return None


def normalize_knowledge_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    """Canonical shape: ``milestones: [int]``, ``characters: {name: {...}}``.

    Accepts legacy / LLM variants:
    - milestones as ``[1, 10, 25]``
    - milestones as ``[{chapter: 1, characters: {...}}, ...]`` (develop-narrative output)
    """
    if not matrix:
        return {"milestones": [], "characters": {}}

    out = dict(matrix)
    raw_ms = matrix.get("milestones") or []
    milestones: list[int] = []
    characters: dict[str, Any] = dict(matrix.get("characters") or {})

    for item in raw_ms:
        if isinstance(item, dict):
            ch = _coerce_chapter_number(item.get("chapter"))
            if ch is not None:
                milestones.append(ch)
            block_chars = item.get("characters")
            if isinstance(block_chars, dict):
                for name, data in block_chars.items():
                    if isinstance(data, dict):
                        characters[str(name)] = dict(data)
        else:
            ch = _coerce_chapter_number(item)
            if ch is not None:
                milestones.append(ch)

    out["milestones"] = sorted(set(milestones))
    out["characters"] = characters
    return out


def load_threads(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "threads.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def effective_milestone(chapter: int, milestones: list[int]) -> int:
    """Largest milestone <= chapter; 0 if none."""
    eligible = [m for m in milestones if m <= chapter]
    return max(eligible) if eligible else 0


def _split_knows(text: str) -> tuple[list[str], list[str]]:
    """Parse milestone prose into knows / does-not-know bullet lists."""
    if not text:
        return [], []
    lower = text.lower()
    for sep in ("does not know yet:", "does not know:", "doesn't know:"):
        idx = lower.find(sep)
        if idx >= 0:
            knows_part = text[:idx]
            not_part = text[idx + len(sep) :]
            knows = _split_list_items(knows_part.replace("Knows:", "").replace("knows:", ""))
            not_knows = _split_list_items(not_part)
            return knows, not_knows
    knows = _split_list_items(text.replace("Knows:", "").replace("knows:", ""))
    return knows, []


def _split_list_items(blob: str) -> list[str]:
    blob = blob.strip()
    if not blob:
        return []
    parts = re.split(r"[.;]\s+|\n+", blob)
    out: list[str] = []
    for p in parts:
        p = p.strip().strip("-").strip()
        if len(p) > 3:
            out.append(p)
    return out


def _active_thread_ids(threads_data: dict[str, Any], chapter: int) -> list[str]:
    out: list[str] = []
    for t in threads_data.get("threads") or []:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        opened = int(t.get("opened_chapter") or 0)
        close_by = int(t.get("must_close_by") or 9999)
        if tid and opened <= chapter <= close_by:
            out.append(str(tid))
    return sorted(out)


def _clues_for_chapter(ledger: dict[str, Any], chapter: int) -> tuple[list[str], list[str], dict[str, dict]]:
    plant: list[str] = []
    payoff: list[str] = []
    details: dict[str, dict] = {}
    for clue in ledger.get("clues") or []:
        if not isinstance(clue, dict):
            continue
        cid = clue.get("id")
        if not cid:
            continue
        pc = int(clue.get("plant_chapter") or 0)
        pay = int(clue.get("payoff_chapter") or 0)
        entry = {
            "id": cid,
            "content": clue.get("content", ""),
            "type": clue.get("type", ""),
            "misdirection": clue.get("misdirection", ""),
            "true_meaning": clue.get("true_meaning", ""),
            "plant_chapter": pc,
            "payoff_chapter": pay,
        }
        if pc == chapter:
            plant.append(cid)
            details[cid] = entry
        if pay == chapter:
            payoff.append(cid)
            details.setdefault(cid, entry)
    return plant, payoff, details


def _reveals_for_chapter(ledger: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rev in ledger.get("major_reveals") or []:
        if not isinstance(rev, dict):
            continue
        ch = int(rev.get("chapter") or 0)
        if ch != chapter:
            continue
        weight = str(rev.get("reveal_weight") or REVEAL_WEIGHT_MAJOR).lower()
        if weight not in MIN_CLUES_BY_REVEAL_WEIGHT:
            weight = REVEAL_WEIGHT_MAJOR
        out.append(
            {
                "id": rev.get("id", ""),
                "reveal": rev.get("reveal", ""),
                "impact": rev.get("impact", ""),
                "reveal_weight": weight,
                "required_clues": list(rev.get("required_clues") or []),
                "min_clues_required": min_clues_for_reveal(weight),
            }
        )
    return out


def _red_herrings_for_chapter(ledger: dict[str, Any], chapter: int) -> tuple[list[str], list[str]]:
    plant: list[str] = []
    dispel: list[str] = []
    for rh in ledger.get("red_herrings") or []:
        if not isinstance(rh, dict):
            continue
        rid = rh.get("id")
        if not rid:
            continue
        plants = [int(x) for x in (rh.get("plant_chapters") or [])]
        dispelled = int(rh.get("dispelled_chapter") or 0)
        if chapter in plants:
            plant.append(rid)
        if dispelled == chapter:
            dispel.append(rid)
    return plant, dispel


def _parse_must_not_know_entry(key: str, val: Any) -> tuple[str, int] | None:
    """Support fact→chapter int OR chN→fact string (legacy matrix layouts)."""
    key_s = str(key).strip()
    if re.match(r"^ch\d+$", key_s, re.I):
        try:
            threshold = int(key_s[2:])
        except ValueError:
            return None
        return str(val).strip(), threshold
    try:
        threshold = int(val)
    except (TypeError, ValueError):
        return None
    return key_s, threshold


def iter_must_not_know_before(char_data: dict[str, Any]) -> list[tuple[str, int]]:
    """Normalize must_not_know_before — dict, scalar int + hidden_truth, or empty."""
    raw = char_data.get("must_not_know_before")
    if raw is None:
        return []
    if isinstance(raw, int):
        hidden = str(char_data.get("hidden_truth") or "").strip()
        return [(hidden, raw)] if hidden else []
    if isinstance(raw, dict):
        out: list[tuple[str, int]] = []
        for fact_key, before_ch in raw.items():
            parsed = _parse_must_not_know_entry(fact_key, before_ch)
            if parsed:
                out.append(parsed)
        return out
    return []


def _knowledge_for_chapter(
    matrix: dict[str, Any],
    chapter: int,
    *,
    milestones: list[int] | None = None,
) -> dict[str, Any]:
    matrix = normalize_knowledge_matrix(matrix)
    ms = milestones if milestones is not None else list(matrix.get("milestones") or [])
    ms = sorted(ms)
    eff = effective_milestone(chapter, ms)
    pov: list[str] = []
    may_know: list[str] = []
    must_not_know: list[str] = []

    for char_name, data in (matrix.get("characters") or {}).items():
        if not isinstance(data, dict):
            continue
        pov.append(str(char_name))
        key = f"ch{eff}" if eff else None
        if key and data.get(key):
            knows, not_knows = _split_knows(str(data[key]))
            for k in knows:
                may_know.append(f"{char_name}: {k}")
            for nk in not_knows:
                must_not_know.append(f"{char_name}: {nk}")
        for fact, threshold in iter_must_not_know_before(data):
            if threshold > chapter:
                must_not_know.append(f"{char_name}: {fact}")
            else:
                may_know.append(f"{char_name}: {fact}")

    return {
        "pov_characters": pov,
        "may_know": may_know,
        "must_not_know": must_not_know,
        "effective_milestone": eff,
    }


def compile_chapter_narrative(
    ledger: dict[str, Any],
    matrix: dict[str, Any],
    threads_data: dict[str, Any],
    chapter: int,
    *,
    truth_background: list[str] | None = None,
) -> dict[str, Any]:
    """Deterministic narrative constraint for one chapter — no LLM."""
    clues_plant, clues_payoff, clue_details = _clues_for_chapter(ledger, chapter)
    rh_plant, rh_dispel = _red_herrings_for_chapter(ledger, chapter)
    knowledge = _knowledge_for_chapter(matrix, chapter)
    iris_knows, truth_bg = _split_iris_knows_and_truth(knowledge, truth_background)
    knowledge = dict(knowledge)
    knowledge["iris_knows"] = iris_knows
    knowledge["truth_background"] = truth_bg
    return {
        "chapter": chapter,
        "clues_plant": clues_plant,
        "clues_payoff": clues_payoff,
        "reveals": _reveals_for_chapter(ledger, chapter),
        "red_herrings_plant": rh_plant,
        "red_herrings_dispel": rh_dispel,
        "threads_touch": _active_thread_ids(threads_data, chapter),
        "knowledge": knowledge,
        "iris_knows": iris_knows,
        "truth_background": truth_bg,
        "clue_details": clue_details,
    }


def _split_iris_knows_and_truth(
    knowledge: dict[str, Any],
    extra_truth: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """iris_knows = may_know (writable beats); truth_background = must_not + god lines."""
    iris = [str(x) for x in (knowledge.get("may_know") or []) if str(x).strip()]
    truth = [str(x) for x in (knowledge.get("must_not_know") or []) if str(x).strip()]
    for line in extra_truth or []:
        s = str(line).strip()
        if s and s not in truth:
            truth.append(s)
    return iris, truth


def _kernel_truth_lines(ws: Path) -> list[str]:
    """Short god-truth lines from kernel — outliner must not write these into early beats."""
    path = ws / "bible" / "narrative" / "kernel.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    lines: list[str] = []
    for key in ("true_case", "core_question"):
        val = str(data.get(key) or "").strip()
        if val:
            lines.append(f"[kernel.{key}] {val}")
    return lines


def compile_act_constraints(ws: Path, act_from: int, act_to: int) -> dict[str, Any]:
    """Payload slice for Outliner: constraints + clue catalog for an act range."""
    direction = _load_direction(ws)
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    truth_lines = _kernel_truth_lines(ws)
    chapters = {}
    for ch in range(act_from, act_to + 1):
        compiled = compile_chapter_narrative(
            ledger, matrix, threads_data, ch, truth_background=truth_lines
        )
        chapters[str(ch)] = compiled
    return {
        "act_range": [act_from, act_to],
        "target_language": direction.get("target_language", "en"),
        "chapters": chapters,
        "clue_catalog": build_clue_catalog(ledger),
        "canonical_reveal_chapter": ledger.get("canonical_reveal_chapter"),
        "iris_vs_truth_rule": (
            "Write beats only from iris_knows. truth_background is god-knowledge — "
            "never put it into beat_summary/must_happen/cliffhanger before unlock."
        ),
    }


def build_clue_catalog(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for clue in ledger.get("clues") or []:
        if not isinstance(clue, dict) or not clue.get("id"):
            continue
        cid = str(clue["id"])
        catalog[cid] = {
            "content": clue.get("content", ""),
            "type": clue.get("type", ""),
            "plant_chapter": int(clue.get("plant_chapter") or 0),
            "payoff_chapter": int(clue.get("payoff_chapter") or 0),
            "misdirection": clue.get("misdirection", ""),
            "true_meaning": clue.get("true_meaning", ""),
        }
    return catalog


def compile_book_narrative(ws: Path, *, total_chapters: int | None = None) -> dict[int, dict[str, Any]]:
    direction = _load_direction(ws)
    if total_chapters is None:
        from factory.engine.lib.book_config import get_total_chapters

        book = int(direction.get("book") or 1)
        total = get_total_chapters(ws.name, book)
    else:
        total = total_chapters
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    truth_lines = _kernel_truth_lines(ws)
    return {
        ch: compile_chapter_narrative(
            ledger, matrix, threads_data, ch, truth_background=truth_lines
        )
        for ch in range(1, total + 1)
    }


def compile_workspace_narrative(workspace_id: str, *, total_chapters: int | None = None) -> dict[int, dict[str, Any]]:
    ws = workspace_dir(workspace_id)
    return compile_book_narrative(ws, total_chapters=total_chapters)


def compile_chapter_for_workspace(ws: Path, chapter: int) -> dict[str, Any] | None:
    """Single-chapter compile; None if compiler disabled for this workspace."""
    direction = _load_direction(ws)
    if not narrative_compiler_enabled(ws, direction):
        return None
    return compile_chapter_narrative(
        load_ledger(ws),
        load_knowledge_matrix(ws),
        load_threads(ws),
        chapter,
    )


def format_narrative_constraints_block(
    compiled: dict[str, Any],
    *,
    lang: str = "en",
    locked_plan: bool = False,
) -> str:
    """Render NARRATIVE CONSTRAINTS for Writer prompt — source is compiler only."""
    ch = compiled.get("chapter", 0)
    vi = lang == "vi"
    heading = (
        f"## RÀNG BUỘC NARRATIVE (Chương {ch})"
        if vi
        else f"## NARRATIVE CONSTRAINTS (Chapter {ch})"
    )
    authority = (
        "Nguồn: mystery_ledger + knowledge_matrix (compiler). "
        "Writer BẮT BUỘC tuân thủ; không mâu thuẫn."
        if vi
        else "Source: mystery_ledger + knowledge_matrix (compiler). "
        "Writer MUST obey; do not contradict."
    )
    lines = [heading, authority]
    if locked_plan:
        lines.append(
            "Beat chương đã khóa — giữ nguyên must_happen/must_not từ plan; "
            "chỉ ràng buộc clue/knowledge bên dưới."
            if vi
            else "Chapter beats are locked — keep plan must_happen/must_not; "
            "obey clue/knowledge rules below."
        )

    def _section(title: str, items: list[str], *, bullet_fmt: str | None = None) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"### {title}")
        for item in items:
            if bullet_fmt:
                lines.append(f"- {bullet_fmt.format(item=item)}")
            else:
                lines.append(f"- {item}")

    details = compiled.get("clue_details") or {}
    plant_lines = []
    for cid in compiled.get("clues_plant") or []:
        d = details.get(cid, {})
        content = d.get("content") or cid
        plant_lines.append(f"**{cid}**: {content}")
    _section(
        "Clues to PLANT" if not vi else "Manh mối PHẢI GIEO",
        plant_lines,
    )

    payoff_lines = []
    for cid in compiled.get("clues_payoff") or []:
        d = details.get(cid, {})
        content = d.get("content") or cid
        true_meaning = d.get("true_meaning", "")
        line = f"**{cid}**: {content}"
        if true_meaning:
            line += f" → ({true_meaning})"
        payoff_lines.append(line)
    _section(
        "Clues to PAY OFF" if not vi else "Manh mối PHẢI TRẢ",
        payoff_lines,
    )

    reveal_lines = []
    for rev in compiled.get("reveals") or []:
        rid = rev.get("id", "")
        weight = rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR)
        text = rev.get("reveal", "")
        reveal_lines.append(f"**{rid}** [{weight}]: {text}")
    _section(
        "Reveals this chapter" if not vi else "Hé lộ chương này",
        reveal_lines,
    )

    rh_plant = compiled.get("red_herrings_plant") or []
    rh_dispel = compiled.get("red_herrings_dispel") or []
    if rh_plant or rh_dispel:
        lines.append("")
        lines.append("### " + ("Red herrings" if not vi else "Manh gỡ / false lead"))
        if rh_plant:
            lines.append("- " + ("Plant: " if not vi else "Gieo: ") + ", ".join(rh_plant))
        if rh_dispel:
            lines.append("- " + ("Dispel: " if not vi else "Gỡ: ") + ", ".join(rh_dispel))

    threads = compiled.get("threads_touch") or []
    if threads:
        lines.append("")
        lines.append("### " + ("Active threads" if not vi else "Mạch đang mở"))
        lines.append("- " + ", ".join(threads))

    knowledge = compiled.get("knowledge") or {}
    may = knowledge.get("may_know") or []
    must_not = knowledge.get("must_not_know") or []
    if may or must_not:
        lines.append("")
        lines.append("### " + ("Knowledge gates" if not vi else "Cổng tri thức"))
        if may:
            lines.append("**" + ("May know" if not vi else "Được biết") + ":**")
            for m in may[:12]:
                lines.append(f"- {m}")
            if len(may) > 12:
                lines.append(f"- … (+{len(may) - 12})")
        if must_not:
            lines.append(
                "**"
                + ("MUST NOT know or reveal yet" if not vi else "TUYỆT ĐỐI chưa được biết/hé")
                + ":**"
            )
            for m in must_not:
                lines.append(f"- {m}")

    if len(lines) <= 2 and not plant_lines and not payoff_lines and not reveal_lines:
        return ""

    return "\n".join(lines)


def narrative_constraints_block_for_prompt(
    ws: Path,
    chapter: int,
    *,
    lang: str = "en",
    locked_plan: bool = False,
) -> str:
    """Prompt block from compiler; empty string if compiler off or no constraints."""
    if not narrative_compiler_enabled(ws):
        return ""
    compiled = compile_chapter_for_workspace(ws, chapter)
    if not compiled:
        return ""
    return format_narrative_constraints_block(
        compiled, lang=lang, locked_plan=locked_plan
    )


def narrative_block_for_plan(compiled: dict[str, Any]) -> dict[str, Any]:
    """Map compiler chapter output → chapter_plan.narrative schema."""
    knowledge = compiled.get("knowledge") or {}
    clue_details = compiled.get("clue_details") or {}
    clue_beats: dict[str, str] = {}
    for cid in compiled.get("clues_plant") or []:
        content = (clue_details.get(cid) or {}).get("content")
        if content:
            clue_beats[str(cid)] = str(content)

    reveals_out: list[dict[str, Any]] = []
    for rev in compiled.get("reveals") or []:
        if not isinstance(rev, dict):
            continue
        reveals_out.append(
            {
                "id": rev.get("id", ""),
                "reveal_weight": rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR),
                "required_clues": list(rev.get("required_clues") or []),
                "min_clues_required": rev.get(
                    "min_clues_required",
                    min_clues_for_reveal(str(rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR))),
                ),
            }
        )

    return {
        "clues_plant": list(compiled.get("clues_plant") or []),
        "clues_payoff": list(compiled.get("clues_payoff") or []),
        "reveals": reveals_out,
        "red_herrings_plant": list(compiled.get("red_herrings_plant") or []),
        "red_herrings_dispel": list(compiled.get("red_herrings_dispel") or []),
        "threads_touch": list(compiled.get("threads_touch") or []),
        "knowledge": {
            "pov_characters": list(knowledge.get("pov_characters") or []),
            "may_know": list(knowledge.get("may_know") or []),
            "must_not_know": list(knowledge.get("must_not_know") or []),
            "iris_knows": list(
                knowledge.get("iris_knows")
                or compiled.get("iris_knows")
                or knowledge.get("may_know")
                or []
            ),
            "truth_background": list(
                knowledge.get("truth_background")
                or compiled.get("truth_background")
                or []
            ),
            "effective_milestone": knowledge.get("effective_milestone", 0),
        },
        "clue_beats": clue_beats,
    }


def merge_narrative_into_plans(ws: Path, plans: list[dict]) -> list[dict]:
    """Attach compiler narrative to each plan. Skips locked and archive workspaces.

    Also injects ``[CLUE id]`` / ``[PAYOFF id]`` into must_happen when the ledger
    schedules a plant/payoff for that chapter but the outliner beat text does not
    yet reference it — so approve/QC does not fail purely because planning ran
    before narrative assets were attached.
    """
    if not narrative_compiler_enabled(ws):
        return plans
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    truth_lines = _kernel_truth_lines(ws)
    out: list[dict] = []
    for plan in plans:
        if plan.get("locked"):
            out.append(plan)
            continue
        ch = int(plan.get("chapter") or 0)
        if ch <= 0:
            out.append(plan)
            continue
        compiled = compile_chapter_narrative(
            ledger, matrix, threads_data, ch, truth_background=truth_lines
        )
        merged = dict(plan)
        merged["narrative"] = narrative_block_for_plan(compiled)
        merged["must_happen"] = _ensure_clue_beats_in_must_happen(
            list(merged.get("must_happen") or []),
            compiled,
            beat_summary=str(merged.get("beat_summary") or ""),
        )
        out.append(merged)
    return out


def _ensure_clue_beats_in_must_happen(
    must_happen: list,
    compiled: dict[str, Any],
    *,
    beat_summary: str = "",
) -> list:
    """Append missing scheduled clue/payoff lines so NC-07 can pass after merge."""
    mh = [str(x) for x in must_happen]
    blob = (" ".join(mh) + " " + beat_summary).lower()
    details = compiled.get("clue_details") or {}

    def _already(cid: str, content: str) -> bool:
        if cid.lower() in blob:
            return True
        c = (content or "").lower().strip()
        if len(c) >= 12 and c[:36] in blob:
            return True
        words = [w for w in re.findall(r"[a-zà-ỹ']{4,}", c) if w not in {"that", "with", "from", "this"}]
        if words and sum(1 for w in words[:6] if w in blob) >= 2:
            return True
        return False

    for cid in compiled.get("clues_plant") or []:
        cid_s = str(cid)
        content = str((details.get(cid_s) or {}).get("content") or "")
        if _already(cid_s, content):
            continue
        mh.append(f"[CLUE {cid_s}] {content}".strip())
        blob = (" ".join(mh) + " " + beat_summary).lower()

    for cid in compiled.get("clues_payoff") or []:
        cid_s = str(cid)
        content = str((details.get(cid_s) or {}).get("content") or "")
        if _already(cid_s, content):
            continue
        mh.append(f"[PAYOFF {cid_s}] {content}".strip())
        blob = (" ".join(mh) + " " + beat_summary).lower()

    return mh
