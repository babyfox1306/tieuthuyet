#!/usr/bin/env python3
"""Factory CLI — production pipeline + catalog delivery."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.engine.lib.call_9router import (
    call_9router,
    list_models,
    load_role,
    parse_json_response,
    probe_model,
    resolve_priority_chain,
)
from factory.engine.lib.catalog import (
    export_book,
    migrate_from_scripts,
    promote_all,
    promote_chapter,
    repair_catalog_book,
    safe_print,
    sync_pipeline_from_catalog,
    write_morning_report,
)
from factory.engine.lib.epub_qc import format_epub_qc_summary, qc_epub_file
from factory.engine.lib.export_gate import (
    format_export_gate_reasons,
    format_export_gate_summary,
    run_export_gate,
    save_export_gate_report,
)
from factory.engine.lib.master_plan import approve_plan, fix_plans, plan_book, plan_is_approved
from factory.engine.lib.bible_schema import bible_is_approved, validate_bible
from factory.engine.lib.concept_cli import (
    concept_check,
    concept_init,
    concept_interview,
    concept_mark_ready,
    concept_show,
)
from factory.engine.lib.narrative_developer import develop_narrative
from factory.engine.lib.narrative_schema import (
    narrative_is_approved,
    validate_narrative_assets,
)
from factory.engine.lib.machine_qc import (
    format_machine_reasons,
    machine_pass,
    machine_qc,
    save_machine_issues,
    word_count_vi,
)
from factory.engine.lib.plan_normalize import normalize_chapter_plan, normalize_chapter_plans
from factory.engine.lib.prompt_builder import (
    build_chapter_prompt,
    load_direction,
    load_series_bible,
    prompt_path,
    render_all_prompts,
)
from factory.engine.lib.qc_eval import format_qc_reasons, qc_fail_reasons, qc_passes
from factory.engine.lib.state_updater import load_state, save_state, update_state_after_pass
from factory.engine.lib.language import target_language
from factory.engine.lib.write_guards import (
    WriteBlockedError,
    assert_write_allowed,
    format_prior_excerpt_block,
    is_sequential_writes,
    load_prior_chapter_excerpt,
    state_chain_complete,
)
from factory.engine.lib.writer_payload_log import (
    write_writer_payload_artifact,
    writer_source_versions,
)
from factory.engine.paths import (
    bible_path,
    book_catalog_dir,
    book_workspace_dir,
    chapter_pipeline_path,
    load_config,
    pipeline_dir,
    resolve_book_slug,
    workspace_dir,
)


def _cli_book_slug(args: argparse.Namespace, cfg: dict | None = None) -> tuple[int, str]:
    cfg = cfg or load_config()
    book_arg = getattr(args, "book", None)
    book = int(book_arg if book_arg is not None else cfg.get("active_book", 1))
    slug = getattr(args, "book_slug", None) or resolve_book_slug(args.workspace, book, cfg=cfg)
    return book, slug


def load_json(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def issues_path(ws: Path, book: int, bucket: str, ch: int) -> Path:
    return pipeline_dir(ws, book, bucket) / f"ch_{ch:03d}_issues.json"


def qc_report_path(ws: Path, book: int, bucket: str, ch: int) -> Path:
    return pipeline_dir(ws, book, bucket) / f"ch_{ch:03d}_qc.json"


def cmd_develop_narrative(args: argparse.Namespace) -> None:
    try:
        paths = develop_narrative(args.workspace, pass_name=args.pass_name)
    except Exception as exc:
        safe_print(f"[develop-narrative] FAIL — {exc}")
        return
    for p in paths:
        safe_print(f"[develop-narrative] OK -> {p}")
    safe_print("[develop-narrative] narrative_status=draft — đọc JSON, sửa tay nếu cần")
    safe_print("[develop-narrative] Tiếp: validate-narrative → approve-narrative")


def cmd_concept(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    if args.init:
        p = concept_init(ws)
        safe_print(f"[concept] template -> {p}")
        safe_print("[concept] Điền author_directive (có Ch1:/Ch2:…) rồi: concept --ready")
        return
    if args.interview:
        concept_interview(ws)
        return
    if args.check:
        errs = concept_check(ws)
        if errs:
            safe_print(f"[concept] CHUA SAN SANG ({len(errs)}):")
            for e in errs:
                safe_print(f"  - {e}")
        else:
            safe_print("[concept] OK — chay concept --ready → compile-intent")
        return
    if args.ready:
        ok, errs = concept_mark_ready(ws)
        if ok:
            safe_print(f"[concept] concept_status=ready -> {ws / 'concept.yaml'}")
            safe_print("[concept] Tiep: compile-intent → approve-intent")
        else:
            safe_print("[concept] BLOCKED:")
            for e in errs:
                safe_print(f"  - {e}")
        return
    concept_show(ws)


def cmd_compile_intent(args: argparse.Namespace) -> None:
    from factory.engine.lib.intent_manifest import compile_and_save_intent, intent_manifest_path
    from factory.engine.lib.workspace_metadata import sync_direction_from_concept

    ws = workspace_dir(args.workspace)
    # Importers may copy concept.yaml after creating a blank workspace.  Sync
    # direction first so spice/language/profile cannot retain template defaults.
    sync_direction_from_concept(ws, preserve_gate_status=True, force_setting=True)
    book = int(getattr(args, "book", None) or load_direction(ws).get("book") or 1)
    try:
        man = compile_and_save_intent(ws, book=book)
    except ValueError as exc:
        safe_print(f"[compile-intent] BLOCKED — {exc}")
        return
    path = intent_manifest_path(ws, book)
    safe_print(f"[compile-intent] OK -> {path}")
    safe_print(
        f"[compile-intent] chapters_mapped={len(man.get('chapter_map') or [])} "
        f"digest={man.get('manifest_digest')} status=draft"
    )
    safe_print("[compile-intent] Tiep: doc manifest → approve-intent")


def cmd_approve_intent(args: argparse.Namespace) -> None:
    from factory.engine.lib.intent_manifest import approve_intent, intent_manifest_path

    ws = workspace_dir(args.workspace)
    book = int(getattr(args, "book", None) or load_direction(ws).get("book") or 1)
    try:
        man = approve_intent(ws, book=book)
    except ValueError as exc:
        safe_print(f"[approve-intent] BLOCKED — {exc}")
        return
    safe_print(f"[approve-intent] intent_status=approved -> {intent_manifest_path(ws, book)}")
    safe_print(f"[approve-intent] digest={man.get('manifest_digest')}")
    safe_print("[approve-intent] Tiep: develop-narrative (optional) → plan")


def cmd_approve_narrative(args: argparse.Namespace) -> None:
    import yaml

    from factory.engine.lib.intent_gates import g1_narrative_fidelity_errors

    ws = workspace_dir(args.workspace)
    direction = load_direction(ws)
    profile = direction.get("narrative_profile", "")
    if not profile:
        print("[approve-narrative] FAIL — set narrative_profile trong direction.yaml trước")
        return
    errors = validate_narrative_assets(ws, direction)
    if errors:
        print(f"[approve-narrative] BLOCKED — validate-narrative fail ({len(errors)} issues)")
        for e in errors[:10]:
            safe_print(f"  - {e}")
        return
    g1 = g1_narrative_fidelity_errors(ws)
    if g1:
        print(f"[approve-narrative] BLOCKED — G1 fidelity fail ({len(g1)} issues)")
        for e in g1[:15]:
            safe_print(f"  - {e}")
        return
    dir_path = ws / "direction.yaml"
    data = yaml.safe_load(dir_path.read_text(encoding="utf-8")) or {}
    data["narrative_status"] = "approved"
    dir_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    safe_print(f"[approve-narrative] narrative_status=approved -> {dir_path}")
    safe_print("[approve-narrative] Lock1 OK — plan sẽ đọc narrative pack đã khóa")


def cmd_plan(args: argparse.Namespace) -> None:
    from factory.engine.lib.intent_manifest import intent_is_approved

    ws = workspace_dir(args.workspace)
    direction = load_direction(ws)
    bible = load_series_bible(ws)
    if not intent_is_approved(ws, args.book, direction) and not args.force:
        print("[plan] BLOCKED — intent chưa approved.")
        print("        Chạy: compile-intent → approve-intent")
        print("        Hoặc: plan --force (không khuyến khích)")
        return
    # Narrative/bible optional when intent locked; still warn if profile expects them
    if direction.get("narrative_profile") and not narrative_is_approved(direction) and not args.force:
        safe_print(
            "[plan] WARN — narrative chưa approved; plan chỉ bám intent_manifest "
            "(chạy develop-narrative → approve-narrative để tận dụng Lock1)"
        )
    # Locked-chain rule: approved IntentManifest is enough; bible is optional Lock1.
    require_bible = False if intent_is_approved(ws, args.book, direction) else (not args.force)
    if require_bible and not bible_is_approved(bible, direction):
        print("[plan] BLOCKED — bible chưa approved. Chạy: validate-bible → approve-bible")
        print("        Hoặc: plan --force (bỏ qua bible khi đã có intent)")
        return
    force_replan = bool(getattr(args, "replan", False))
    try:
        path, n_prompts = plan_book(
            ws,
            args.book,
            acts=args.acts,
            force_replan=force_replan,
            require_bible=require_bible,
        )
    except RuntimeError as exc:
        print(f"[plan] BLOCKED — {exc}")
        return
    print(f"[plan] OK -> {path}")
    print(f"[plan] rendered {n_prompts} prompts in {book_workspace_dir(ws, args.book) / 'prompts'}")
    safe_print("[plan] Doc luot prompts/ roi: approve-plan")


def cmd_validate_narrative(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    direction = load_direction(ws)
    profile = direction.get("narrative_profile", "")
    if not profile:
        safe_print("[validate-narrative] SKIP — chưa set narrative_profile trong direction.yaml")
        return
    errors = validate_narrative_assets(ws, direction)
    if errors:
        print(f"[validate-narrative] FAIL ({len(errors)} issues):")
        for e in errors:
            safe_print(f"  - {e}")
    else:
        safe_print("[validate-narrative] PASS — đủ file + sanity check OK")
        if not narrative_is_approved(direction):
            safe_print("  (chưa approved — đọc bible/narrative/ rồi: approve-narrative)")


def cmd_architect(args: argparse.Namespace) -> None:
    from factory.engine.lib.bible_architect import generate_bible_with_retry

    ws = workspace_dir(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    result = generate_bible_with_retry(ws)
    if result.get("ok"):
        print(
            f"[architect] OK -> {bible_path(ws)} "
            f"(attempts={result.get('attempts')})"
        )
        safe_print("[architect] Chạy tiếp: validate-bible → approve-bible → plan")
        return
    print(f"[architect] FAIL after {result.get('attempts')} attempts:")
    for e in result.get("errors") or []:
        safe_print(f"  - {e}")
    raise SystemExit(1)


def cmd_validate_bible(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    path = bible_path(ws)
    if not path.exists():
        print(f"[validate-bible] FAIL — missing {path}")
        return
    bible = load_json(path)
    direction = load_direction(ws)
    from factory.engine.lib.narrative_schema import load_concept

    errors = validate_bible(bible, concept=load_concept(ws))
    if errors:
        print(f"[validate-bible] FAIL ({len(errors)} issues):")
        for e in errors:
            safe_print(f"  - {e}")
    else:
        safe_print("[validate-bible] PASS — schema + luật bất biến OK")
        if not bible_is_approved(bible, direction):
            safe_print("  (chưa approved — chạy approve-bible sau khi duyệt canon)")


def cmd_approve_bible(args: argparse.Namespace) -> None:
    import yaml

    ws = workspace_dir(args.workspace)
    path = bible_path(ws)
    if not path.exists():
        print(f"[approve-bible] FAIL — missing {path}")
        return
    bible = load_json(path)
    from factory.engine.lib.narrative_schema import load_concept

    errors = validate_bible(bible, concept=load_concept(ws))
    if errors:
        print(f"[approve-bible] BLOCKED — validate-bible fail ({len(errors)} issues)")
        for e in errors[:10]:
            safe_print(f"  - {e}")
        return
    bible["bible_status"] = "approved"
    save_json(path, bible)
    dir_path = ws / "direction.yaml"
    if dir_path.exists():
        data = yaml.safe_load(dir_path.read_text(encoding="utf-8")) or {}
        data["bible_status"] = "approved"
        dir_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    print(f"[approve-bible] bible_status=approved -> {path}")
    from factory.engine.lib.canon_registry import scaffold_canon_registry

    canon = scaffold_canon_registry(ws, force=False)
    safe_print(f"[approve-bible] canon: {canon.get('message')}")


def cmd_init_canon_registry(args: argparse.Namespace) -> None:
    from factory.engine.lib.canon_registry import scaffold_canon_registry

    ws = workspace_dir(args.workspace)
    result = scaffold_canon_registry(ws, force=bool(getattr(args, "force", False)))
    safe_print(f"[init-canon-registry] {result.get('message')}")
    print(f"[init-canon-registry] -> {result.get('path')}")


def cmd_outline(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    direction = load_direction(ws)
    bible = load_json(bible_path(ws))
    prev = ""
    if args.book > 1:
        prev_path = book_workspace_dir(ws, args.book - 1) / "outline.json"
        if prev_path.exists():
            prev = prev_path.read_text(encoding="utf-8")[:2000]
    user = json.dumps(
        {"series_bible": bible, "book_number": args.book, "previous_book_summary": prev, "direction": direction},
        ensure_ascii=False,
    )
    raw, _ = call_9router("outliner", user, max_tokens=16384, direction=direction)
    outline = parse_json_response(raw)
    out = book_workspace_dir(ws, args.book) / "outline.json"
    save_json(out, outline)
    print(f"[outline] OK -> {out} beats={len(outline.get('chapter_beats', []))}")


def _clear_chapter_pipeline(ws: Path, book: int, ch: int) -> None:
    """Remove stale drafts before a rewrite."""
    bd = book_workspace_dir(ws, book) / "pipeline"
    for bucket in ("needs_fix", "needs_review", "draft"):
        for pattern in (f"ch_{ch:03d}.txt", f"ch_{ch:03d}_qc.json", f"ch_{ch:03d}_issues.json"):
            p = bd / bucket / pattern
            if p.exists():
                p.unlink()


def build_writer_payload(ws: Path, book: int, ch: int, cfg: dict) -> str:
    """Writer authority = sealed writer_request.json when present; else legacy disk prompt."""
    from factory.engine.lib.canonical_ir import load_canonical_ir
    from factory.engine.lib.chapter_contract import (
        assert_writer_artifacts_ready,
        load_writer_packet,
        render_writer_prompt_from_packet,
    )
    from factory.engine.lib.intent_gates import (
        assert_prompt_matches_disk,
        g4_prompt_errors,
        is_prompt_hand_locked,
        strip_prompt_hand_lock_banner,
    )

    direction = load_direction(ws)
    lang = target_language(direction, cfg)
    ir = load_canonical_ir(ws)
    packet = load_writer_packet(ws, book, ch)
    if ir and packet:
        assert_writer_artifacts_ready(ws, book, ch, str(ir.get("ir_digest") or ""))
        prompt = render_writer_prompt_from_packet(packet)
        # Keep legacy disk prompt as debug companion when present.
        pp = prompt_path(ws, book, ch)
        if pp.exists():
            prompt += (
                "\n\n---\n## LEGACY PROMPT (debug only — packet is authority)\n"
                + pp.read_text(encoding="utf-8")
            )
    else:
        pp = prompt_path(ws, book, ch)
        if not pp.exists():
            raise FileNotFoundError(
                f"Missing prompt {pp} — chạy `plan` + `render-prompts` trước"
            )
        disk_prompt = pp.read_text(encoding="utf-8")
        if is_prompt_hand_locked(disk_prompt):
            prompt = strip_prompt_hand_lock_banner(disk_prompt)
        else:
            plan = load_chapter_plan(ws, book, ch)
            plan_path = book_workspace_dir(ws, book) / "master_plan.json"
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            plans = normalize_chapter_plans(
                data.get("chapter_plans", data.get("chapter_beats", []))
            )
            prior = [p for p in plans if p.get("chapter", 0) < ch]
            live = build_chapter_prompt(
                plan,
                prior_plans=prior,
                direction=direction,
                chapter=ch,
                cfg=cfg,
                series_bible=load_series_bible(ws),
                ws=ws,
            )
            assert_prompt_matches_disk(disk_prompt, live, ch)
            prompt = disk_prompt

        prompt_errors = g4_prompt_errors(ws, book, ch, prompt)
        if prompt_errors:
            raise RuntimeError(
                "Writer prompt blocked by reveal/fidelity gate: "
                + "; ".join(prompt_errors)
            )

    excerpt = load_prior_chapter_excerpt(ws, book, ch)
    if excerpt:
        prompt += format_prior_excerpt_block(excerpt, lang=lang)
    state = load_state(ws, book)
    # Only verified facts may appear as canon in state mirror.
    verified = state.get("verified_facts") if isinstance(state, dict) else None
    state_view = {
        "current_chapter": state.get("current_chapter"),
        "current_book": state.get("current_book"),
        "verified_facts": verified or [],
        "locked_names": state.get("locked_names") or {},
        "open_threads": state.get("open_threads") or [],
    }
    from factory.engine.lib.locked_names import (
        format_locked_names_block,
        merge_locked_names,
        seed_locked_names_from_plan,
    )
    from factory.engine.lib.state_updater import save_state

    seeded = seed_locked_names_from_plan(ws, book)
    if seeded:
        merged = merge_locked_names(state.get("locked_names"), seeded)
        if merged != (state.get("locked_names") or {}):
            state = dict(state)
            state["locked_names"] = merged
            save_state(ws, book, state)
            state_view["locked_names"] = merged

    locked_block = format_locked_names_block(
        state.get("locked_names") if isinstance(state.get("locked_names"), dict) else {},
        lang=lang,
    )
    if locked_block:
        prompt += "\n\n" + locked_block
    return (
        prompt
        + "\n\n---\n## STORY_STATE (verified only — không được mâu thuẫn)\n```json\n"
        + json.dumps(
            {
                "story_state": state_view,
                "banned_phrases": cfg.get("banned_phrases", []),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n```\n"
    )


def load_chapter_plan(ws: Path, book: int, ch: int) -> dict:
    path = book_workspace_dir(ws, book) / "master_plan.json"
    if not path.exists():
        return {"chapter": ch}
    data = json.loads(path.read_text(encoding="utf-8"))
    for p in data.get("chapter_plans", []):
        if p.get("chapter") == ch:
            return normalize_chapter_plan(p)
    return {"chapter": ch}


def build_qc_payload(ws: Path, book: int, chapter: str, chapter_num: int) -> str:
    direction = load_direction(ws)
    prior = load_prior_chapter_excerpt(ws, book, chapter_num)

    # Collect concept-driven content boundaries for LLM QC comprehension check
    must_avoid: list[str] = []
    try:
        from factory.engine.lib.narrative_schema import load_concept
        concept = load_concept(ws)
        for item in concept.get("must_avoid") or []:
            if str(item).strip():
                must_avoid.append(str(item).strip())
    except Exception:
        pass

    # Also pull content_rules from bible
    try:
        bible = load_json(bible_path(ws))
        for item in (bible or {}).get("content_rules") or []:
            entry = str(item).strip()
            if entry and entry not in must_avoid:
                must_avoid.append(entry)
    except Exception:
        bible = {}

    from factory.engine.lib.canon_registry import resolve_spice_max_from_direction

    spice_max = resolve_spice_max_from_direction(direction)

    def _qc_bible() -> dict:
        b = load_json(bible_path(ws))
        if b:
            return b
        from factory.engine.lib.master_plan import _bible_stub_from_intent

        return _bible_stub_from_intent(ws, book)

    return json.dumps(
        {
            "chapter_number": chapter_num,
            "chapter": chapter,
            "series_bible": _qc_bible(),
            "story_state": load_state(ws, book),
            "prior_chapter_excerpt": prior,
            "target_language": direction.get("target_language"),
            "spice_max": spice_max,
            "content_boundaries": must_avoid,
        },
        ensure_ascii=False,
    )


def _expand_short_patch(cfg: dict, word_count: int, attempt: int) -> str:
    min_w = int(cfg.get("min_word_count", 1250))
    target = cfg.get("max_word_count", 2200)
    lang = cfg.get("default_target_language", "en")
    if lang == "vi":
        return (
            f"\n\n[VIẾT LẠI — lần {attempt + 1}] Bản trước chỉ {word_count} chữ. "
            f"BẮT BUỘC tối thiểu {min_w} chữ (mục tiêu 1600–1900). "
            "Mở rộng bằng đối thoại, nội tâm, chi tiết cảm giác — KHÔNG tóm tắt, KHÔNG skip scene."
        )
    return (
        f"\n\n[REVISION — attempt {attempt + 1}] Previous draft was only {word_count} words. "
        f"REQUIRED minimum {min_w} words (target 1600–1900, cap ~{target}). "
        "Expand with dialogue, internal monologue, and sensory detail — do NOT summarize or skip scenes."
    )


def _length_full_rewrite_patch(cfg: dict, word_count: int, attempt: int) -> str:
    """Stronger than expand suffix — demand a full new draft at min length."""
    min_w = int(cfg.get("min_word_count", 1250))
    lang = cfg.get("default_target_language", "en")
    if lang == "vi":
        return (
            f"\n\n[VIẾT LẠI TOÀN BỘ — length {attempt + 1}] "
            f"Bản trước CHỈ {word_count}/{min_w} chữ — KHÔNG ĐẠT. "
            f"Viết LẠI CẢ CHƯƠNG từ đầu, tối thiểu {min_w} chữ. "
            "Cấm bản ngắn / tóm tắt. Mỗi beat trong plan phải có scene đầy đủ."
        )
    return (
        f"\n\n[FULL REWRITE — length attempt {attempt + 1}] "
        f"Previous draft was ONLY {word_count}/{min_w} words — REJECTED. "
        f"Rewrite the ENTIRE chapter from scratch, minimum {min_w} words. "
        "No short summaries. Every plan beat must be a full scene."
    )


def _markdown_patch(lang: str, attempt: int, samples: list[str]) -> str:
    sample = ", ".join(samples[:2]) if samples else "*italics*"
    if lang == "vi":
        return (
            f"\n\n[VIẾT LẠI — lần {attempt + 1}] Bản trước còn markdown ({sample}). "
            "XÓA HẾT dấu * ** ` và # heading trong thân chương. Chỉ văn bản thuần + tiêu đề `# Chương N`."
        )
    return (
        f"\n\n[REVISION — attempt {attempt + 1}] Previous draft had markdown ({sample}). "
        "Remove ALL * ** ` and # headings from body prose. Plain text only (chapter title `# Chapter N` is OK)."
    )


def _pov_patch(lang: str, attempt: int, count: int) -> str:
    if lang == "vi":
        return (
            f"\n\n[VIẾT LẠI — lần {attempt + 1}] Bản trước dùng ngôi thứ nhất ngoài thoại "
            f"({count} hits). Viết lại toàn bộ ở ngôi thứ BA limited. "
            'CẤM narration "tôi/tớ/mình" ngoài đoạn hội thoại trong ngoặc kép.'
        )
    return (
        f"\n\n[REVISION — attempt {attempt + 1}] Previous draft used first-person narration "
        f"outside dialogue ({count} hits). Rewrite entirely in THIRD-PERSON limited. "
        'NO "I/my/me" narration outside quoted dialogue.'
    )


def _foreign_chars_patch(lang: str, attempt: int, samples: list[str]) -> str:
    sample = ", ".join(samples[:5]) if samples else "non-target script"
    if lang == "vi":
        return (
            f"\n\n[VIẾT LẠI — lần {attempt + 1}] Bản trước có ký tự ngoại ngữ ({sample}). "
            "Xóa hết; chỉ dùng chữ của ngôn ngữ đích."
        )
    return (
        f"\n\n[REVISION — attempt {attempt + 1}] Previous draft had foreign characters ({sample}). "
        "Remove them; write only in the target language script."
    )


def _content_fail_patch(lang: str, attempt: int, issues: dict) -> str:
    """Revision hint for content_fail retries (POV, name drift, etc.)."""
    bits: list[str] = []
    if "pov_violation" in issues:
        pv = issues.get("pov_violation") or {}
        count = int(pv.get("count") or 0) if isinstance(pv, dict) else 0
        bits.append(_pov_patch(lang, attempt, count).strip())
    if "name_drift" in issues:
        hits = issues.get("name_drift") or []
        samples = []
        for h in hits[:4]:
            if isinstance(h, dict):
                samples.append(f"{h.get('found')}→{h.get('canonical')}")
        sample = ", ".join(samples) or "forbidden alias"
        if lang == "vi":
            bits.append(
                f"[VIẾT LẠI — lần {attempt + 1}] Name drift ({sample}). "
                "Chỉ dùng tên canonical trong LOCKED CANON; xóa mọi alias cấm."
            )
        else:
            bits.append(
                f"[REVISION — attempt {attempt + 1}] Name drift ({sample}). "
                "Use ONLY canonical names from LOCKED CANON; remove forbidden aliases."
            )
    if "invented_character" in issues:
        names = ", ".join(
            str(hit.get("name") or hit)
            for hit in (issues.get("invented_character") or [])[:5]
        )
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Remove invented characters "
            f"({names}). Use only named cast in LOCKED CANON; unnamed incidental "
            "roles are allowed only when the chapter contract requires them."
        )
    if "unsupported_case_fact" in issues:
        facts = ", ".join(
            str(item) for item in (issues.get("unsupported_case_fact") or [])[:8]
        )
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Remove unsupported case facts "
            f"({facts}). Do not invent evidence, prior relationships, locations, "
            "dates, money, investigations, or backstory absent from this chapter's "
            "locked plan."
        )
        if False:  # unreachable legacy branch; kept out of retry output
            bits.append(
                f"[REVISION — attempt {attempt + 1}] Name drift ({sample}). "
                "Use ONLY canonical names from LOCKED CANON; remove forbidden aliases."
            )
    if "repeat" in issues:
        phrases = ", ".join(str(p) for p in (issues.get("repeat") or [])[:3])
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Remove banned repeated phrases: {phrases}."
        )
    if "must_happen_miss" in issues:
        misses = issues.get("must_happen_miss") or []
        samples = []
        for m in misses[:3]:
            if isinstance(m, dict):
                samples.append(str(m.get("must_happen") or "")[:80])
        sample = "; ".join(samples) or "locked beats"
        if lang == "vi":
            bits.append(
                f"[VIẾT LẠI — lần {attempt + 1}] Thiếu MUST HAPPEN khóa ({sample}). "
                "Viết ĐỦ mọi mục thành scene — cấm bỏ / đổi nhánh."
            )
        else:
            bits.append(
                f"[REVISION — attempt {attempt + 1}] Missing locked MUST HAPPEN ({sample}). "
                "Realize EVERY item as on-page scene — do not drop or swap branches."
            )
    if "technical_chapter_reference" in issues:
        hit = str(issues.get("technical_chapter_reference") or "")
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Remove the non-diegetic planning "
            f"label {hit!r}. Narration must refer to the actual event, evidence, "
            "or elapsed time—never Chapter N."
        )
    if "publication_duplicate_block" in issues:
        samples = []
        for hit in (issues.get("publication_duplicate_block") or [])[:2]:
            if isinstance(hit, dict):
                samples.append(
                    str(hit.get("snippet") or hit.get("detail") or "")[:120]
                )
        sample = " | ".join(samples)
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Remove repeated prose blocks"
            + (f" near: {sample}" if sample else "")
            + ". Execute each reveal and cliffhanger once; do not restate an "
            "earlier paragraph at the ending."
        )
    # Generic content leftovers
    other = [
        k
        for k in (issues.get("classification") or {}).get("content_fail", {})
        if k not in ("pov_violation", "name_drift", "repeat")
    ]
    if other and not bits:
        keys = ", ".join(other[:5])
        bits.append(
            f"[REVISION — attempt {attempt + 1}] Fix content violations: {keys}. "
            "Obey LOCKED CANON / bible rules exactly."
        )
    return "\n\n" + "\n".join(bits) if bits else ""


def _draft_chapter_prose(
    ws: Path,
    book: int,
    ch: int,
    cfg: dict,
    direction: dict,
    *,
    auto: bool = False,
) -> tuple[str, dict]:
    """Call writer; short → expand then full rewrite; format_only → no rewrite; content capped.

    auto=True → content + length full rewrites use writer_auto_max_retries (default 10).
    """
    from factory.engine.lib.machine_qc import (
        classify_machine_issues,
        has_content_fail,
        is_format_only_issues,
    )

    base_payload = build_writer_payload(ws, book, ch, cfg)
    system_message = load_role("writer", direction=direction, cfg=cfg)
    source_versions = writer_source_versions(ws, book)
    max_tokens = int(cfg.get("writer_max_tokens", 16384))
    short_retries = int(cfg.get("writer_short_retries", 2))
    # Full rewrites when expand patches still leave chapter under min (default 3).
    length_max = int(cfg.get("writer_length_max_retries", 3))
    if length_max < 1:
        length_max = 1
    content_max = int(cfg.get("writer_content_max_retries", 2))
    if content_max < 1:
        content_max = 1
    if auto:
        auto_max = int(cfg.get("writer_auto_max_retries", 10))
        if auto_max < 1:
            auto_max = 1
        content_max = auto_max
        length_max = auto_max

    chapter = ""
    m_issues: dict = {}
    expand_suffix = ""
    content_suffix = ""
    lang = target_language(direction, cfg)
    content_attempts = 0
    short_used = 0
    length_rewrites = 0
    attempt_number = 0

    max_rounds = content_max + short_retries + length_max + 2

    def _meta() -> dict:
        return {
            "content_attempts": content_attempts,
            "max_content_retries": content_max,
            "short_expands": short_used,
            "max_short_retries": short_retries,
            "length_rewrites": length_rewrites,
            "max_length_retries": length_max,
        }

    for _round in range(max_rounds):
        attempt_number += 1
        retry_suffix = expand_suffix + content_suffix
        user_content = base_payload + retry_suffix
        try:
            raw, call_meta = call_9router(
                "writer",
                user_content,
                max_tokens=max_tokens,
                direction=direction,
            )
            write_writer_payload_artifact(
                ws,
                book,
                ch,
                attempt_number=attempt_number,
                system_message=system_message,
                user_payload=base_payload,
                retry_suffix=retry_suffix,
                model_called=call_meta.get("model") if isinstance(call_meta, dict) else None,
                source_versions=source_versions,
                output=raw,
                error=None,
            )
        except Exception as call_exc:
            write_writer_payload_artifact(
                ws,
                book,
                ch,
                attempt_number=attempt_number,
                system_message=system_message,
                user_payload=base_payload,
                retry_suffix=retry_suffix,
                model_called=None,
                source_versions=source_versions,
                output=None,
                error=str(call_exc),
            )
            raise
        chapter = raw.strip()
        state = load_state(ws, book)
        m_issues = machine_qc(
            chapter,
            min_words=cfg["min_word_count"],
            banned_phrases=cfg.get("banned_phrases", []),
            phrases_already_used=state.get("phrases_used", []),
            direction=direction,
            cfg=cfg,
            workspace_id=ws.name,
            book=book,
            chapter=ch,
            publication_safety=True,
        )
        cls = classify_machine_issues(m_issues)
        m_issues["classification"] = cls
        m_issues["retry_meta"] = _meta()

        if machine_pass(m_issues):
            return chapter, m_issues

        # Length ALWAYS first — never treat short like format hand-fix / never stop early
        if cls["has_length"]:
            wc = int(m_issues.get("word_count") or word_count_vi(chapter))
            if short_used < short_retries:
                short_used += 1
                print(
                    f"  ch_{ch:03d} SHORT ({wc} words) — expand "
                    f"{short_used}/{short_retries}"
                )
                expand_suffix = _expand_short_patch(cfg, wc, short_used)
                content_suffix = ""
                m_issues["retry_meta"] = _meta()
                continue
            if length_rewrites < length_max:
                length_rewrites += 1
                print(
                    f"  ch_{ch:03d} SHORT ({wc} words) — FULL REWRITE "
                    f"{length_rewrites}/{length_max} (expand chưa đủ)"
                )
                expand_suffix = ""
                content_suffix = _length_full_rewrite_patch(cfg, wc, length_rewrites - 1)
                m_issues["retry_meta"] = _meta()
                continue
            safe_print(
                f"  ch_{ch:03d} LENGTH_CAP — vẫn {wc} < min sau "
                f"{short_used} expand + {length_rewrites} rewrite — "
                "needs_fix (KHÔNG cho qua ready; không phải lỗi dấu *)"
            )
            return chapter, m_issues

        # Format-only (length OK) → stop; operator hand-fixes * / quotes (save tokens)
        if is_format_only_issues(m_issues) or (
            cls["has_format"] and not cls["has_content"]
        ):
            safe_print(
                f"  ch_{ch:03d} FORMAT_FIX — no rewrite "
                f"({', '.join(cls['format_fix'].keys())})"
            )
            return chapter, m_issues

        # Content fail → regenerate up to writer_content_max_retries
        if has_content_fail(m_issues):
            content_attempts += 1
            m_issues["retry_meta"] = _meta()
            m_issues["retry_meta"]["content_attempts"] = content_attempts
            if content_attempts >= content_max:
                safe_print(
                    f"  ch_{ch:03d} CONTENT_CAP — stop after {content_attempts}/{content_max} "
                    f"({', '.join(cls['content_fail'].keys())})"
                )
                return chapter, m_issues
            print(
                f"  ch_{ch:03d} CONTENT — retry {content_attempts}/{content_max} "
                f"({', '.join(cls['content_fail'].keys())})"
            )
            content_suffix = _content_fail_patch(lang, content_attempts - 1, m_issues)
            expand_suffix = ""
            continue

        return chapter, m_issues

    m_issues["retry_meta"] = _meta()
    return chapter, m_issues


def write_one_chapter(
    ws: Path,
    book: int,
    ch: int,
    cfg: dict,
    workspace_id: str,
    *,
    force: bool = False,
    auto: bool = False,
) -> tuple[int, str]:
    from factory.engine.lib.machine_qc import (
        classify_machine_issues,
        has_content_fail,
        is_format_only_issues,
    )

    direction = load_direction(ws)
    beat = load_chapter_plan(ws, book, ch)
    if chapter_pipeline_path(ws, book, "ready", ch).exists():
        print(f"  ch_{ch:03d} SKIP (already ready)")
        return ch, "skipped"

    if not force:
        assert_write_allowed(ws, book, ch, cfg)

    _clear_chapter_pipeline(ws, book, ch)

    print(f"  ch_{ch:03d} writing...")
    chapter, m_issues = _draft_chapter_prose(
        ws, book, ch, cfg, direction, auto=auto
    )
    time.sleep(cfg.get("throttle_seconds", 4))

    if not machine_pass(m_issues):
        cls = m_issues.get("classification") or classify_machine_issues(m_issues)
        reasons = format_machine_reasons(m_issues)

        # Content exhausted → needs_review (operator decides). Format/length → needs_fix.
        if has_content_fail(m_issues) and not is_format_only_issues(m_issues):
            # Prefer content-only path to review; if also format, still review with both notes
            chapter_pipeline_path(ws, book, "needs_review", ch).write_text(
                chapter, encoding="utf-8"
            )
            save_machine_issues(issues_path(ws, book, "needs_review", ch), m_issues)
            meta = m_issues.get("retry_meta") or {}
            qc = {
                "verdict": "FAIL",
                "fail_reasons": reasons,
                "source": "machine_content_cap",
                "content_retries": meta.get("content_attempts"),
                "max_content_retries": meta.get("max_content_retries"),
                "classification": cls,
            }
            save_json(qc_report_path(ws, book, "needs_review", ch), qc)
            safe_print(
                f"  ch_{ch:03d} NEEDS_REVIEW (content_fail) — "
                + ("; ".join(reasons) or str(list(cls.get("content_fail", {}))))
            )
            return ch, "needs_review"

        chapter_pipeline_path(ws, book, "needs_fix", ch).write_text(chapter, encoding="utf-8")
        save_machine_issues(issues_path(ws, book, "needs_fix", ch), m_issues)
        safe_print(f"  ch_{ch:03d} NEEDS_FIX — {'; '.join(reasons) or list(m_issues.keys())}")
        return ch, "needs_fix"

    # P1: Machine Canon Claim Gate before literary QC / Fixer LLM.
    from factory.engine.lib.canonical_ir import load_canonical_ir
    from factory.engine.lib.prose_claim_gate import run_prose_claim_gate

    ir = load_canonical_ir(ws)
    canon = None
    if ir:
        from factory.engine.lib.canon_ops import (
            assert_chapter_not_stale,
            classify_error_layer,
            should_skip_literary_fixer,
        )

        try:
            assert_chapter_not_stale(ws, book, ch, str(ir.get("ir_digest") or ""))
        except RuntimeError as exc:
            chapter_pipeline_path(ws, book, "needs_fix", ch).write_text(
                chapter, encoding="utf-8"
            )
            save_json(
                qc_report_path(ws, book, "needs_fix", ch),
                {
                    "error_layer": classify_error_layer(str(exc)),
                    "stale": True,
                    "detail": str(exc),
                    "skip_literary_fixer": True,
                },
            )
            safe_print(f"  ch_{ch:03d} NEEDS_FIX — {exc}")
            return ch, "needs_fix"

        canon = run_prose_claim_gate(ws, book, ch, chapter, ir)
        if canon.get("status") != "pass":
            _ = should_skip_literary_fixer(canon)
            chapter_pipeline_path(ws, book, "needs_fix", ch).write_text(
                chapter, encoding="utf-8"
            )
            save_json(
                qc_report_path(ws, book, "needs_fix", ch),
                {
                    "canon_qc": canon,
                    "error_layer": classify_error_layer("canon_qc fail"),
                    "skip_literary_fixer": True,
                },
            )
            viol = [
                f"{v.get('reason')}:{v.get('claim')}"
                for v in (canon.get("violations") or [])[:5]
            ]
            safe_print(f"  ch_{ch:03d} NEEDS_FIX — canon_qc: {'; '.join(viol)}")
            return ch, "needs_fix"

    qc_raw, _ = call_9router("qc", build_qc_payload(ws, book, chapter, ch), max_tokens=4096, direction=direction)
    time.sleep(cfg.get("throttle_seconds", 4))
    try:
        qc = parse_json_response(qc_raw)
    except json.JSONDecodeError:
        qc = {"verdict": "FAIL", "fail_reasons": ["qc_json_parse_error"]}

    hard_fail = qc_fail_reasons(qc)
    if hard_fail:
        qc.setdefault("fail_reasons", [])
        for r in hard_fail:
            if r not in qc["fail_reasons"]:
                qc["fail_reasons"].append(r)
        qc["verdict"] = "FAIL"

    if not qc_passes(qc):
        chapter_pipeline_path(ws, book, "needs_review", ch).write_text(chapter, encoding="utf-8")
        save_json(qc_report_path(ws, book, "needs_review", ch), qc)
        reasons = format_qc_reasons(qc)
        safe_print(f"  ch_{ch:03d} NEEDS_REVIEW — {'; '.join(reasons) or qc.get('fail_reasons', [])}")
        return ch, "needs_review"

    if ir and canon and canon.get("status") == "pass":
        from factory.engine.lib.prose_settlement import (
            build_settlement,
            load_settlement,
            write_settlement,
        )
        from factory.engine.lib.story_intelligence import compile_chapter_intelligence

        prior = load_settlement(ws, book, ch - 1)
        intel = compile_chapter_intelligence(ir, ch, prior_settlement=prior)
        settlement = build_settlement(
            chapter=ch,
            canon_qc=canon,
            intelligence=intel,
            prose_len=len(chapter),
            ir=ir,
        )
        write_settlement(ws, book, ch, settlement)

    chapter_pipeline_path(ws, book, "ready", ch).write_text(chapter, encoding="utf-8")
    save_json(qc_report_path(ws, book, "ready", ch), qc)
    if state_chain_complete(ws, book, ch):
        try:
            update_state_after_pass(ws, ch, chapter, book=book)
        except Exception as exc:
            # Fail closed when IR provenance pipeline is active.
            if ir:
                chapter_pipeline_path(ws, book, "needs_fix", ch).write_text(
                    chapter, encoding="utf-8"
                )
                safe_print(f"  ch_{ch:03d} NEEDS_FIX — state update failed (no fail-open): {exc}")
                return ch, "needs_fix"
            safe_print(f"  ch_{ch:03d} WARN state update failed: {exc}")
    else:
        print(
            f"  ch_{ch:03d} READY (state deferred — chưa đủ chuỗi ready 1..{ch - 1}; sửa gap rồi reconcile)"
        )
    promote_out, promote_reasons = promote_chapter(workspace_id, book, ch, auto=True)
    if promote_out is None and promote_reasons:
        safe_print(
            f"  ch_{ch:03d} READY nhưng promote bị chặn — "
            + "; ".join(promote_reasons[:3])
        )
        print(f"  ch_{ch:03d} READY (chưa catalog — bấm Duyệt sau khi sửa) (~{word_count_vi(chapter)} words)")
    elif promote_out is None:
        print(f"  ch_{ch:03d} READY (catalog đã có hoặc thiếu ready file) (~{word_count_vi(chapter)} words)")
    else:
        print(f"  ch_{ch:03d} READY + auto-promoted (~{word_count_vi(chapter)} words)")
    return ch, "ready"


def cmd_write(args: argparse.Namespace) -> None:
    cfg = load_config()
    ws = workspace_dir(args.workspace)
    if not plan_is_approved(ws) and not args.force:
        print("[write] BLOCKED — plan chưa approved. Chạy: plan → đọc prompts → approve-plan")
        print("        Hoặc: write --force (không khuyến khích)")
        return
    chapters = list(range(args.from_chapter, args.to_chapter + 1))
    if not chapters:
        print("No chapters in range.")
        return
    counts: dict[str, int] = {}
    for ch in chapters:
        try:
            _, status = write_one_chapter(
                ws, args.book, ch, cfg, args.workspace, force=args.force
            )
        except WriteBlockedError as exc:
            print(f"  ch_{ch:03d} BLOCKED: {exc}")
            counts["blocked"] = counts.get("blocked", 0) + 1
            if is_sequential_writes(cfg):
                break
            continue
        counts[status] = counts.get(status, 0) + 1
    print(f"\n[write] done: {counts}")


def cmd_approve_plan(args: argparse.Namespace) -> None:
    from factory.engine.lib.canon_registry import CanonRegistryError, format_conflicts

    ws = workspace_dir(args.workspace)
    direction = load_direction(ws)
    book = int(getattr(args, "book", None) or direction.get("book") or 1)
    try:
        approve_plan(ws, book=book)
    except CanonRegistryError as exc:
        print(f"[approve-plan] BLOCKED — {len(exc.conflicts)} canon conflict(s):")
        for line in format_conflicts(exc.conflicts):
            print(f"  {line}")
        return
    print(f"[approve-plan] plan_status=approved -> {ws / 'direction.yaml'}")


def cmd_render_prompts(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    n = render_all_prompts(ws, args.book)
    print(f"[render-prompts] {n} files -> {book_workspace_dir(ws, args.book) / 'prompts'}")


def cmd_normalize_plan(args: argparse.Namespace) -> None:
    from factory.engine.lib.plan_normalize import persist_normalized_master_plan

    ws = workspace_dir(args.workspace)
    changed = persist_normalized_master_plan(ws, args.book)
    n = render_all_prompts(ws, args.book)
    print(f"[normalize-plan] master_plan fixed={changed}, rendered {n} prompts")


def cmd_fix_plans(args: argparse.Namespace) -> None:
    ws = workspace_dir(args.workspace)
    remaining, n = fix_plans(ws, args.book, use_llm=not args.no_llm)
    print(f"[fix-plans] rendered {n} prompts")
    if remaining:
        for ch, issues in sorted(remaining.items())[:10]:
            safe_print(f"  ch{ch}: {issues}")
        if len(remaining) > 10:
            print(f"  ... +{len(remaining)-10} more")
    else:
        print("[fix-plans] all plans pass plan_qc")


def cmd_promote(args: argparse.Namespace) -> None:
    n = promote_all(args.workspace, args.book)
    print(f"[promote] {n} chapter(s)")


def cmd_migrate(args: argparse.Namespace) -> None:
    from_dir = Path(args.from_dir)
    if not from_dir.is_absolute():
        from_dir = ROOT / from_dir
    if not from_dir.exists():
        alt = ROOT / "archive" / "scripts"
        if alt.exists():
            from_dir = alt
            safe_print(f"  using archive fallback: {from_dir}")
    to_hint = args.to or f"catalog/{args.workspace}"
    n = migrate_from_scripts(from_dir, workspace_id=args.workspace, with_fixes=args.with_fixes)
    print(f"[migrate] {n} chapters -> {to_hint}")


def cmd_init_book(args: argparse.Namespace) -> None:
    from factory.engine.lib.book_scaffold import init_book, list_series_books

    result = init_book(
        args.workspace,
        args.book,
        title=args.title or None,
        slug=args.slug or None,
        total_chapters=args.total_chapters,
        update_config=not args.no_config_update,
    )
    safe_print(f"[init-book] book {result['book']}: {result['title']}")
    safe_print(f"  slug -> {result['slug']}")
    safe_print(f"  workspace -> {result['workspace_dir']}")
    safe_print(f"  catalog -> {result['catalog_dir']}")
    books = list_series_books(args.workspace)
    safe_print(f"  series books: {[b['book'] for b in books]}")


def cmd_export(args: argparse.Namespace) -> None:
    cfg = load_config()
    if getattr(args, "publish", False):
        cfg = {**cfg, "export_gate_publish_mode": True, "export_gate_dup_title": "error"}
    book, book_slug = _cli_book_slug(args, cfg)
    cover = Path(args.cover) if args.cover else None
    if cover and not cover.is_absolute():
        cover = ROOT / cover
    if getattr(args, "skip_export_gate", False):
        cfg = {**cfg, "export_gate_enabled": False}
        safe_print("[export] WARN: export gate disabled (--skip-export-gate) — preview only")
    export_book(args.workspace, book_slug, args.target, cover_path=cover, cfg=cfg)


def cmd_repair_catalog(args: argparse.Namespace) -> None:
    cfg = load_config()
    book, book_slug = _cli_book_slug(args, cfg)
    result = repair_catalog_book(
        args.workspace,
        book_slug,
        backup=not args.no_backup,
    )
    safe_print(f"[repair-catalog] fixed {result['fixed']} chapters ({result['target_language']})")
    if result.get("cleared_needs_fix"):
        safe_print(f"  cleared needs_fix on {result['cleared_needs_fix']} chapters")
    if result.get("backup"):
        safe_print(f"  backup -> {result['backup']}")
    sync = sync_pipeline_from_catalog(args.workspace, book, book_slug=book_slug)
    safe_print(f"[repair-catalog] pipeline sync: {len(sync['synced'])} ready")


def cmd_sync_pipeline(args: argparse.Namespace) -> None:
    cfg = load_config()
    book, book_slug = _cli_book_slug(args, cfg)
    sync = sync_pipeline_from_catalog(args.workspace, book, book_slug=book_slug)
    safe_print(f"[sync-pipeline] {len(sync['synced'])} chapters -> ready")
    if sync.get("skipped"):
        safe_print(f"  skipped (needs_fix in catalog): {sync['skipped'][:12]}")


def cmd_qc_export_gate(args: argparse.Namespace) -> None:
    cfg = load_config()
    if args.strict:
        cfg = {**cfg, "export_gate_strict": True}
    if getattr(args, "publish", False):
        cfg = {**cfg, "export_gate_publish_mode": True, "export_gate_dup_title": "error"}
    book, book_slug = _cli_book_slug(args, cfg)
    report = run_export_gate(args.workspace, book_slug, cfg=cfg, scope="full")
    save_export_gate_report(args.workspace, book_slug, report)
    safe_print(format_export_gate_summary(report))
    flagged = report.get("needs_fix_chapters") or []
    if flagged:
        safe_print("  [advisory] chapters still carrying needs_fix:")
        for line in flagged:
            safe_print(f"    {line}")
    reasons = format_export_gate_reasons(report)
    for reason in reasons[:20]:
        safe_print(f"  {reason}")
    if len(reasons) > 20:
        safe_print(f"  ... +{len(reasons) - 20} more")
    path = save_export_gate_report(args.workspace, book_slug, report)
    safe_print(f"  report -> {path}")
    if not report.get("passed"):
        sys.exit(1)


def cmd_qc_epub(args: argparse.Namespace) -> None:
    cfg = load_config()
    book_slug = args.book_slug or resolve_book_slug(
        args.workspace, int(cfg.get("active_book") or 1), cfg=cfg
    )
    if args.epub:
        epub = Path(args.epub)
        if not epub.is_absolute():
            epub = ROOT / epub
    else:
        epub = book_catalog_dir(args.workspace, book_slug) / "exports" / "epub" / f"{book_slug}.epub"
    report = qc_epub_file(epub)
    safe_print(format_epub_qc_summary(report))
    if not report.get("ok"):
        safe_print(f"  {report.get('error')}")
        sys.exit(1)
    for msg in report.get("messages") or []:
        safe_print(f"  {msg['level']}({msg['code']}): {msg['message']}")
    qc_path = epub.with_suffix(".qc.json")
    safe_print(f"  report -> {qc_path}")
    if not report.get("passed"):
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    cfg = load_config()
    ws = workspace_dir(args.workspace)
    for bucket in ("ready", "needs_fix", "needs_review", "draft"):
        txts = list(pipeline_dir(ws, args.book, bucket).glob("ch_*.txt"))
        print(f"  pipeline/{bucket}: {len(txts)}")
    st_path = book_workspace_dir(ws, args.book) / "state.json"
    if st_path.exists():
        st = load_state(ws, args.book)
        print(f"  state: book {st.get('current_book')} ch {st.get('current_chapter')}")
    report = write_morning_report(args.workspace, args.book, cfg.get("book_slug"))
    safe_print(f"  morning report -> {report}")
    try:
        print(report.read_text(encoding="utf-8"))
    except UnicodeEncodeError:
        safe_print(report.read_text(encoding="utf-8"))


def cmd_reset(args: argparse.Namespace) -> None:
    """Archive catalog + wipe pipeline/plan for fresh rewrite."""
    import yaml

    ws = workspace_dir(args.workspace)
    book = args.book
    bd = book_workspace_dir(ws, book)

    cat = ROOT / "catalog" / args.workspace
    if cat.exists():
        dest = ROOT / "archive" / f"catalog_{args.workspace}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(cat, dest)
        book_dir = cat / "books" / "01-hop-dong-co-gia"
        for sub in ("chapters", "exports", "spot_check"):
            p = book_dir / sub if sub != "spot_check" else cat / sub
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
        (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
        (cat / "spot_check").mkdir(parents=True, exist_ok=True)
        for f in cat.glob("MORNING.md"):
            f.unlink(missing_ok=True)
        print(f"  archived catalog -> {dest}")

    for name in ("master_plan.json", "outline.json"):
        p = bd / name
        if p.exists():
            p.unlink()
    prompts = bd / "prompts"
    if prompts.exists():
        shutil.rmtree(prompts)
    for bucket in ("draft", "needs_fix", "needs_review", "ready"):
        d = pipeline_dir(ws, book, bucket)
        for f in d.glob("*"):
            f.unlink()

    save_state(
        ws,
        book,
        {
            "current_book": book,
            "current_chapter": 0,
            "timeline": [],
            "character_status": {},
            "open_threads": [],
            "facts_established": [],
            "spice_progression": "",
            "phrases_used": [],
        },
    )

    for cfg_path in (ws / "direction.yaml", ws / "manifest.yaml"):
        if cfg_path.exists():
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            data["canon_through"] = 0
            data["plan_status"] = "draft"
            cfg_path.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )

    safe_print(f"[reset] OK - san sang plan tu ch1. workspace={ws}")


def cmd_list_models(args: argparse.Namespace) -> None:
    models = list_models()
    prefix = args.prefix
    for m in sorted(models):
        if not prefix or m.startswith(prefix):
            print(m)
    print(f"\n[{len(models)} total]")


def cmd_probe_models(args: argparse.Namespace) -> None:
    cfg = load_config()
    if args.model:
        candidates = [args.model]
        safe_print(f"=== probe {args.model} ===")
        for m in candidates:
            ok, msg = probe_model(m)
            tag = "OK" if ok else "FAIL"
            safe_print(f"  {tag} {m}: {msg}")
        return

    roles = [args.role] if args.role else list(cfg.get("model_priority_by_role", {}).keys())
    if not roles:
        roles = ["writer"]

    routing = cfg.get("model_routing", "flexible")
    safe_print(f"model_routing: {routing}")
    if routing == "flexible":
        prefs = cfg.get("model_preferences") or []
        if prefs:
            safe_print(f"model_preferences (last resort): {', '.join(prefs)}")
        else:
            safe_print("model_preferences: (none — OmniRoute auto picks provider)")

    for role in roles:
        chain = resolve_priority_chain(cfg, role)
        group = cfg.get("model_priority_by_role", {}).get(role, "")
        label = f"{role} ({group})" if group else role
        safe_print(f"\n=== {label} ===")
        if not chain:
            safe_print("  (empty chain)")
            continue
        for i, m in enumerate(chain, 1):
            ok, msg = probe_model(m)
            tag = "OK" if ok else "FAIL"
            safe_print(f"  {i}. {tag} {m}: {msg[:100]}")


def cmd_init_workspace(args: argparse.Namespace) -> None:
    from factory.engine.lib.workspace_init import init_workspace_from_template

    dst = init_workspace_from_template(
        args.workspace,
        template_id=args.from_workspace,
        copy_narrative=not args.no_narrative,
        copy_concept=not args.no_concept,
    )
    print(f"[init-workspace] created {dst}")
    print("[init-workspace] Next: UI chon workspace -> batch Chuan bi sach -> approve narrative/bible sau khi doc")


def cmd_setup_workspace(args: argparse.Namespace) -> None:
    cfg = load_config()
    ws = workspace_dir(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)

    manifest = ws / "manifest.yaml"
    if not manifest.exists():
        manifest.write_text(
            """id: ceo-contract
pen_name: ""
spice_level: 3
target_platforms: [vella, webnovel]
blurb: |
  Một tỷ đồng đổi một năm làm vợ hợp đồng cho chủ tịch lạnh lùng nhất Sài Gòn.
  Diệp Tâm tưởng đây chỉ là giao dịch — cho tới khi hợp đồng bắt đầu có điều khoản
  không ai viết ra.
tropes: [contract marriage, CEO, slow burn enemies-to-lovers, forced proximity]
spice_badge: "18+"
""",
            encoding="utf-8",
        )

    book = 1
    for bucket in ("draft", "needs_fix", "needs_review", "ready"):
        pipeline_dir(ws, book, bucket)

    legacy = ROOT / "story_factory" / "series" / "ceo_contract_01"
    if legacy.exists():
        bible_path(ws).parent.mkdir(parents=True, exist_ok=True)
        if (legacy / "series_bible.json").exists() and not bible_path(ws).exists():
            shutil.copy2(legacy / "series_bible.json", bible_path(ws))
        bd = book_workspace_dir(ws, book)
        if (legacy / "book_1_outline.json").exists() and not (bd / "outline.json").exists():
            shutil.copy2(legacy / "book_1_outline.json", bd / "outline.json")
        if (legacy / "story_state.json").exists() and not (bd / "state.json").exists():
            shutil.copy2(legacy / "story_state.json", bd / "state.json")
        src_ready = legacy / "chapters" / "ready"
        if src_ready.exists():
            for f in src_ready.glob("ch_*.txt"):
                dst = pipeline_dir(ws, book, "ready") / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)

    if not bible_path(ws).exists():
        save_json(
            bible_path(ws),
            {
                "title": "Hợp đồng có giá",
                "genre": "ngôn tình hiện đại",
                "sub_niche": "ceo_contract_marriage",
                "spice_level": cfg["spice_level"],
            },
        )
    print(f"[setup] OK -> {ws}")


def main() -> None:
    cfg = load_config()
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--workspace",
        default=cfg.get("default_workspace", "ceo-contract"),
        help="workspace id",
    )

    parser = argparse.ArgumentParser(description="Story factory (3-zone)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_arch = sub.add_parser("architect", parents=[parent])
    p_arch.add_argument("--niche", default="ceo_contract_marriage")
    p_arch.add_argument("--spice", type=int, default=None)
    p_arch.add_argument("--books", type=int, default=5)

    p_out = sub.add_parser("outline", parents=[parent])
    p_out.add_argument("--book", type=int, default=1)

    p_w = sub.add_parser("write", parents=[parent])
    p_w.add_argument("--book", type=int, default=1)
    p_w.add_argument("--from-chapter", type=int, default=4)
    p_w.add_argument("--to-chapter", type=int, default=15)
    p_w.add_argument("--force", action="store_true", help="bỏ qua plan approved + state gate")

    p_plan = sub.add_parser("plan", parents=[parent])
    p_plan.add_argument("--book", type=int, default=1)
    p_plan.add_argument("--acts", default="all", help="all hoặc 4-12")
    p_plan.add_argument("--force", action="store_true", help="bỏ qua bible approved")
    p_plan.add_argument(
        "--replan",
        action="store_true",
        help="xóa chapter_plans hiện tại và sinh lại toàn bộ (Tạo lại plan)",
    )

    sub.add_parser("validate-bible", parents=[parent])
    sub.add_parser("approve-bible", parents=[parent])
    p_icr = sub.add_parser("init-canon-registry", parents=[parent])
    p_icr.add_argument(
        "--force",
        action="store_true",
        help="ghi đè canon_registry.yaml nếu đã có",
    )

    p_dn = sub.add_parser("develop-narrative", parents=[parent])
    p_dn.add_argument(
        "--pass",
        dest="pass_name",
        default="all",
        choices=["all", "kernel", "book_arc", "threads", "mystery_ledger", "knowledge_matrix"],
        help="pass đơn hoặc all",
    )

    p_concept = sub.add_parser("concept", parents=[parent])
    p_concept.add_argument("--init", action="store_true", help="tạo concept.yaml trống")
    p_concept.add_argument("--interview", action="store_true", help="hỏi từng câu, lưu concept.yaml")
    p_concept.add_argument("--check", action="store_true", help="kiểm tra đã điền chỉ đạo chưa")
    p_concept.add_argument("--ready", action="store_true", help="đánh dấu concept_status=ready")

    p_ci = sub.add_parser("compile-intent", parents=[parent])
    p_ci.add_argument("--book", type=int, default=None)
    p_ai = sub.add_parser("approve-intent", parents=[parent])
    p_ai.add_argument("--book", type=int, default=None)

    sub.add_parser("validate-narrative", parents=[parent])
    sub.add_parser("approve-narrative", parents=[parent])

    p_ap = sub.add_parser("approve-plan", parents=[parent])
    p_ap.add_argument("--book", type=int, default=None, help="book number (default: direction.book)")

    p_rp = sub.add_parser("render-prompts", parents=[parent])
    p_rp.add_argument("--book", type=int, default=1)

    p_norm = sub.add_parser("normalize-plan", parents=[parent])
    p_norm.add_argument("--book", type=int, default=1)

    p_fix = sub.add_parser("fix-plans", parents=[parent])
    p_fix.add_argument("--book", type=int, default=1)
    p_fix.add_argument("--no-llm", action="store_true", help="chi apply canon + rule patch, khong goi plan_fixer")

    p_prom = sub.add_parser("promote", parents=[parent])
    p_prom.add_argument("--book", type=int, default=1)

    p_mig = sub.add_parser("migrate", parents=[parent])
    p_mig.add_argument("--from", dest="from_dir", default="scripts")
    p_mig.add_argument("--to", default=None)
    p_mig.add_argument("--with-fixes", action="store_true", default=True)

    p_exp = sub.add_parser("export", parents=[parent])
    p_exp.add_argument("--book", type=int, default=None)
    p_exp.add_argument("--book-slug", default=None)
    p_exp.add_argument("--target", choices=["vella", "epub", "docx"], required=True)
    p_exp.add_argument("--cover", default=None, help="ảnh bìa .jpg/.png cho export epub")
    p_exp.add_argument(
        "--skip-export-gate",
        action="store_true",
        help="bỏ qua export gate (preview khi còn lỗi nội dung)",
    )
    p_exp.add_argument(
        "--publish",
        action="store_true",
        help="publish mode: EG-05 dup title = error",
    )

    p_repair = sub.add_parser("repair-catalog", parents=[parent])
    p_repair.add_argument("--book", type=int, default=None)
    p_repair.add_argument("--book-slug", default=None)
    p_repair.add_argument("--no-backup", action="store_true")

    p_sync = sub.add_parser("sync-pipeline", parents=[parent])
    p_sync.add_argument("--book", type=int, default=1)
    p_sync.add_argument("--book-slug", default=None)

    p_qc_epub = sub.add_parser("qc-epub", parents=[parent])
    p_qc_epub.add_argument("--book", type=int, default=None)
    p_qc_epub.add_argument("--book-slug", default=None)
    p_qc_epub.add_argument("--epub", default=None, help="đường dẫn .epub (mặc định: catalog/.../exports/epub/<slug>.epub)")

    p_qc_gate = sub.add_parser("qc-export-gate", parents=[parent])
    p_qc_gate.add_argument("--book", type=int, default=None)
    p_qc_gate.add_argument("--book-slug", default=None)
    p_qc_gate.add_argument("--strict", action="store_true", help="WARN cũng fail")
    p_qc_gate.add_argument(
        "--publish",
        action="store_true",
        help="publish mode: EG-05 dup title = error",
    )

    p_st = sub.add_parser("status", parents=[parent])
    p_st.add_argument("--book", type=int, default=1)

    p_probe = sub.add_parser("probe-models", parents=[parent])
    p_probe.add_argument("--model", default=None)
    p_probe.add_argument(
        "--role",
        default=None,
        help="architect|outliner|writer|qc|... — không truyền = probe mọi chain",
    )

    p_lm = sub.add_parser("list-models", parents=[parent])
    p_lm.add_argument("--prefix", default=None)

    p_reset = sub.add_parser("reset", parents=[parent])
    p_reset.add_argument("--book", type=int, default=1)

    p_init = sub.add_parser("init-workspace", parents=[parent])
    p_init.add_argument("--from-workspace", default="ceo-contract", dest="from_workspace")
    p_init.add_argument("--no-narrative", action="store_true")
    p_init.add_argument("--no-concept", action="store_true")

    p_ib = sub.add_parser("init-book", parents=[parent])
    p_ib.add_argument("--book", type=int, required=True, help="book number (2, 3, …)")
    p_ib.add_argument("--title", default=None, help="display title")
    p_ib.add_argument("--slug", default=None, help="catalog slug e.g. 02-the-altered-name")
    p_ib.add_argument("--total-chapters", type=int, default=None, dest="total_chapters")
    p_ib.add_argument("--no-config-update", action="store_true", dest="no_config_update")

    sub.add_parser("setup", parents=[parent])

    args = parser.parse_args()

    handlers = {
        "architect": cmd_architect,
        "validate-bible": cmd_validate_bible,
        "approve-bible": cmd_approve_bible,
        "init-canon-registry": cmd_init_canon_registry,
        "develop-narrative": cmd_develop_narrative,
        "concept": cmd_concept,
        "compile-intent": cmd_compile_intent,
        "approve-intent": cmd_approve_intent,
        "validate-narrative": cmd_validate_narrative,
        "approve-narrative": cmd_approve_narrative,
        "outline": cmd_outline,
        "write": cmd_write,
        "plan": cmd_plan,
        "approve-plan": cmd_approve_plan,
        "render-prompts": cmd_render_prompts,
        "normalize-plan": cmd_normalize_plan,
        "fix-plans": cmd_fix_plans,
        "promote": cmd_promote,
        "repair-catalog": cmd_repair_catalog,
        "sync-pipeline": cmd_sync_pipeline,
        "migrate": cmd_migrate,
        "export": cmd_export,
        "qc-epub": cmd_qc_epub,
        "qc-export-gate": cmd_qc_export_gate,
        "status": cmd_status,
        "reset": cmd_reset,
        "list-models": cmd_list_models,
        "probe-models": cmd_probe_models,
        "init-workspace": cmd_init_workspace,
        "init-book": cmd_init_book,
        "setup": cmd_setup_workspace,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
