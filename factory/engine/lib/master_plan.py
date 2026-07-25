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
    chapter_plan_structurally_complete,
    ensure_task_word_count,
    prefer_richer_chapter_plan,
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


def _bible_stub_from_intent(ws: Path, book: int) -> dict:
    """Minimal bible-shaped dict from approved IntentManifest (no AI, no disk write).

    Used when planning with intent-only path (bible optional / not yet generated).
    """
    from factory.engine.lib.intent_manifest import load_intent_manifest
    from factory.engine.lib.narrative_schema import load_concept

    man = load_intent_manifest(ws, book)
    concept = load_concept(ws)
    cast = list(man.get("cast") or [])
    female = cast[0] if cast else "Unassigned"
    male = "Unassigned (no male lead)"

    female_lead: dict = {"name": female}
    supporting: list[dict] = []
    for item in concept.get("characters") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        traits = item.get("traits") or []
        voice = ", ".join(str(t) for t in traits[:4]) if traits else str(item.get("role") or "")
        entry = {
            "name": name,
            "age": item.get("age", ""),
            "voice": voice,
            "tics": list(traits)[:6] if isinstance(traits, list) else [],
            # wound ok for POV; never put antagonist secret into prompt bible
            "boundary": str(item.get("wound") or "")[:180],
            "internal_voice": str(item.get("arc") or "")[:180],
            "role": item.get("role"),
        }
        if name.lower() == female.lower():
            female_lead = {k: v for k, v in entry.items() if k != "role"}
        else:
            # Never dump concept.secret into writer prompts via stub bible —
            # those are late-book truths and would spoil early chapters.
            # Never dump full character arc (end-state) into internal_voice.
            supporting.append(
                {
                    "name": name,
                    "relation_type": str(item.get("role") or "supporting"),
                    "relation_to": female,
                    "alive": str(item.get("status") or "").lower() not in ("deceased", "dead"),
                }
            )

    # Female lead: keep wound/boundary; omit end-state arc from prompt stub
    if female_lead.get("internal_voice"):
        iv = str(female_lead.get("internal_voice") or "")
        if "finally" in iv.lower() or "cuối cùng" in iv.lower():
            female_lead["internal_voice"] = ""

    spice_max = 0
    genre = concept.get("genre") if isinstance(concept.get("genre"), dict) else {}
    if isinstance(genre, dict) and genre.get("spice") is not None:
        try:
            spice_max = int(genre.get("spice"))
        except (TypeError, ValueError):
            spice_max = 0

    return {
        "title": man.get("title") or ws.name,
        "logline": man.get("logline") or "",
        "bible_status": "draft",
        "spice_max": spice_max,
        "leads": {
            "female": female_lead,
            "male": {"name": male},
        },
        "supporting_cast": supporting,
        "cast": [{"name": n} for n in cast],
        "world_rules": [],
        "content_rules": list(man.get("must_avoid") or []),
        "meta": {"source": "intent_manifest_stub"},
    }


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
    """Assemble Outliner request — locked pack only (intent ± approved narrative).

    Does not send raw concept.yaml. Bible is slimmed to titles/cast already locked;
    authority for beats is intent_manifest (+ narrative_lock when approved).
    """
    from factory.engine.lib.canon_registry import locked_canon_names_payload
    from factory.engine.lib.intent_manifest import locked_pack_for_outliner

    slim_direction = {
        k: direction.get(k)
        for k in (
            "target_language",
            "spice_default",
            "spice_level",
            "total_chapters",
            "book",
            "blurb",
            "book1_ending",
            "canon_through",
            "narrative_profile",
            "pen_name",
        )
        if direction.get(k) is not None
    }
    slim_bible = {
        k: bible.get(k)
        for k in ("title", "logline", "leads", "cast", "meta", "spice_max")
        if bible.get(k) is not None
    }
    body: dict = {
        "direction": slim_direction,
        "series_bible": slim_bible,
        "book_number": book,
        "act_range": [act_from, act_to],
        "act_name": act_name,
        "prior_plans": prior,
        "canon_through": direction.get("canon_through", 3),
    }
    locked = locked_canon_names_payload(ws, book)
    if locked:
        body["locked_canon_names"] = locked
    # Primary authority: approved intent pack (raises if missing)
    try:
        body["locked_pack"] = locked_pack_for_outliner(ws, book, act_from, act_to)
    except RuntimeError:
        # Backward-compat during migration: allow plan --force paths without intent
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
        fixed = merged[0] if merged else fixed
    fixed = normalize_chapter_plan(fixed)
    # These fields are intentionally hidden from the fixer. Restore only a
    # missing value from this chapter's prior plan before completeness checks.
    for field in ("spice", "signature_detail_hint"):
        fixed_missing = fixed.get(field) in (None, "", [])
        prior_present = plan.get(field) not in (None, "", [])
        if fixed_missing and prior_present:
            fixed[field] = plan[field]
    # Never accept a fixer result that strips required fields from a complete chapter.
    kept = prefer_richer_chapter_plan(plan, fixed)
    if chapter_plan_structurally_complete(plan) and not chapter_plan_structurally_complete(fixed):
        safe_print(
            f"[fix-plans] ch{plan.get('chapter')}: fixer returned incomplete object — kept prior"
        )
    return kept


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
    """Upsert chapter plans — never replace a complete chapter with a thinner one."""
    by_ch: dict[int, dict] = {}
    for p in existing:
        np = normalize_chapter_plan(p)
        ch = int(np.get("chapter") or 0)
        if ch:
            by_ch[ch] = np
    for p in new_plans:
        np = normalize_chapter_plan(p)
        ch = int(np.get("chapter") or 0)
        if not ch:
            continue
        by_ch[ch] = prefer_richer_chapter_plan(by_ch.get(ch), np)
    return [by_ch[k] for k in sorted(by_ch)]


def chunk_needs_replan(existing_plans: list[dict], lo: int, hi: int) -> bool:
    """True unless every chapter in [lo, hi] is structurally complete."""
    by_ch = {
        int(p.get("chapter") or 0): p
        for p in existing_plans
        if int(p.get("chapter") or 0)
    }
    for ch in range(lo, hi + 1):
        plan = by_ch.get(ch)
        if plan is None or not chapter_plan_structurally_complete(plan):
            return True
    return False


def filter_complete_chapter_plans(plans: list[dict], *, lo: int, hi: int) -> list[dict]:
    """Keep only structurally complete plans in range — refuse partial objects."""
    out: list[dict] = []
    for p in plans:
        np = normalize_chapter_plan(p)
        ch = int(np.get("chapter") or 0)
        if ch < lo or ch > hi:
            continue
        if chapter_plan_structurally_complete(np):
            out.append(np)
        else:
            safe_print(
                f"  [plan] reject incomplete ch{ch} "
                f"(missing required fields / must_happen<3) — not written"
            )
    return out


def initial_prior_plans(ws: Path, direction: dict) -> list[dict]:
    canon = int(direction.get("canon_through", 0))
    if canon <= 0:
        return []
    return [p for p in canon_summaries_for_seed(ws) if p.get("chapter", 0) <= canon]


OUTLINER_MAX_TOKENS = 24576


def _fetch_act_plans(
    ws: Path, book: int, act_from: int, act_to: int, act_name: str
) -> tuple[list[dict], dict]:
    from factory.engine.lib.canon_registry import sync_bible_leads_from_registry
    from factory.engine.lib.prompt_builder import load_series_bible

    sync_bible_leads_from_registry(ws, book)
    direction = load_direction(ws)
    bible = load_series_bible(ws)
    if not bible:
        # Intent-only path: stub bible from locked intent so payload/QC don't crash.
        bible = _bible_stub_from_intent(ws, book)
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
    new_plans = filter_complete_chapter_plans(new_plans, lo=act_from, hi=act_to)
    return new_plans, log


def plan_act(ws: Path, book: int, act_from: int, act_to: int, act_name: str) -> tuple[list[dict], dict]:
    expected = act_to - act_from + 1
    plans, log = _fetch_act_plans(ws, book, act_from, act_to, act_name)
    if len(plans) >= expected:
        return plans, log

    safe_print(
        f"  [plan] thiếu {len(plans)}/{expected} ch hoàn chỉnh (JSON cắt/thiếu field) — "
        f"tách {act_from}-{act_to} làm 2..."
    )
    if expected <= 1:
        raise RuntimeError(
            f"Outliner trả thiếu/incomplete plan ch{act_from}. "
            f"Chạy lại: plan --acts {act_from}-{act_to}"
        )
    mid = (act_from + act_to) // 2
    p1, log1 = _fetch_act_plans(ws, book, act_from, mid, f"{act_name}a")
    p2, log2 = _fetch_act_plans(ws, book, mid + 1, act_to, f"{act_name}b")
    merged = merge_plans(p1, p2)
    complete = filter_complete_chapter_plans(merged, lo=act_from, hi=act_to)
    if len(complete) < expected:
        raise RuntimeError(
            f"Vẫn thiếu plan hoàn chỉnh sau khi tách ch{act_from}-{act_to} "
            f"({len(complete)}/{expected}). Thử: plan --acts {act_from}-{act_to}"
        )
    return complete, log2


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
    require_bible: bool = True,
) -> tuple[Path, int]:
    from factory.engine.lib.canon_registry import sync_bible_leads_from_registry
    from factory.engine.lib.intent_manifest import intent_is_approved

    sync_bible_leads_from_registry(ws, book)
    direction = load_direction(ws)
    bible = load_series_bible(ws)
    if not intent_is_approved(ws, book, direction):
        raise RuntimeError(
            "Intent chưa approved. Chạy: compile-intent → approve-intent"
        )
    if require_bible and not bible_is_approved(bible, direction):
        raise RuntimeError(
            "Bible chưa approved. Chạy: validate-bible → (duyệt canon) → approve-bible "
            "(hoặc plan --force để bỏ qua bible khi đã có intent)"
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
        if acts == "all" and not chunk_needs_replan(data.get("chapter_plans", []), lo, hi):
            safe_print(f"[plan] skip {name} ch {lo}-{hi} (đủ field trong master_plan)")
            continue
        if acts == "all" and any(ch in existing_chs for ch in range(lo, hi + 1)):
            incomplete = [
                ch
                for ch in range(lo, hi + 1)
                if chunk_needs_replan(
                    [p for p in data.get("chapter_plans", []) if p.get("chapter") == ch],
                    ch,
                    ch,
                )
            ]
            safe_print(
                f"[plan] re-plan {name} ch {lo}-{hi} — incomplete: {incomplete or 'range gap'}"
            )
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
        safe_print(f"[plan] plan_qc remaining issues: {len(remaining)} chapters (chay fix-plans neu can)")
    save_master_plan(ws, book, load_master_plan(ws, book))
    safe_print("[plan] render prompts…")
    n = render_all_prompts(ws, book)
    return master_plan_path(ws, book), n


def fix_plans(ws: Path, book: int, *, use_llm: bool = True) -> tuple[dict[int, list[str]], int]:
    remaining = qc_and_fix_plans(ws, book, use_llm=use_llm)
    n = render_all_prompts(ws, book)
    return remaining, n


_EARLY_REVEAL_SOFT_MARKERS = (
    "true_plot_spoil_early",
    "mystery_reveal_too_early",
)


def _soft_intentional_early_reveal(ws: Path, issue: str) -> bool:
    """When concept.intentional_early_reveal, demote two reveal gates to WARN."""
    from factory.engine.lib.narrative_schema import intentional_early_reveal

    if not intentional_early_reveal(ws=ws):
        return False
    return any(m in issue for m in _EARLY_REVEAL_SOFT_MARKERS)


def approve_plan(ws: Path, book: int | None = None) -> None:
    from factory.engine.lib.canon_registry import CanonRegistryError, validate_plan_against_canon_registry
    from factory.engine.lib.catalog import safe_print
    from factory.engine.lib.intent_gates import g3_plan_fidelity_errors, g4_prompt_errors
    from factory.engine.lib.intent_manifest import intent_is_approved, load_intent_manifest
    from factory.engine.lib.plan_qc import apply_deterministic_plan_fixes, validate_all_plans
    from factory.engine.lib.prompt_builder import build_chapter_prompt, prompt_path

    direction = load_direction(ws)
    book_num = int(book if book is not None else direction.get("book") or 1)
    conflicts = validate_plan_against_canon_registry(ws, book_num)

    if not intent_is_approved(ws, book_num, direction):
        conflicts.append(
            {
                "code": "intent_not_approved",
                "source": "intent_manifest.json",
                "value": "missing",
                "expected": "approve-intent before approve-plan",
            }
        )

    # Full plan QC must also pass — names/spice alone are not enough.
    bible = load_series_bible(ws)
    data = load_master_plan(ws, book_num)
    plans = normalize_chapter_plans(data.get("chapter_plans", []))
    # Attach compiler narrative only when Lock1 approved (compiler self-gates).
    plans = merge_narrative_into_plans(ws, plans)
    plans = [apply_deterministic_plan_fixes(p, direction) for p in plans]
    data["chapter_plans"] = plans
    man = load_intent_manifest(ws, book_num)
    if man:
        data["intent_digest"] = man.get("manifest_digest")
        data["intent_concept_digest"] = man.get("concept_digest")
    save_master_plan(ws, book_num, data)

    for err in g3_plan_fidelity_errors(ws, plans, book=book_num):
        conflicts.append(
            {
                "code": "intent_plan_fidelity",
                "source": "master_plan.json",
                "value": err,
                "expected": "plan covers intent chapter_map",
            }
        )

    remaining = validate_all_plans(plans, direction, bible=bible, ws=ws)
    for ch, issues in sorted(remaining.items()):
        for issue in issues:
            if _soft_intentional_early_reveal(ws, str(issue)):
                safe_print(
                    f"  [approve-plan WARN] intentional_early_reveal: {issue}"
                )
                continue
            conflicts.append(
                {
                    "code": "plan_qc_fail",
                    "source": f"master_plan.json:ch{ch}",
                    "value": issue,
                    "expected": "plan QC pass before approve",
                }
            )

    # Atomic with prompt projection (G4): render then verify disk
    n = render_all_prompts(ws, book_num)
    if n <= 0:
        conflicts.append(
            {
                "code": "prompts_missing",
                "source": "prompts/",
                "value": "0",
                "expected": "render prompts before approve",
            }
        )
    else:
        for plan in plans:
            ch = int(plan.get("chapter") or 0)
            if ch <= 0:
                continue
            pp = prompt_path(ws, book_num, ch)
            if not pp.exists():
                conflicts.append(
                    {
                        "code": "prompt_missing",
                        "source": str(pp),
                        "value": "missing",
                        "expected": f"prompts/ch_{ch:03d}.txt",
                    }
                )
                continue
            disk = pp.read_text(encoding="utf-8")
            live = build_chapter_prompt(
                plan,
                prior_plans=[p for p in plans if int(p.get("chapter") or 0) < ch],
                direction=direction,
                chapter=ch,
                series_bible=bible,
                ws=ws,
            )
            for err in g4_prompt_errors(ws, book_num, ch, live, disk_text=disk):
                if _soft_intentional_early_reveal(ws, str(err)):
                    safe_print(
                        f"  [approve-plan WARN] intentional_early_reveal: {err}"
                    )
                    continue
                conflicts.append(
                    {
                        "code": "prompt_fidelity",
                        "source": str(pp),
                        "value": err,
                        "expected": "prompt projection matches lock",
                    }
                )

    if conflicts:
        raise CanonRegistryError(conflicts)

    path = ws / "direction.yaml"
    data_dir = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data_dir["plan_status"] = "approved"
    if man:
        data_dir["plan_intent_digest"] = man.get("manifest_digest")
    path.write_text(
        yaml.dump(data_dir, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def plan_is_approved(ws: Path) -> bool:
    return load_direction(ws).get("plan_status") == "approved"
