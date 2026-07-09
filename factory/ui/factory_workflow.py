"""Factory UI — pipeline status, chapter write/approve, export."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.bible_schema import bible_is_approved, validate_bible
from factory.engine.lib.book_config import get_total_chapters, set_total_chapters
from factory.engine.lib.catalog import (
    catalog_chapter_is_clean,
    export_book,
    parse_markdown,
    promote_chapter,
    sync_pipeline_from_catalog,
)
from factory.engine.lib.chapter_reasons import chapter_block_info, format_status_with_reason
from factory.engine.lib.machine_qc import word_count_vi
from factory.engine.lib.master_plan import approve_plan, fix_plans, plan_book, plan_is_approved
from factory.engine.lib.narrative_developer import develop_narrative
from factory.engine.lib.narrative_schema import (
    load_concept,
    narrative_is_approved,
    validate_narrative_assets,
)
from factory.engine.lib.prompt_builder import prompt_path, render_all_prompts
from factory.engine.lib.write_guards import best_effort_catch_up_state, state_chain_complete
from factory.engine.lib.state_updater import update_state_after_pass
from factory.engine.paths import (
    bible_path,
    book_catalog_dir,
    book_workspace_dir,
    chapter_pipeline_path,
    load_config,
    pipeline_dir,
    promoted_marker,
    resolve_book_slug,
    workspace_dir,
)
from factory.engine.run_factory import load_chapter_plan, save_json, write_one_chapter
from factory.engine.lib.call_9router import call_9router, parse_json_response

from factory.ui import batch_state


def _batch_is_active(workspace_id: str) -> bool:
    return batch_state.batch_is_active(workspace_id)


def _load_direction(ws: Path) -> dict:
    p = ws / "direction.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _catalog_is_clean(workspace_id: str, book: int, ch: int) -> bool:
    path = _catalog_chapter_path(workspace_id, book, ch)
    if not path:
        return False
    meta, _ = parse_markdown(path)
    return catalog_chapter_is_clean(meta)


def _chapter_status(ws: Path, book: int, ch: int, *, workspace_id: str | None = None) -> str:
    wid = workspace_id or ws.name
    cat_path = _catalog_chapter_path(wid, book, ch)
    if cat_path:
        meta, _ = parse_markdown(cat_path)
        if catalog_chapter_is_clean(meta):
            return "ready"
        return "needs_fix"
    for bucket in ("ready", "needs_review", "needs_fix", "draft"):
        if chapter_pipeline_path(ws, book, bucket, ch).exists():
            return bucket
    if prompt_path(ws, book, ch).exists():
        return "prompt_only"
    return "missing"


def _chapter_text(ws: Path, book: int, ch: int) -> tuple[str | None, str]:
    """Return (text, source) — clean catalog wins over stale pipeline buckets."""
    wid = ws.name
    cat_path = _catalog_chapter_path(wid, book, ch)
    if cat_path:
        meta, body = parse_markdown(cat_path)
        if catalog_chapter_is_clean(meta):
            return body, "catalog"
    for bucket in ("ready", "needs_review", "needs_fix", "draft"):
        p = chapter_pipeline_path(ws, book, bucket, ch)
        if p.exists():
            return p.read_text(encoding="utf-8"), bucket
    cfg = load_config()
    try:
        slug = resolve_book_slug(wid, book, cfg=cfg)
    except ValueError:
        slug = cfg.get("book_slug", "01-hop-dong-co-gia")
    cat_dir = book_catalog_dir(ws.name, slug) / "chapters"
    if cat_dir.exists():
        for f in sorted(cat_dir.glob("*.md")):
            if f.name.startswith(f"{ch:02d}-") or f.name.startswith(f"{ch}-"):
                return f.read_text(encoding="utf-8"), "catalog"
    return None, "none"


def _resolve_book(
    workspace_id: str,
    book: int | None = None,
    book_slug: str | None = None,
) -> tuple[int, str]:
    cfg = load_config()
    book_num = int(book or cfg.get("active_book", 1))
    slug = book_slug or resolve_book_slug(workspace_id, book_num, cfg=cfg)
    return book_num, slug


def pipeline_status(workspace_id: str, book: int | None = None) -> dict[str, Any]:
    cfg = load_config()
    book = int(book or cfg.get("active_book", 1))
    ws = workspace_dir(workspace_id)
    direction = _load_direction(ws)
    concept = load_concept(ws)
    total = get_total_chapters(workspace_id, book)

    plan_path = book_workspace_dir(ws, book) / "master_plan.json"
    planned = 0
    if plan_path.exists():
        planned = len(json.loads(plan_path.read_text(encoding="utf-8")).get("chapter_plans", []))

    counts = {b: 0 for b in ("ready", "needs_review", "needs_fix", "draft", "prompt_only", "missing")}
    in_catalog = 0
    blocked: list[dict[str, Any]] = []
    for ch in range(1, total + 1):
        st = _chapter_status(ws, book, ch, workspace_id=workspace_id)
        counts[st] = counts.get(st, 0) + 1
        if promoted_marker(ws, book, ch).exists() or _catalog_has_chapter(workspace_id, book, ch):
            in_catalog += 1
        if st in ("needs_fix", "needs_review"):
            block = chapter_block_info(ws, book, st, ch)
            blocked.append(
                {
                    "chapter": ch,
                    "status": st,
                    "reasons": block["reasons"],
                    "reason_summary": block["reason_summary"],
                }
            )

    narr_errors = validate_narrative_assets(ws, direction) if direction.get("narrative_profile") else []
    bible_errors: list[str] = []
    if bible_path(ws).exists():
        bible_errors = validate_bible(json.loads(bible_path(ws).read_text(encoding="utf-8")))

    gates = {
        "concept": {
            "status": concept.get("concept_status", "missing"),
            "ok": concept.get("concept_status") == "ready",
        },
        "narrative": {
            "status": direction.get("narrative_status", "draft"),
            "ok": narrative_is_approved(direction),
            "errors": narr_errors[:5],
        },
        "bible": {
            "status": direction.get("bible_status", "draft"),
            "ok": bible_path(ws).exists() and not bible_errors,
            "errors": bible_errors[:5],
        },
        "plan": {
            "status": direction.get("plan_status", "draft"),
            "ok": plan_is_approved(ws),
            "chapters_planned": planned,
            "total": total,
        },
        "write": {
            "ready": counts["ready"],
            "in_catalog": in_catalog,
            "total": total,
        },
    }

    next_steps: list[str] = []
    if not gates["concept"]["ok"]:
        next_steps.append("concept: điền form → sẵn sàng")
    elif not gates["narrative"]["ok"]:
        next_steps.append("narrative: sinh AI → duyệt → approve-narrative")
    elif not gates["bible"]["ok"]:
        next_steps.append("bible: architect → validate → approve-bible")
    elif not gates["plan"]["ok"]:
        next_steps.append("plan: plan → fix-plans → approve-plan")
    elif counts["ready"] < total:
        next_steps.append(f"write: viết chương ({counts['ready']}/{total} ready)")
    else:
        next_steps.append("export: EPUB/DOCX")

    from factory.engine.lib.book_scaffold import list_series_books

    _, slug = _resolve_book(workspace_id, book)

    return {
        "workspace": workspace_id,
        "book": book,
        "book_slug": slug,
        "books": list_series_books(workspace_id),
        "total_chapters": total,
        "planned_chapters": planned,
        "title": concept.get("title", ""),
        "target_language": direction.get("target_language", "vi"),
        "gates": gates,
        "counts": counts,
        "blocked_chapters": blocked,
        "next_steps": next_steps,
        "direction": {
            "narrative_profile": direction.get("narrative_profile"),
            "publish_strategy": direction.get("publish_strategy"),
            "plan_status": direction.get("plan_status"),
            "bible_status": direction.get("bible_status"),
            "narrative_status": direction.get("narrative_status"),
        },
    }


def _catalog_has_chapter(workspace_id: str, book: int, ch: int) -> bool:
    return _catalog_chapter_path(workspace_id, book, ch) is not None


def _catalog_chapter_path(workspace_id: str, book: int, ch: int) -> Path | None:
    cfg = load_config()
    try:
        slug = resolve_book_slug(workspace_id, book, cfg=cfg)
    except ValueError:
        slug = cfg.get("book_slug", "01-hop-dong-co-gia")
    cat_dir = book_catalog_dir(workspace_id, slug) / "chapters"
    if not cat_dir.exists():
        return None
    for f in cat_dir.glob("*.md"):
        if f.name.startswith(f"{ch:02d}-") or f.name.startswith(f"{ch}-"):
            return f
    return None


def chapter_list(workspace_id: str, book: int = 1) -> list[dict]:
    ws = workspace_dir(workspace_id)
    direction = _load_direction(ws)
    total = get_total_chapters(workspace_id, book)
    items: list[dict] = []
    for ch in range(1, total + 1):
        plan = load_chapter_plan(ws, book, ch)
        status = _chapter_status(ws, book, ch, workspace_id=workspace_id)
        text, _ = _chapter_text(ws, book, ch)
        block = chapter_block_info(ws, book, status, ch)
        items.append(
            {
                "chapter": ch,
                "title": plan.get("title") or plan.get("one_line_summary", "")[:60],
                "status": status,
                "reasons": block["reasons"],
                "reason_summary": block["reason_summary"],
                "has_prompt": prompt_path(ws, book, ch).exists(),
                "in_catalog": promoted_marker(ws, book, ch).exists() or _catalog_has_chapter(workspace_id, book, ch),
                "word_count": word_count_vi(text) if text else 0,
            }
        )
    return items


def chapter_get(workspace_id: str, ch: int, book: int = 1) -> dict:
    ws = workspace_dir(workspace_id)
    text, source = _chapter_text(ws, book, ch)
    plan = load_chapter_plan(ws, book, ch)
    status = _chapter_status(ws, book, ch)
    block = chapter_block_info(ws, book, status, ch)
    prompt = ""
    pp = prompt_path(ws, book, ch)
    if pp.exists():
        prompt = pp.read_text(encoding="utf-8")
    return {
        "chapter": ch,
        "status": status,
        "source": source,
        "title": plan.get("title", ""),
        "plan_summary": plan.get("one_line_summary", ""),
        "prose": text or "",
        "prompt_preview": prompt[:2000] if prompt else "",
        "word_count": word_count_vi(text) if text else 0,
        "reasons": block["reasons"],
        "reason_summary": block["reason_summary"],
        "issues": block["issues"],
        "qc": block["qc"],
    }


def chapter_write(workspace_id: str, ch: int, book: int = 1) -> dict:
    ws = workspace_dir(workspace_id)
    direction = _load_direction(ws)
    if not plan_is_approved(ws):
        return {"ok": False, "error": "plan chưa approved — chạy plan + approve-plan trước"}
    if not prompt_path(ws, book, ch).exists():
        return {"ok": False, "error": f"thiếu prompt ch_{ch:03d} — chạy plan/fix-plans"}
    cfg = load_config()
    _, status = write_one_chapter(ws, book, ch, cfg, workspace_id)
    return {"ok": status in ("ready", "skipped"), "status": status, **chapter_get(workspace_id, ch, book)}


def chapter_approve(workspace_id: str, ch: int, book: int = 1) -> dict:
    """User đọc xong → duyệt vào catalog (kể cả needs_review)."""
    ws = workspace_dir(workspace_id)
    cat_existing = _catalog_chapter_path(workspace_id, book, ch)
    if promoted_marker(ws, book, ch).exists() or cat_existing:
        meta = chapter_get(workspace_id, ch, book)
        return {
            "ok": True,
            "already_promoted": True,
            "message": "chương đã có trong catalog",
            "catalog_path": str(cat_existing) if cat_existing else None,
            **meta,
        }

    text = None
    for bucket in ("needs_review", "needs_fix", "draft"):
        p = chapter_pipeline_path(ws, book, bucket, ch)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            chapter_pipeline_path(ws, book, "ready", ch).write_text(text, encoding="utf-8")
            p.unlink(missing_ok=True)
            break
    ready = chapter_pipeline_path(ws, book, "ready", ch)
    if not ready.exists():
        return {"ok": False, "error": "không có chương để duyệt — viết trước"}
    text = text or ready.read_text(encoding="utf-8")
    best_effort_catch_up_state(ws, book, ch + 1)
    if state_chain_complete(ws, book, ch):
        try:
            update_state_after_pass(ws, ch, text, book=book)
        except Exception:
            pass
    out, block_reasons = promote_chapter(workspace_id, book, ch, auto=False)
    meta = chapter_get(workspace_id, ch, book)
    if out is None:
        cat_existing = _catalog_chapter_path(workspace_id, book, ch)
        if cat_existing:
            return {
                "ok": True,
                "already_promoted": True,
                "message": "chương đã có trong catalog",
                "catalog_path": str(cat_existing),
                **meta,
            }
        err = "promote thất bại — kiểm tra pipeline/ready"
        if block_reasons:
            err = "export gate chặn promote: " + "; ".join(block_reasons[:4])
        return {
            "ok": False,
            "error": err,
            "export_gate_reasons": block_reasons,
            **meta,
        }
    return {
        "ok": True,
        "catalog_path": str(out),
        **meta,
    }


def chapter_discard(workspace_id: str, ch: int, book: int = 1) -> dict:
    ws = workspace_dir(workspace_id)
    for bucket in ("ready", "needs_review", "needs_fix", "draft"):
        p = chapter_pipeline_path(ws, book, bucket, ch)
        if p.exists():
            p.unlink()
        issues = pipeline_dir(ws, book, bucket) / f"ch_{ch:03d}_issues.json"
        issues.unlink(missing_ok=True)
        qc = pipeline_dir(ws, book, bucket) / f"ch_{ch:03d}_qc.json"
        qc.unlink(missing_ok=True)
    pm = promoted_marker(ws, book, ch)
    if pm.exists():
        pm.unlink()
    return {"ok": True, "chapter": ch, "status": "missing"}


def run_pipeline_step(workspace_id: str, action: str, book: int = 1) -> dict:
    ws = workspace_dir(workspace_id)
    cfg = load_config()
    direction = _load_direction(ws)

    try:
        if action == "develop-narrative":
            paths = develop_narrative(workspace_id, pass_name="all")
            return {"ok": True, "files": [str(p) for p in paths], **pipeline_status(workspace_id, book)}

        if action == "validate-narrative":
            errs = validate_narrative_assets(ws, direction)
            return {"ok": not errs, "errors": errs, **pipeline_status(workspace_id, book)}

        if action == "approve-narrative":
            errs = validate_narrative_assets(ws, direction)
            if errs:
                return {"ok": False, "errors": errs}
            data = direction
            data["narrative_status"] = "approved"
            (ws / "direction.yaml").write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            return {"ok": True, **pipeline_status(workspace_id, book)}

        if action == "architect":
            concept = load_concept(ws)
            user = json.dumps(
                {
                    "genre": "romance thriller",
                    "sub_niche": direction.get("narrative_profile", "romance_thriller"),
                    "spice_level": cfg["spice_level"],
                    "planned_books": 5,
                    "target_language": direction.get("target_language", "vi"),
                    "concept_title": concept.get("title"),
                    "concept_logline": concept.get("logline"),
                    "author_directive": (concept.get("author_directive") or "")[:4000],
                },
                ensure_ascii=False,
            )
            raw, _ = call_9router("architect", user, max_tokens=8192, direction=direction)
            bible = parse_json_response(raw)
            bible["bible_status"] = "draft"
            save_json(bible_path(ws), bible)
            direction["bible_status"] = "draft"
            (ws / "direction.yaml").write_text(
                yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            return {"ok": True, **pipeline_status(workspace_id, book)}

        if action == "validate-bible":
            bible = json.loads(bible_path(ws).read_text(encoding="utf-8"))
            errs = validate_bible(bible)
            return {"ok": not errs, "errors": errs, **pipeline_status(workspace_id, book)}

        if action == "approve-bible":
            bible = json.loads(bible_path(ws).read_text(encoding="utf-8"))
            errs = validate_bible(bible)
            if errs:
                return {"ok": False, "errors": errs}
            bible["bible_status"] = "approved"
            save_json(bible_path(ws), bible)
            direction["bible_status"] = "approved"
            (ws / "direction.yaml").write_text(
                yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            return {"ok": True, **pipeline_status(workspace_id, book)}

        if action == "plan":
            if direction.get("narrative_profile") and not narrative_is_approved(direction):
                return {"ok": False, "error": "narrative chưa approved"}
            bible = json.loads(bible_path(ws).read_text(encoding="utf-8"))
            if not bible_is_approved(bible, direction):
                return {"ok": False, "error": "bible chưa approved"}
            plan_book(ws, book)
            fix_plans(ws, book, use_llm=True)
            return {"ok": True, **pipeline_status(workspace_id, book)}

        if action == "fix-plans":
            fix_plans(ws, book, use_llm=True)
            return {"ok": True, **pipeline_status(workspace_id, book)}

        if action == "approve-plan":
            approve_plan(ws)
            n = render_all_prompts(ws, book)
            return {"ok": True, "prompts_rendered": n, **pipeline_status(workspace_id, book)}

        if action == "render-prompts":
            n = render_all_prompts(ws, book)
            return {"ok": True, "prompts_rendered": n, **pipeline_status(workspace_id, book)}

        return {"ok": False, "error": f"unknown action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), **pipeline_status(workspace_id, book)}


def _batch_progress_path(ws: Path) -> Path:
    return ws / "batch_progress.json"


def _write_batch_progress(ws: Path, data: dict) -> None:
    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _batch_progress_path(ws).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_batch_lock(ws: Path, prog: dict, workspace_id: str | None = None) -> dict:
    """Clear orphaned ``running: true`` left by server restart or uncaught errors."""
    if not prog.get("running"):
        return prog
    ws_id = workspace_id or ws.name
    log = prog.get("log") or []
    fixed: dict | None = None
    if not _batch_is_active(ws_id):
        fixed = {
            **prog,
            "running": False,
            "ok": False,
            "error": "batch bi ngat (server restart hoac crash) — co the bat lai",
            "log": list(log) + ["⚠ batch treo — lock da xoa tu dong"],
        }
    elif prog.get("ok") is not None:
        fixed = {**prog, "running": False}
    elif prog.get("phase") == "write" and any("dung batch" in line for line in log):
        fixed = {**prog, "running": False}
    elif prog.get("phase") == "prep" and prog.get("step") and len(log) <= 1:
        fixed = {
            **prog,
            "running": False,
            "ok": False,
            "error": "prep bi ngat — thu lai",
            "log": list(log) + ["⚠ prep bi ngat giua chung — lock da xoa"],
        }
    if fixed:
        _write_batch_progress(ws, fixed)
        return fixed
    return prog


def reset_batch_lock(workspace_id: str) -> dict:
    """Manually clear a stale batch lock (safe when no batch thread is active)."""
    ws = workspace_dir(workspace_id)
    if _batch_is_active(workspace_id):
        return {
            "ok": False,
            "error": "batch dang chay that — khong the xoa lock",
            **get_batch_progress(workspace_id),
        }
    p = _batch_progress_path(ws)
    if not p.exists():
        return {"ok": True, "running": False, "phase": "", "log": []}
    prog = json.loads(p.read_text(encoding="utf-8"))
    if not prog.get("running"):
        return {"ok": True, **prog}
    log = list(prog.get("log") or [])
    fixed = {
        **prog,
        "running": False,
        "ok": False,
        "error": "lock da xoa thu cong",
        "log": log + ["⚠ lock batch da xoa thu cong"],
    }
    _write_batch_progress(ws, fixed)
    return {"ok": True, **fixed}


def get_batch_progress(workspace_id: str) -> dict:
    ws = workspace_dir(workspace_id)
    p = _batch_progress_path(ws)
    if not p.exists():
        return {"running": False, "phase": "", "log": []}
    prog = json.loads(p.read_text(encoding="utf-8"))
    return _normalize_batch_lock(ws, prog, workspace_id)


def _prep_steps(status: dict, *, prompts_ready: bool = False) -> list[str]:
    """Các bước cần chạy để sẵn sàng viết — bỏ qua gate đã approved."""
    g = status.get("gates", {})
    if not g.get("concept", {}).get("ok"):
        return []
    if (
        g.get("narrative", {}).get("ok")
        and g.get("bible", {}).get("ok")
        and g.get("plan", {}).get("ok")
        and prompts_ready
    ):
        return []
    steps: list[str] = []
    if g.get("narrative", {}).get("status") != "approved":
        steps.extend(["develop-narrative", "validate-narrative", "approve-narrative"])
    if g.get("bible", {}).get("status") != "approved":
        steps.extend(["architect", "validate-bible", "approve-bible"])
    planned = int(g.get("plan", {}).get("chapters_planned", 0))
    total = int(g.get("plan", {}).get("total", 50))
    if planned < total or not g.get("plan", {}).get("ok"):
        steps.append("plan")
    if g.get("plan", {}).get("status") != "approved":
        steps.extend(["fix-plans", "approve-plan"])
    if not prompts_ready:
        steps.append("render-prompts")
    # dedupe giữ thứ tự
    seen: set[str] = set()
    out: list[str] = []
    for s in steps:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def run_batch_prep(workspace_id: str, book: int = 1) -> dict:
    ws = workspace_dir(workspace_id)
    log: list[str] = []
    status = pipeline_status(workspace_id, book)
    total = int(status.get("gates", {}).get("plan", {}).get("total", 50))
    prompts_ready = all(prompt_path(ws, book, ch).exists() for ch in range(1, total + 1))
    steps = _prep_steps(status, prompts_ready=prompts_ready)
    if not steps:
        if not status["gates"]["concept"]["ok"]:
            return {"ok": False, "error": "concept chua ready — dien form truoc", **status}
        _write_batch_progress(ws, {"running": False, "phase": "prep", "log": ["Da san sang — khong can chay them"]})
        return {"ok": True, "skipped": True, "log": ["Da san sang"], **status}

    batch_state.add_sync_lock(workspace_id)
    _write_batch_progress(ws, {"running": True, "phase": "prep", "step": "", "log": log})
    failed = False
    err_msg = ""
    try:
        for action in steps:
            log.append(f"▶ {action}...")
            _write_batch_progress(ws, {"running": True, "phase": "prep", "step": action, "log": list(log)})
            result = run_pipeline_step(workspace_id, action, book)
            if result.get("ok"):
                extra = ""
                if result.get("prompts_rendered"):
                    extra = f" ({result['prompts_rendered']} prompts)"
                log.append(f"✓ {action}{extra}")
            else:
                err_msg = result.get("error") or ", ".join(result.get("errors") or []) or "failed"
                log.append(f"✗ {action}: {err_msg}")
                failed = True
                break
            status = result
    except Exception as exc:
        failed = True
        err_msg = str(exc)
        log.append(f"✗ prep: {err_msg}")
    finally:
        batch_state.discard_sync_lock(workspace_id)
        _write_batch_progress(
            ws,
            {
                "running": False,
                "phase": "prep",
                "step": "",
                "ok": not failed,
                "error": err_msg or None,
                "log": log,
            },
        )
    return {"ok": not failed, "log": log, **pipeline_status(workspace_id, book)}


def start_batch_prep(workspace_id: str, book: int = 1) -> dict:
    """Run prep in background — returns immediately (prep can take many minutes)."""
    ws = workspace_dir(workspace_id)
    if _batch_is_active(workspace_id):
        return {
            "ok": False,
            "error": "batch dang chay — doi hoac bam Huy lock batch",
            **get_batch_progress(workspace_id),
        }

    def _run() -> None:
        try:
            run_batch_prep(workspace_id, book)
        finally:
            batch_state.unregister_thread(workspace_id)

    t = threading.Thread(target=_run, daemon=True)
    batch_state.register_thread(workspace_id, t)
    t.start()
    return {"ok": True, "started": True, "phase": "prep", **get_batch_progress(workspace_id)}


def _first_incomplete_chapter(ws: Path, book: int, from_ch: int, to_ch: int) -> int:
    """First chapter in range that still needs writing (not ready)."""
    for ch in range(from_ch, to_ch + 1):
        if _chapter_status(ws, book, ch) != "ready":
            return ch
    return from_ch


def _run_batch_write_loop(
    workspace_id: str,
    book: int,
    from_ch: int,
    to_ch: int,
    *,
    stop_on_review: bool = False,
) -> None:
    ws = workspace_dir(workspace_id)
    cfg = load_config()
    direction = _load_direction(ws)
    total = get_total_chapters(workspace_id, book)
    to_ch = min(to_ch, total)
    log: list[str] = [
        f"Viet chuong {from_ch}–{to_ch}..."
        + (" (dung khi QC fail)" if stop_on_review else " (chay het — loi de lai trong pipeline)")
    ]
    _write_batch_progress(
        ws,
        {
            "running": True,
            "phase": "write",
            "from_ch": from_ch,
            "to_ch": to_ch,
            "current_ch": from_ch,
            "written": 0,
            "log": log,
        },
    )
    written = 0
    skipped_ready = 0
    failed_ch: int | None = None
    issue_chapters: list[int] = []
    skipped_chapters: list[int] = []
    err_msg = ""
    try:
        from factory.engine.lib.write_guards import WriteBlockedError

        for ch in range(from_ch, to_ch + 1):
            st = _chapter_status(ws, book, ch, workspace_id=workspace_id)
            if st == "ready":
                skipped_ready += 1
                log.append(f"⊘ ch{ch}: da co (ready) — bo qua")
                _write_batch_progress(
                    ws,
                    {
                        "running": True,
                        "phase": "write",
                        "current_ch": ch,
                        "written": written,
                        "issue_chapters": issue_chapters,
                        "log": list(log),
                    },
                )
                continue
            if st in ("needs_review", "needs_fix", "draft"):
                log.append(f"↻ ch{ch}: viet lai (dang {st})")
            if not prompt_path(ws, book, ch).exists():
                skipped_chapters.append(ch)
                log.append(f"⊘ ch{ch}: thieu prompt — bo qua, tiep tuc")
                if stop_on_review:
                    failed_ch = ch
                    err_msg = "thieu prompt"
                    break
                continue
            log.append(f"▶ ch{ch} dang viet...")
            _write_batch_progress(
                ws,
                {
                    "running": True,
                    "phase": "write",
                    "current_ch": ch,
                    "written": written,
                    "issue_chapters": issue_chapters,
                    "log": list(log),
                },
            )
            try:
                _, status = write_one_chapter(ws, book, ch, cfg, workspace_id)
                block = chapter_block_info(ws, book, status, ch)
                status_label = format_status_with_reason(status, block.get("reason_summary", ""))
                log.append(f"✓ ch{ch}: {status_label}")
                if status not in ("skipped",):
                    written += 1
                if status in ("needs_fix", "needs_review"):
                    issue_chapters.append(ch)
                    for reason in block.get("reasons") or []:
                        log.append(f"  → {reason}")
                    if stop_on_review:
                        failed_ch = ch
                        err_msg = status_label
                        log.append(f"⏸ dung batch — sua ch{ch} truoc khi tiep")
                        break
                    log.append(f"⚠ ch{ch}: {status} — de lai, tiep tuc")
            except WriteBlockedError as exc:
                skipped_chapters.append(ch)
                log.append(f"⊘ ch{ch}: blocked — {exc}")
                log.append("  bo qua, tiep tuc chuong sau")
            except Exception as exc:
                skipped_chapters.append(ch)
                log.append(f"✗ ch{ch}: {exc}")
                if stop_on_review:
                    failed_ch = ch
                    err_msg = str(exc)
                    break
                log.append(f"  bo qua, tiep tuc chuong sau")
        else:
            parts = [f"{written} ch da viet"]
            if skipped_ready:
                parts.append(f"{skipped_ready} ready (bo qua)")
            if issue_chapters:
                parts.append(f"{len(issue_chapters)} can sua: ch{', ch'.join(map(str, issue_chapters))}")
            if skipped_chapters:
                parts.append(f"{len(skipped_chapters)} bo qua: ch{', ch'.join(map(str, skipped_chapters))}")
            log.append(f"--- Ket thuc batch: {'; '.join(parts)}")
    except Exception as exc:
        err_msg = str(exc)
        log.append(f"✗ batch write: {err_msg}")
    finally:
        batch_state.unregister_thread(workspace_id)
        completed_range = failed_ch is None
        _write_batch_progress(
            ws,
            {
                "running": False,
                "phase": "write",
                "ok": completed_range,
                "written": written,
                "failed_ch": failed_ch,
                "issue_chapters": issue_chapters,
                "skipped_chapters": skipped_chapters,
                "error": err_msg,
                "log": log,
            },
        )


def start_batch_write(
    workspace_id: str,
    book: int = 1,
    from_ch: int = 1,
    to_ch: int | None = None,
    *,
    stop_on_review: bool = False,
    auto_from: bool = False,
) -> dict:
    ws = workspace_dir(workspace_id)
    prog = get_batch_progress(workspace_id)
    if prog.get("running"):
        if _batch_is_active(workspace_id):
            hint = "doi batch hien tai xong"
            if prog.get("failed_ch"):
                hint = f"batch da dung o ch{prog['failed_ch']} — tat 'Dung khi QC fail' de chay het"
            return {"ok": False, "error": f"batch dang chay — {hint}", **prog}
        prog = reset_batch_lock(workspace_id)
    if not plan_is_approved(ws):
        return {"ok": False, "error": "plan chua approved — chay chuan bi sach truoc"}
    direction = _load_direction(ws)
    total = get_total_chapters(workspace_id, book)
    to_ch = min(to_ch or total, total)
    if auto_from:
        from_ch = _first_incomplete_chapter(ws, book, from_ch, to_ch)
    from_ch = max(1, min(from_ch, to_ch))

    def _target() -> None:
        try:
            _run_batch_write_loop(
                workspace_id, book, from_ch, to_ch, stop_on_review=stop_on_review
            )
        finally:
            batch_state.unregister_thread(workspace_id)

    t = threading.Thread(target=_target, daemon=True)
    batch_state.register_thread(workspace_id, t)
    t.start()
    return {
        "ok": True,
        "started": True,
        "phase": "write",
        "from_ch": from_ch,
        "to_ch": to_ch,
        "stop_on_review": stop_on_review,
    }


def start_batch_full(
    workspace_id: str,
    book: int = 1,
    from_ch: int = 1,
    to_ch: int | None = None,
    *,
    stop_on_review: bool = False,
    auto_from: bool = False,
) -> dict:
    ws = workspace_dir(workspace_id)
    prog = get_batch_progress(workspace_id)
    if prog.get("running"):
        if _batch_is_active(workspace_id):
            return {"ok": False, "error": "batch dang chay — doi xong hoac bam Huy lock", **prog}
        reset_batch_lock(workspace_id)

    def _full() -> None:
        try:
            prep = run_batch_prep(workspace_id, book)
            if not prep.get("ok"):
                return
            direction = _load_direction(ws)
            total = get_total_chapters(workspace_id, book)
            end = min(to_ch or total, total)
            start = from_ch
            if auto_from:
                start = _first_incomplete_chapter(ws, book, from_ch, end)
            _run_batch_write_loop(
                workspace_id, book, start, end, stop_on_review=stop_on_review
            )
        finally:
            batch_state.unregister_thread(workspace_id)

    t = threading.Thread(target=_full, daemon=True)
    batch_state.register_thread(workspace_id, t)
    t.start()
    return {"ok": True, "started": True, "phase": "full"}


def update_book_config(
    workspace_id: str,
    book: int,
    *,
    total_chapters: int,
) -> dict[str, Any]:
    result = set_total_chapters(workspace_id, book, total_chapters)
    return {**result, **pipeline_status(workspace_id, book)}


def run_export(
    workspace_id: str,
    target: str,
    book_slug: str | None = None,
    *,
    book: int | None = None,
) -> dict:
    cfg = load_config()
    book_num, slug = _resolve_book(workspace_id, book, book_slug)
    try:
        paths = export_book(workspace_id, slug, target, cover_path=None, cfg=cfg)
        out_dir = book_catalog_dir(workspace_id, slug) / "exports" / target
        payload: dict = {
            "ok": True,
            "export_dir": str(out_dir),
            "paths": [str(p) for p in paths],
            "book": book_num,
            "book_slug": slug,
        }
        gate_path = book_catalog_dir(workspace_id, slug) / "exports" / ".export_gate.json"
        if gate_path.exists():
            payload["export_gate"] = json.loads(gate_path.read_text(encoding="utf-8"))
        if target == "epub" and paths:
            qc_path = Path(paths[0]).with_suffix(".qc.json")
            if qc_path.exists():
                payload["epub_qc"] = json.loads(qc_path.read_text(encoding="utf-8"))
        return {**payload, **pipeline_status(workspace_id, book_num)}
    except Exception as exc:
        from factory.engine.lib.export_gate import ExportGateError

        payload: dict = {"ok": False, "error": str(exc), "book": book_num, "book_slug": slug}
        gate_path = book_catalog_dir(workspace_id, slug) / "exports" / ".export_gate.json"
        if isinstance(exc, ExportGateError) and gate_path.exists():
            payload["export_gate"] = json.loads(gate_path.read_text(encoding="utf-8"))
        return {**payload, **pipeline_status(workspace_id, book_num)}


def run_export_gate(
    workspace_id: str,
    book_slug: str | None = None,
    *,
    book: int | None = None,
) -> dict:
    from factory.engine.lib.export_gate import (
        format_export_gate_reasons,
        format_export_gate_summary,
        run_export_gate as _run_gate,
        save_export_gate_report,
    )

    cfg = load_config()
    book_num, slug = _resolve_book(workspace_id, book, book_slug)
    report = _run_gate(workspace_id, slug, cfg=cfg, scope="full")
    save_export_gate_report(workspace_id, slug, report)
    return {
        "ok": report.get("passed", False),
        "summary": format_export_gate_summary(report),
        "reasons": format_export_gate_reasons(report),
        "export_gate": report,
        "book": book_num,
        "book_slug": slug,
        **pipeline_status(workspace_id, book_num),
    }


def run_repair_catalog(
    workspace_id: str,
    book_slug: str | None = None,
    *,
    book: int | None = None,
) -> dict:
    from factory.engine.lib.catalog import repair_catalog_book

    book_num, slug = _resolve_book(workspace_id, book, book_slug)
    result = repair_catalog_book(workspace_id, slug, backup=True)
    sync = sync_pipeline_from_catalog(workspace_id, book=book_num, book_slug=slug)
    return {
        "ok": True,
        "fixed": result.get("fixed", 0),
        "cleared_needs_fix": result.get("cleared_needs_fix", 0),
        "backup": result.get("backup"),
        "target_language": result.get("target_language"),
        "pipeline_synced": len(sync.get("synced", [])),
        "book": book_num,
        "book_slug": slug,
        **pipeline_status(workspace_id, book_num),
    }


def run_qc_epub(
    workspace_id: str,
    book_slug: str | None = None,
    epub_path: str | None = None,
    *,
    book: int | None = None,
) -> dict:
    """Run EPUBCheck on existing or default catalog EPUB."""
    from factory.engine.lib.epub_qc import format_epub_qc_summary, qc_epub_file

    cfg = load_config()
    book_num, slug = _resolve_book(workspace_id, book, book_slug)
    if epub_path:
        epub = Path(epub_path)
    else:
        epub = book_catalog_dir(workspace_id, slug) / "exports" / "epub" / f"{slug}.epub"
    report = qc_epub_file(epub)
    return {
        "ok": report.get("ok", False) and report.get("passed", False),
        "epub_qc": report,
        "summary": format_epub_qc_summary(report),
        "book": book_num,
        "book_slug": slug,
        **pipeline_status(workspace_id, book_num),
    }
