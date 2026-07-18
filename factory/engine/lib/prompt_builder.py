"""Build chapter prompts in format prompt_chapter3_ceo_explicit.txt."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from factory.engine.lib.bible_schema import render_bible_block
from factory.engine.lib.language import (
    apply_lead_placeholders,
    build_tech_rules,
    language_profile,
    target_language,
)
from factory.engine.lib.narrative_compiler import (
    load_ledger,
    narrative_constraints_block_for_prompt,
)
from factory.engine.lib.plan_normalize import (
    coerce_text_field,
    coerce_text_list,
    locked_plans_look_vietnamese_legacy,
    normalize_chapter_plan,
    normalize_chapter_plans,
)
from factory.engine.paths import bible_path, book_workspace_dir, load_config, workspace_dir

if TYPE_CHECKING:
    from factory.engine.lib.canon_registry import CanonRegistry


def load_series_bible(ws: Path) -> dict:
    path = bible_path(ws)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_direction(ws: Path) -> dict:
    path = ws / "direction.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def prompts_dir(ws: Path, book: int) -> Path:
    p = book_workspace_dir(ws, book) / "prompts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def master_plan_path(ws: Path, book: int) -> Path:
    return book_workspace_dir(ws, book) / "master_plan.json"


def spice_for_chapter(direction: dict, chapter: int) -> int:
    if chapter in direction.get("spice_explicit_chapters", []):
        return 3
    if chapter in direction.get("spice_steamy_chapters", []):
        return 2
    return int(direction.get("spice_default", 1))


def format_prior_summaries(
    plans: list[dict],
    through_ch: int,
    *,
    empty_line: str,
    max_chapters: int | None = 5,
    registry: CanonRegistry | None = None,
) -> str:
    lines = []
    for raw in plans:
        p = normalize_chapter_plan(raw)
        ch = p.get("chapter", 0)
        if ch >= through_ch:
            break
        summary = p.get("one_line_summary") or p.get("beat_summary", "")
        if summary:
            if registry is not None:
                from factory.engine.lib.canon_registry import sanitize_text_for_registry

                summary = sanitize_text_for_registry(str(summary), registry)
            lines.append(f"- Ch{ch}: {summary}")
    if max_chapters and len(lines) > max_chapters:
        lines = lines[-max_chapters:]
    return "\n".join(lines) if lines else empty_line


def _content_boundaries_for_prompt(ws: Path | None, series_bible: dict | None) -> list[str]:
    """Operator content boundaries from concept.must_avoid (+ bible content_rules)."""
    lines: list[str] = []
    seen: set[str] = set()

    def _add(raw: object) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        lines.append(text)

    if ws is not None:
        from factory.engine.lib.narrative_schema import load_concept

        concept = load_concept(ws)
        for item in concept.get("must_avoid") or []:
            _add(item)
    for item in (series_bible or {}).get("content_rules") or []:
        _add(item)
    return lines


def render_locked_canon_block(
    registry: CanonRegistry,
    *,
    lang: str = "en",
    content_boundaries: list[str] | None = None,
    world_rules: list[str] | None = None,
    supporting_constraints: list[str] | None = None,
) -> str:
    """Non-negotiable canon rules — must appear above bible / story-so-far in writer prompts."""
    from factory.engine.lib.canon_registry import is_absent_male_lead

    male = registry.characters["male_lead"]
    female = registry.characters["female_lead"]
    male_forbidden = ", ".join(male.forbidden_aliases) if male.forbidden_aliases else "(none)"
    female_forbidden = (
        ", ".join(female.forbidden_aliases) if female.forbidden_aliases else "(none)"
    )
    if registry.spice_max <= 1:
        spice_line = (
            f"Spice: MAX level {registry.spice_max}. "
            "No on-page explicit sex. Fade to black beyond kiss/tension."
        )
    elif registry.spice_max == 2:
        spice_line = (
            f"Spice: MAX level {registry.spice_max}. "
            "Steamy tension/kissing allowed; no explicit sex."
        )
    else:
        spice_line = f"Spice: MAX level {registry.spice_max}."

    pov_mode = registry.pov_mode or "third_person_limited"
    boundaries = [str(b).strip() for b in (content_boundaries or []) if str(b).strip()]
    if boundaries:
        bound_heading = "Content boundaries (MUST AVOID):" if lang != "vi" else "Ranh giới nội dung (CẤM):"
        bound_block = bound_heading + "\n" + "\n".join(f"- {b}" for b in boundaries)
    else:
        bound_block = ""

    rules = [str(r).strip() for r in (world_rules or []) if str(r).strip()]
    if rules:
        rules_heading = "World rules (HARD):" if lang != "vi" else "Luật thế giới (CỨNG):"
        rules_block = rules_heading + "\n" + "\n".join(f"- {r}" for r in rules)
    else:
        rules_block = ""

    support = [str(s).strip() for s in (supporting_constraints or []) if str(s).strip()]
    if support:
        support_heading = (
            "Supporting cast (HARD):" if lang != "vi" else "Cast phụ (CỨNG):"
        )
        support_block = support_heading + "\n" + "\n".join(f"- {s}" for s in support)
    else:
        support_block = ""

    parts = [
        "## LOCKED CANON — ABSOLUTE, DO NOT VIOLATE",
        f"Male lead: {male.canonical} ONLY. Never write: {male_forbidden}.",
        f"Female lead: {female.canonical} ONLY. Never write: {female_forbidden}.",
        (
            f"POV: {pov_mode}. Third-person limited locked to {female.canonical}. "
            'NO first-person ("I/my/me") narration outside quoted dialogue.'
        ),
        spice_line,
    ]
    if is_absent_male_lead(male.canonical):
        parts.append(
            "NO male lead exists. Do NOT invent a love interest, caretaker romance, "
            "physically-present romantic doctor, or [ROMANCE] subplot with an invented man. "
            "Emotional tension stays with mystery/isolation only. "
            "Do NOT invent named doctors beyond declared supporting cast."
            if lang != "vi"
            else "KHÔNG có male lead. CẤM bịa love interest / bác sĩ romantic / [ROMANCE]."
        )
    if support_block:
        parts.append(support_block)
    if bound_block:
        parts.append(bound_block)
    if rules_block:
        parts.append(rules_block)
    parts.append("If any instruction below conflicts with this block, THIS BLOCK WINS.")
    return "\n".join(parts)


def _load_canon_registry_for_prompt(ws: Path, direction: dict) -> CanonRegistry:
    from factory.engine.lib.canon_registry import build_canon_registry

    book = int(direction.get("book") or 1)
    return build_canon_registry(ws, book)


def _warn_spice_capped(chapter: int, plan_spice: int, capped: int) -> None:
    from factory.engine.lib.catalog import safe_print

    safe_print(
        f"  [prompt] WARN ch_{chapter:03d}: plan spice {plan_spice} > registry max "
        f"{capped} — emitting spice level {capped} for writer (fix plan; approve-plan should catch)"
    )


def build_chapter_prompt(
    plan: dict,
    *,
    prior_plans: list[dict],
    direction: dict,
    chapter: int,
    cfg: dict | None = None,
    series_bible: dict | None = None,
    ws: Path | None = None,
) -> str:
    cfg = cfg or load_config()
    lang = target_language(direction, cfg)
    plan = normalize_chapter_plan(plan)
    prof = language_profile(lang)

    registry: CanonRegistry | None = None
    locked_canon_block = ""
    if ws is not None:
        registry = _load_canon_registry_for_prompt(ws, direction)
        boundaries = _content_boundaries_for_prompt(ws, series_bible)
        world_rules = [
            str(r).strip()
            for r in ((series_bible or {}).get("world_rules") or [])
            if str(r).strip()
        ]
        # Prefer concept compiler over vague bible "touches the clause" rules
        from factory.engine.lib.concept_canon import (
            compile_chapter_canon_rules,
            format_chapter_canon_for_prompt,
        )
        from factory.engine.lib.narrative_schema import load_concept

        concept = load_concept(ws)
        chapter_rules = compile_chapter_canon_rules(concept, chapter)
        if chapter_rules.reveal_state != "none":
            # Drop ambiguous touch-style world rules when structured pair exists
            world_rules = [
                r
                for r in world_rules
                if "touches the clause" not in r.lower()
                and "stated identically in every chapter that touches" not in r.lower()
            ]
        from factory.engine.lib.canon_registry import phone_only_cast_constraints

        locked_canon_block = render_locked_canon_block(
            registry,
            lang=lang,
            content_boundaries=boundaries,
            world_rules=world_rules,
            supporting_constraints=phone_only_cast_constraints(ws),
        )
        clause_block = format_chapter_canon_for_prompt(chapter_rules, lang=lang)
        if clause_block:
            locked_canon_block = locked_canon_block + "\n\n" + clause_block

    reveal_ch: int | None = None
    if ws is not None:
        try:
            ledger = load_ledger(ws)
            rc = ledger.get("canonical_reveal_chapter")
            if rc:
                reveal_ch = int(rc)
        except (OSError, TypeError, ValueError):
            pass
    if reveal_ch is None and series_bible:
        try:
            reveal_ch = int((series_bible.get("central_mystery") or {}).get("reveal_chapter") or 0) or None
        except (TypeError, ValueError):
            reveal_ch = None
    bible_block = render_bible_block(
        series_bible or {},
        lang=lang,
        reveal_chapter=reveal_ch,
        chapter=chapter,
    )

    plan_spice_raw = plan.get("spice", spice_for_chapter(direction, chapter))
    try:
        spice = int(plan_spice_raw)
    except (TypeError, ValueError):
        spice = spice_for_chapter(direction, chapter)
    if registry is not None and spice > registry.spice_max:
        _warn_spice_capped(chapter, spice, registry.spice_max)
        spice = registry.spice_max

    spice_extra = plan.get("spice_note", "").strip()
    spice_blocks = prof.get("spice", {})
    spice_block = spice_blocks.get(spice, spice_blocks.get(1, ""))
    spice_block = apply_lead_placeholders(spice_block, series_bible)
    if spice == 3 and spice_extra:
        ctx = "Bối cảnh cảnh 18+:" if lang == "vi" else "18+ scene context:"
        spice_block = spice_block + f"\n- **{ctx}** {spice_extra}"

    prior = format_prior_summaries(
        prior_plans,
        chapter,
        empty_line=prof["prior_empty"],
        max_chapters=int(cfg.get("story_so_far_max_chapters", 5) or 0) or None,
        registry=registry,
    )
    must_not = coerce_text_list(plan.get("must_not", []))
    must_happen = coerce_text_list(plan.get("must_happen", []))
    opens = plan.get("opens_with", plan.get("hook_hint", ""))
    if not isinstance(opens, str):
        opens = coerce_text_field(opens)
    cliff = plan.get("cliffhanger", "")
    if not isinstance(cliff, str):
        cliff = coerce_text_field(cliff)
    sig = plan.get("signature_detail_hint", "")
    if not isinstance(sig, str):
        sig = coerce_text_field(sig)
    title = plan.get("title", f"Chương {chapter}")
    if not isinstance(title, str):
        title = coerce_text_field(title)
    task_body = plan.get("chapter_task") or plan.get("beat_summary", "")
    if not isinstance(task_body, str):
        task_body = coerce_text_field(task_body)

    must_block = ""
    if must_happen:
        must_block += f"\n**{prof['must_happen_label']}:** " + "; ".join(must_happen)
    if must_not:
        must_block += f"\n**{prof['must_not_label']}:** " + "; ".join(must_not)

    audience = direction.get("audience", "Độc giả nữ 18-35")
    ch_label = f"Chương {chapter}" if lang == "vi" else f"Chapter {chapter}"
    open_label = "Mở bằng móc câu:" if lang == "vi" else "Open with hook:"
    cliff_label = "Kết cliffhanger:" if lang == "vi" else "End cliffhanger:"
    write_label = "Viết" if lang == "vi" else "Write"

    parts = [prof["role_header"].format(audience=audience)]
    if locked_canon_block:
        parts.extend(["", locked_canon_block])
    parts.extend(
        [
            "",
            bible_block,
            "",
            f"## {prof['prior_heading']}",
            prior,
            "",
            build_tech_rules(prof, min_words=int(cfg.get("min_word_count", 1250)), bible=series_bible),
        ]
    )
    if sig:
        sig_heading = "SIGNATURE DETAIL GỢI Ý" if lang == "vi" else "SIGNATURE DETAIL HINT"
        parts.extend(["", f"## {sig_heading}", sig])
    if spice_block:
        parts.extend(["", spice_block])
    # Narrative OS → Writer: always from compiler, never from master_plan.narrative
    if ws is not None:
        narrative_block = narrative_constraints_block_for_prompt(
            ws,
            chapter,
            lang=lang,
            locked_plan=bool(plan.get("locked")),
        )
        if narrative_block:
            parts.extend(["", narrative_block])
    parts.extend(
        [
            "",
            f"## {prof['task_heading']}",
            f"{write_label} **{ch_label}: {title}** hoàn chỉnh." if lang == "vi" else f"{write_label} **{ch_label}: {title}** complete.",
            task_body,
        ]
    )
    if opens:
        parts.append(f"{open_label} {opens}")
    if cliff:
        parts.append(f"{cliff_label} {cliff}")
    parts.append(must_block)
    parts.extend(["", prof["output_instruction"]])
    return "\n".join(p for p in parts if p is not None).strip() + "\n"


def render_all_prompts(ws: Path, book: int) -> int:
    from factory.engine.lib.concept_canon import require_fresh_plan

    require_fresh_plan(ws)
    plan_path = master_plan_path(ws, book)
    if not plan_path.exists():
        raise FileNotFoundError(f"Missing {plan_path} — chạy `plan` trước")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    direction = load_direction(ws)
    cfg = load_config()
    series_bible = load_series_bible(ws)
    plans = normalize_chapter_plans(data.get("chapter_plans", data.get("chapter_beats", [])))
    if plans != data.get("chapter_plans", []):
        data["chapter_plans"] = plans
        plan_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    out_dir = prompts_dir(ws, book)
    count = 0
    for plan in sorted(plans, key=lambda x: x.get("chapter", 0)):
        ch = plan["chapter"]
        prior = [p for p in plans if p.get("chapter", 0) < ch]
        text = build_chapter_prompt(
            plan,
            prior_plans=prior,
            direction=direction,
            chapter=ch,
            cfg=cfg,
            series_bible=series_bible,
            ws=ws,
        )
        (out_dir / f"ch_{ch:03d}.txt").write_text(text, encoding="utf-8")
        count += 1
    return count


def prompt_path(ws: Path, book: int, ch: int) -> Path:
    return prompts_dir(ws, book) / f"ch_{ch:03d}.txt"


def locked_plans_path(ws: Path) -> Path:
    return bible_path(ws).parent / "locked_chapter_plans.json"


def load_locked_chapter_plans(ws: Path) -> list[dict]:
    """Workspace-specific locked plans (data file, not engine code)."""
    path = locked_plans_path(ws)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    plans = data.get("chapter_plans", [])
    direction = load_direction(ws)
    lang = target_language(direction)
    if lang == "en" and locked_plans_look_vietnamese_legacy(plans):
        return []
    return plans


def canon_summaries_for_seed(ws: Path) -> list[dict]:
    """Locked chapter summaries for plan continuity — from workspace data."""
    return load_locked_chapter_plans(ws)
