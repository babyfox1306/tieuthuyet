"""Master plan — Outliner v2 in acts, then render chapter prompts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from factory.engine.lib.bible_schema import bible_is_approved
from factory.engine.lib.call_9router import call_9router, parse_json_response
from factory.engine.lib.catalog import safe_print
from factory.engine.lib.prompt_builder import (
    canon_summaries_for_seed,
    load_direction,
    load_series_bible,
    master_plan_path,
    render_all_prompts,
)
from factory.engine.lib.plan_qc import (
    apply_canon_plans,
    apply_deterministic_plan_fixes,
    ensure_task_word_count,
    validate_plan,
)
from factory.engine.lib.narrative_compiler import (
    compile_act_constraints,
    merge_narrative_into_plans,
    narrative_compiler_enabled,
)
from factory.engine.lib.plan_normalize import (
    normalize_chapter_plan,
    normalize_chapter_plans,
)
from factory.engine.paths import bible_path, book_workspace_dir, workspace_dir


def build_outliner_payload(
    ws: Path,
    book: int,
    act_from: int,
    act_to: int,
    act_name: str,
    *,
    bible: dict,
    direction: dict,
    prior: list[dict],
) -> dict:
    """Assemble Outliner request body; adds narrative_constraints when compiler on."""
    body: dict = {
        "series_bible": bible,
        "direction": direction,
        "book_number": book,
        "act_range": [act_from, act_to],
        "act_name": act_name,
        "prior_plans": prior,
        "canon_through": direction.get("canon_through", 3),
    }
    if narrative_compiler_enabled(ws):
        body["narrative_constraints"] = compile_act_constraints(ws, act_from, act_to)
    return body


def load_locked_plans(ws: Path) -> list[dict]:
    from factory.engine.lib.prompt_builder import load_locked_chapter_plans

    return load_locked_chapter_plans(ws)


def _trim_plan_for_payload(plan: dict) -> dict:
    """Giảm token khi gửi plan_fixer — giữ field cần continuity."""
    keys = (
        "chapter",
        "title",
        "one_line_summary",
        "beat_summary",
        "opens_with",
        "cliffhanger",
        "chapter_task",
        "must_happen",
        "must_not",
        "carries_to_next",
    )
    return {k: plan[k] for k in keys if k in plan}


def build_plan_fixer_payload(
    ws: Path,
    plan: dict,
    issues: list[str],
    prior: list[dict],
    direction: dict,
) -> dict:
    """Assemble plan_fixer request; adds narrative hints when compiler on."""
    slim_direction = {
        k: direction.get(k)
        for k in ("target_language", "spice_level", "total_chapters", "blurb", "book1_ending")
        if direction.get(k) is not None
    }
    body: dict = {
        "chapter_plan": _trim_plan_for_payload(plan),
        "issues": issues,
        "prior_plans": prior,
        "direction": slim_direction,
    }
    if narrative_compiler_enabled(ws):
        narr = plan.get("narrative") if isinstance(plan.get("narrative"), dict) else {}
        knowledge = narr.get("knowledge") if isinstance(narr.get("knowledge"), dict) else {}
        narrative_issues = [i for i in issues if ":NC-" in i]
        body["narrative_issues"] = narrative_issues
        body["narrative_fix_hints"] = {
            "immutable": [
                "narrative.clues_plant",
                "narrative.clues_payoff",
                "narrative.reveals",
                "narrative.red_herrings_plant",
                "narrative.red_herrings_dispel",
            ],
            "clue_beats": narr.get("clue_beats") or {},
            "clues_plant": narr.get("clues_plant") or [],
            "clues_payoff": narr.get("clues_payoff") or [],
            "must_not_know": knowledge.get("must_not_know") or [],
            "instruction": (
                "Sửa must_happen/beat_summary/cliffhanger để khớp clue & knowledge. "
                "KHÔNG đổi clue ID, timing, hay thêm field narrative vào output."
            ),
        }
    return body


def fix_plan_with_llm(ws: Path, book: int, plan: dict, issues: list[str]) -> dict:
    direction = load_direction(ws)
    current = load_master_plan(ws, book)
    prior = [
        _trim_plan_for_payload(p)
        for p in current.get("chapter_plans", [])
        if p.get("chapter", 0) < plan.get("chapter", 0)
    ][-5:]
    payload = json.dumps(
        build_plan_fixer_payload(ws, plan, issues, prior, direction),
        ensure_ascii=False,
        indent=2,
    )
    raw, _ = call_9router("plan_fixer", payload, max_tokens=4096, direction=direction)
    fixed = parse_json_response(raw)
    if not isinstance(fixed, dict):
        raise RuntimeError("plan_fixer returned non-object JSON")
    if "chapter" not in fixed:
        fixed["chapter"] = plan["chapter"]
    fixed.pop("narrative", None)
    if narrative_compiler_enabled(ws):
        merged = merge_narrative_into_plans(ws, [fixed])
        return merged[0] if merged else fixed
    return fixed


def qc_and_fix_plans(ws: Path, book: int, *, use_llm: bool = True) -> dict[int, list[str]]:
    direction = load_direction(ws)
    bible = load_series_bible(ws)
    data = load_master_plan(ws, book)
    locked = load_locked_plans(ws)
    plans = apply_canon_plans(data.get("chapter_plans", []), locked)
    plans = merge_narrative_into_plans(ws, plans)
    remaining: dict[int, list[str]] = {}
    total = len([p for p in plans if not p.get("locked")])
    done = 0

    for i, p in enumerate(plans):
        if p.get("locked"):
            continue
        done += 1
        ch = int(p.get("chapter") or 0)
        p = apply_deterministic_plan_fixes(p, direction)
        issues = validate_plan(p, direction, bible=bible, all_plans=plans, ws=ws)
        if issues and use_llm:
            safe_print(
                f"[fix-plans] ch{ch} ({done}/{total}): {len(issues)} issue(s) → plan_fixer…"
            )
            try:
                p = normalize_chapter_plan(
                    merge_narrative_into_plans(ws, [fix_plan_with_llm(ws, book, p, issues)])[0]
                )
                p = apply_deterministic_plan_fixes(p, direction)
                issues = validate_plan(p, direction, bible=bible, all_plans=plans, ws=ws)
                if issues:
                    safe_print(f"[fix-plans] ch{ch}: still {len(issues)} issue(s) after fixer")
                else:
                    safe_print(f"[fix-plans] ch{ch}: fixed")
            except Exception as exc:
                safe_print(f"[fix-plans] ch{ch}: fixer failed — {exc}")
        elif issues:
            safe_print(f"[fix-plans] ch{ch} ({done}/{total}): {len(issues)} issue(s) (no LLM)")
        plans[i] = p
        if issues:
            remaining[ch] = issues

    data["chapter_plans"] = plans
    save_master_plan(ws, book, data)
    if remaining:
        safe_print(f"[fix-plans] remaining: {len(remaining)} chapter(s)")
    else:
        safe_print("[fix-plans] all chapters pass QC")
    return remaining


def _resolve_total(ws: Path, direction: dict) -> int:
    from factory.engine.lib.book_config import get_total_chapters

    book = int(direction.get("book") or 1)
    return get_total_chapters(ws.name, book)


def chapter_chunks(direction: dict, chunk_size: int = 3, *, ws: Path | None = None) -> list[tuple[int, int, str]]:
    """Smaller chunks = JSON ổn định hơn từ 9router."""
    canon = int(direction.get("canon_through", 0))
    total = _resolve_total(ws, direction) if ws else int(direction.get("total_chapters", 50))
    start = canon + 1
    chunks: list[tuple[int, int, str]] = []
    while start <= total:
        end = min(start + chunk_size - 1, total)
        chunks.append((start, end, f"ch{start:02d}-{end:02d}"))
        start = end + 1
    return chunks


def act_ranges(direction: dict, *, ws: Path | None = None) -> list[tuple[int, int, str]]:
    arc = direction.get("arc", {})
    canon = int(direction.get("canon_through", 0))
    ranges = []
    for key in ("act1_setup", "act2_complications", "act3_crisis", "act4_resolution"):
        if key not in arc:
            continue
        lo, hi = arc[key]
        start = max(lo, canon + 1)
        if start <= hi:
            ranges.append((start, hi, key))
    if not ranges:
        total = _resolve_total(ws, direction) if ws else int(direction.get("total_chapters", 50))
        start = canon + 1
        if start <= total:
            ranges.append((start, total, "full"))
    return ranges


def load_master_plan(ws: Path, book: int) -> dict:
    path = master_plan_path(ws, book)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data["chapter_plans"] = normalize_chapter_plans(data.get("chapter_plans", []))
        return data
    return {"book": book, "chapter_plans": []}


def save_master_plan(ws: Path, book: int, data: dict) -> Path:
    path = master_plan_path(ws, book)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["chapter_plans"] = normalize_chapter_plans(data.get("chapter_plans", []))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def merge_plans(existing: list[dict], new_plans: list[dict]) -> list[dict]:
    by_ch = {p["chapter"]: normalize_chapter_plan(p) for p in existing}
    for p in new_plans:
        by_ch[normalize_chapter_plan(p)["chapter"]] = normalize_chapter_plan(p)
    return [by_ch[k] for k in sorted(by_ch)]


def initial_prior_plans(ws: Path, direction: dict) -> list[dict]:
    canon = int(direction.get("canon_through", 0))
    if canon <= 0:
        return []
    return [p for p in canon_summaries_for_seed(ws) if p.get("chapter", 0) <= canon]


OUTLINER_MAX_TOKENS = 24576


def _fetch_act_plans(
    ws: Path, book: int, act_from: int, act_to: int, act_name: str
) -> tuple[list[dict], dict]:
    direction = load_direction(ws)
    bible = json.loads(bible_path(ws).read_text(encoding="utf-8"))
    current = load_master_plan(ws, book)
    prior = current.get("chapter_plans", [])
    if not prior:
        prior = initial_prior_plans(ws, direction)

    payload = json.dumps(
        build_outliner_payload(
            ws,
            book,
            act_from,
            act_to,
            act_name,
            bible=bible,
            direction=direction,
            prior=prior,
        ),
        ensure_ascii=False,
        indent=2,
    )
    raw, log = call_9router("outliner", payload, max_tokens=OUTLINER_MAX_TOKENS, direction=direction)
    bd = book_workspace_dir(ws, book)
    raw_path = bd / f"plan_raw_{act_from:03d}_{act_to:03d}.txt"
    raw_path.write_text(raw, encoding="utf-8")
    try:
        result = parse_json_response(raw)
    except json.JSONDecodeError as exc:
        safe_print(f"  [plan] JSON parse fail ch{act_from}-{act_to}: {exc} — thử plan_fixer...")
        repair_payload = json.dumps(
            {
                "broken_json": raw[:20000],
                "parse_error": str(exc),
                "act_range": [act_from, act_to],
                "instruction": "Trả JSON hợp lệ ONLY với key chapter_plans (mảng đủ các chương trong act).",
            },
            ensure_ascii=False,
        )
        repair = call_9router("plan_fixer", repair_payload, max_tokens=OUTLINER_MAX_TOKENS, direction=direction)
        raw_path.with_suffix(".repair.txt").write_text(repair[0], encoding="utf-8")
        try:
            result = parse_json_response(repair[0])
        except json.JSONDecodeError as exc2:
            raise RuntimeError(
                f"Không parse được plan ch{act_from}-{act_to} sau repair. "
                f"Xem {raw_path} và chạy lại: plan --acts {act_from}-{act_to}"
            ) from exc2
    if not isinstance(result, dict):
        raise RuntimeError(
            f"Plan ch{act_from}-{act_to} không phải JSON object. Xem {raw_path}"
        )
    chapter_plans = result.get("chapter_plans")
    if not isinstance(chapter_plans, list):
        # Some models return a bare list of chapter plans
        if isinstance(result.get("chapters"), list):
            chapter_plans = result["chapters"]
        else:
            raise RuntimeError(
                f"Plan ch{act_from}-{act_to} thiếu chapter_plans[]. Xem {raw_path}"
            )
    new_plans = normalize_chapter_plans(merge_narrative_into_plans(ws, chapter_plans))
    return new_plans, log


def plan_act(ws: Path, book: int, act_from: int, act_to: int, act_name: str) -> tuple[list[dict], dict]:
    expected = act_to - act_from + 1
    plans, log = _fetch_act_plans(ws, book, act_from, act_to, act_name)
    if len(plans) >= expected:
        return plans, log

    safe_print(
        f"  [plan] thiếu {len(plans)}/{expected} ch (JSON có thể bị cắt) — tách {act_from}-{act_to} làm 2..."
    )
    if expected <= 1:
        raise RuntimeError(
            f"Outliner trả thiếu plan ch{act_from}. Chạy lại: plan --acts {act_from}-{act_to}"
        )
    mid = (act_from + act_to) // 2
    p1, log1 = _fetch_act_plans(ws, book, act_from, mid, f"{act_name}a")
    p2, log2 = _fetch_act_plans(ws, book, mid + 1, act_to, f"{act_name}b")
    merged = merge_plans(p1, p2)
    if len(merged) < expected:
        raise RuntimeError(
            f"Vẫn thiếu plan sau khi tách ch{act_from}-{act_to} "
            f"({len(merged)}/{expected}). Thử: plan --acts {act_from}-{act_to}"
        )
    return merged, log2


def clear_master_plan_for_replan(ws: Path, book: int) -> Path:
    """Wipe chapter_plans + plan_raw_* and set plan_status=draft so plan_book regenerates."""
    path = master_plan_path(ws, book)
    book_dir = book_workspace_dir(ws, book)
    book_dir.mkdir(parents=True, exist_ok=True)

    data: dict = {"book": book, "chapter_plans": []}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                for key in ("title", "total_chapters", "acts"):
                    if key in prev:
                        data[key] = prev[key]
        except (json.JSONDecodeError, OSError):
            pass
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for raw in book_dir.glob("plan_raw_*.txt"):
        try:
            raw.unlink()
        except OSError:
            pass

    direction_path = ws / "direction.yaml"
    if direction_path.exists():
        direction = yaml.safe_load(direction_path.read_text(encoding="utf-8")) or {}
        direction["plan_status"] = "draft"
        direction_path.write_text(
            yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    return path


def plan_book(
    ws: Path,
    book: int,
    *,
    acts: str = "all",
    chunk_size: int = 3,
    force_replan: bool = False,
) -> tuple[Path, int]:
    direction = load_direction(ws)
    bible = load_series_bible(ws)
    if not bible_is_approved(bible, direction):
        raise RuntimeError(
            "Bible chưa approved. Chạy: validate-bible → (duyệt canon) → approve-bible"
        )

    if force_replan:
        clear_master_plan_for_replan(ws, book)
        safe_print("[plan] force_replan — đã xóa chapter_plans + plan_raw_*, plan_status=draft")

    if acts != "all":
        a, b = acts.split("-", 1)
        ranges = [(int(a), int(b), "custom")]
    else:
        ranges = chapter_chunks(direction, chunk_size=chunk_size)

    data = load_master_plan(ws, book)
    if not data.get("chapter_plans"):
        data["chapter_plans"] = initial_prior_plans(ws, direction)
    data["book"] = book
    data["title"] = data.get("title") or bible.get("title") or bible.get("meta", {}).get("series_id", "")

    existing_chs = {p.get("chapter") for p in data.get("chapter_plans", [])}

    for lo, hi, name in ranges:
        if acts == "all" and all(ch in existing_chs for ch in range(lo, hi + 1)):
            safe_print(f"[plan] skip {name} ch {lo}-{hi} (đã có trong master_plan)")
            continue
        print(f"[plan] act {name}: ch {lo}-{hi}...")
        new_plans, log = plan_act(ws, book, lo, hi, name)
        print(f"  -> {len(new_plans)} chapters ({log.get('usage', {})})")
        data["chapter_plans"] = merge_plans(data["chapter_plans"], new_plans)
        save_master_plan(ws, book, data)
        existing_chs = {p.get("chapter") for p in data["chapter_plans"]}

    data["chapter_plans"] = merge_narrative_into_plans(ws, data.get("chapter_plans", []))
    save_master_plan(ws, book, data)

    # Deterministic QC only here — LLM fix is a separate step (UI fix-plans / CLI).
    # Avoids silent N× plan_fixer calls that look like a hang after plan_raw_*.
    safe_print("[plan] deterministic QC (spice/word-count)…")
    remaining = qc_and_fix_plans(ws, book, use_llm=False)
    if remaining:
        print(f"[plan] plan_qc remaining issues: {len(remaining)} chapters (chạy fix-plans nếu cần)")
    save_master_plan(ws, book, load_master_plan(ws, book))
    safe_print("[plan] render prompts…")
    n = render_all_prompts(ws, book)
    return master_plan_path(ws, book), n


def fix_plans(ws: Path, book: int, *, use_llm: bool = True) -> tuple[dict[int, list[str]], int]:
    remaining = qc_and_fix_plans(ws, book, use_llm=use_llm)
    n = render_all_prompts(ws, book)
    return remaining, n


def approve_plan(ws: Path, book: int | None = None) -> None:
    from factory.engine.lib.canon_registry import CanonRegistryError, validate_plan_against_canon_registry
    from factory.engine.lib.plan_qc import apply_deterministic_plan_fixes, validate_all_plans

    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    conflicts = validate_plan_against_canon_registry(ws, book_num)

    # Full plan QC must also pass — names/spice alone are not enough.
    bible = load_series_bible(ws)
    data = load_master_plan(ws, book_num)
    plans = normalize_chapter_plans(data.get("chapter_plans", []))
    # Attach compiler narrative before QC (plans may predate compiler enablement).
    plans = merge_narrative_into_plans(ws, plans)
    plans = [apply_deterministic_plan_fixes(p, direction) for p in plans]
    data["chapter_plans"] = plans
    save_master_plan(ws, book_num, data)

    remaining = validate_all_plans(plans, direction, bible=bible, ws=ws)
    for ch, issues in sorted(remaining.items()):
        for issue in issues:
            conflicts.append(
                {
                    "code": "plan_qc_fail",
                    "source": f"master_plan.json:ch{ch}",
                    "value": issue,
                    "expected": "plan QC pass before approve",
                }
            )

    if conflicts:
        raise CanonRegistryError(conflicts)

    path = ws / "direction.yaml"
    data_dir = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data_dir["plan_status"] = "approved"
    path.write_text(
        yaml.dump(data_dir, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def plan_is_approved(ws: Path) -> bool:
    return load_direction(ws).get("plan_status") == "approved"
