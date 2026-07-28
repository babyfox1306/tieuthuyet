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
from factory.engine.lib.technical_refs import (
    derive_chapter_day_map,
    project_technical_chapter_refs,
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


def _pov_character_for_prompt(ws: Path, registry: CanonRegistry) -> str:
    """Read POV identity from concept/intent instead of assuming female lead."""
    try:
        from factory.engine.lib.narrative_schema import load_concept

        raw = load_concept(ws).get("pov")
        if isinstance(raw, dict):
            name = str(raw.get("character") or raw.get("name") or "").strip()
            if name:
                return name
    except (OSError, TypeError, ValueError):
        pass
    try:
        from factory.engine.lib.intent_manifest import load_intent_manifest

        pov = str(load_intent_manifest(ws, 1).get("pov") or "")
        name = pov.split("|")[0].split(",")[0].strip()
        if name:
            return name
    except (OSError, TypeError, ValueError):
        pass
    return registry.characters["female_lead"].canonical


def prompts_dir(ws: Path, book: int) -> Path:
    p = book_workspace_dir(ws, book) / "prompts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def master_plan_path(ws: Path, book: int) -> Path:
    return book_workspace_dir(ws, book) / "master_plan.json"


def spice_for_chapter(direction: dict, chapter: int) -> int:
    schedule = direction.get("spice_schedule")
    if isinstance(schedule, dict) and schedule:
        raw = schedule.get(chapter, schedule.get(str(chapter)))
        if raw is not None:
            level = int(raw)
            ceiling = int(
                direction.get("spice_max")
                if direction.get("spice_max") is not None
                else direction.get("spice_level") or 3
            )
            if level < 0 or level > 3 or level > ceiling:
                raise ValueError(
                    f"spice_schedule ch{chapter}={level} exceeds valid ceiling {ceiling}"
                )
            return level
        if chapter in direction.get("spice_explicit_chapters", []):
            raise ValueError(
                f"spice_schedule missing level for explicit chapter {chapter}"
            )
    ceiling = int(
        direction.get("spice_max")
        if direction.get("spice_max") is not None
        else direction.get("spice_level") or 3
    )
    if chapter in direction.get("spice_explicit_chapters", []):
        return ceiling
    if chapter in direction.get("spice_steamy_chapters", []):
        return min(2, ceiling)
    # Respect spice_max=0 books (gothic / no-romance); do not default them to sweet.
    if "spice_default" in direction:
        return int(direction.get("spice_default") or 0)
    spice_max = direction.get("spice_max")
    if spice_max is not None:
        return int(spice_max)
    return 1


def _genre_label(direction: dict, registry: CanonRegistry | None = None) -> str:
    raw = str(direction.get("narrative_profile") or "").strip()
    if not raw and registry is not None:
        # Intent genre may live only on direction sync; keep fallback readable
        raw = ""
    if not raw:
        return "commercial fiction"
    return raw.replace("_", " ").strip()


def _wants_romance_persona(direction: dict, *, spice_max: int, boundaries: list[str]) -> bool:
    """Romance GoodNovel persona only when book actually opts into romance heat."""
    profile = str(direction.get("narrative_profile") or "").lower()
    if any(x in profile for x in ("romance", "ngon tinh", "ngôn tình", "ceo", "billionaire")):
        return True
    if any(x in profile for x in ("gothic", "horror", "thriller", "mystery", "crime", "noir")):
        return False
    for b in boundaries:
        bl = str(b).lower()
        if "romance" in bl or "sexual content" in bl or "no romance" in bl:
            return False
    return spice_max >= 1


def role_header_for_prompt(
    *,
    lang: str,
    audience: str,
    direction: dict,
    registry: CanonRegistry | None,
    boundaries: list[str],
) -> str:
    from factory.engine.lib.language import language_profile

    prof = language_profile(lang)
    spice_max = int(registry.spice_max) if registry is not None else int(
        direction.get("spice_max")
        if direction.get("spice_max") is not None
        else direction.get("spice_default") or 1
    )
    if _wants_romance_persona(direction, spice_max=spice_max, boundaries=boundaries):
        return prof["role_header"].format(audience=audience)
    genre = _genre_label(direction, registry)
    template = prof.get("role_header_genre") or prof["role_header"]
    try:
        return template.format(audience=audience, genre=genre)
    except KeyError:
        return prof["role_header"].format(audience=audience)


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


def _content_boundaries_for_prompt(
    ws: Path | None,
    series_bible: dict | None,
    *,
    chapter: int | None = None,
) -> tuple[list[str], list[str]]:
    """Return (must_avoid, chapter must_include) — never mix under one MUST AVOID heading."""
    avoid: list[str] = []
    include: list[str] = []
    seen_avoid: set[str] = set()
    seen_include: set[str] = set()

    def _add(bucket: list[str], seen: set[str], raw: object) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        bucket.append(text)

    if ws is not None:
        from factory.engine.lib.intent_manifest import (
            load_intent_manifest,
            must_include_for_chapter,
        )
        from factory.engine.lib.narrative_schema import load_concept

        man = load_intent_manifest(ws)
        if man and man.get("status") == "approved":
            for item in man.get("must_avoid") or []:
                _add(avoid, seen_avoid, item)
            if chapter is not None:
                for item in must_include_for_chapter(man, chapter):
                    _add(include, seen_include, item)
        else:
            concept = load_concept(ws)
            for item in concept.get("must_avoid") or []:
                _add(avoid, seen_avoid, item)
    for item in (series_bible or {}).get("content_rules") or []:
        _add(avoid, seen_avoid, item)
    return avoid, include


def _world_rules_for_chapter(
    ws: Path | None,
    series_bible: dict | None,
    chapter: int,
) -> list[str]:
    """Filter world_rules by intent reveal_ladder — withhold spoiler rules early."""
    rules = [
        str(r).strip()
        for r in ((series_bible or {}).get("world_rules") or [])
        if str(r).strip()
    ]
    if ws is None or not rules:
        return rules
    from factory.engine.lib.intent_manifest import load_intent_manifest

    man = load_intent_manifest(ws)
    if not man or man.get("status") != "approved":
        return rules
    book_requirements = {
        re.sub(r"\s+", " ", str(item)).strip().casefold()
        for item in (man.get("must_include_book") or [])
        if str(item).strip()
    }
    # Narrative/bible generation may mirror the legacy flat list into
    # world_rules. Those copies are audit inputs, not global chapter rules.
    rules = [
        rule
        for rule in rules
        if re.sub(r"\s+", " ", rule).strip().casefold() not in book_requirements
    ]
    true = str(man.get("true_plot") or "").lower()
    surface = str(man.get("surface_plot") or "").lower()
    if not true or chapter >= int(man.get("chapter_count") or 99):
        return rules
    # Drop rules that expose true_plot before the canonical reader reveal.
    reveal_from = int(
        man.get("canonical_reveal_chapter")
        or max(3, int(man.get("chapter_count") or 10) - 2)
    )
    if chapter >= reveal_from:
        return rules
    filtered: list[str] = []
    true_tokens = set(re.findall(r"[a-zA-Zà-ỹÀ-Ỹ']{4,}", true))
    surface_tokens = set(re.findall(r"[a-zA-Zà-ỹÀ-Ỹ']{4,}", surface))
    hidden_tokens = true_tokens - surface_tokens
    for r in rules:
        rt = set(re.findall(r"[a-zA-Zà-ỹÀ-Ỹ']{4,}", r.lower()))
        if hidden_tokens and len(rt & hidden_tokens) / max(1, len(rt)) >= 0.50:
            continue
        filtered.append(r)
    return filtered

def render_locked_canon_block(
    registry: CanonRegistry,
    *,
    lang: str = "en",
    pov_character: str | None = None,
    content_boundaries: list[str] | None = None,
    must_include: list[str] | None = None,
    world_rules: list[str] | None = None,
    supporting_constraints: list[str] | None = None,
) -> str:
    """Non-negotiable canon rules — must appear above bible / story-so-far in writer prompts."""
    from factory.engine.lib.canon_registry import is_absent_male_lead

    male = registry.characters["male_lead"]
    female = registry.characters["female_lead"]
    pov_name = str(pov_character or female.canonical).strip()
    male_forbidden = ", ".join(male.forbidden_aliases) if male.forbidden_aliases else ""
    female_forbidden = (
        ", ".join(female.forbidden_aliases) if female.forbidden_aliases else ""
    )
    if registry.spice_max <= 0:
        spice_line = (
            f"Spice: MAX level {registry.spice_max}. "
            "No romance heat, no kissing as romantic beat, no sexual tension or fade-to-black intimacy."
            if lang != "vi"
            else f"Spice: MAX level {registry.spice_max}. Không romance / hôn / căng tình dục."
        )
    elif registry.spice_max == 1:
        spice_line = (
            f"Spice: MAX level {registry.spice_max}. "
            "No on-page explicit sex. Fade to black beyond kiss/tension."
            if lang != "vi"
            else f"Spice: MAX level {registry.spice_max}. Không sex on-page; fade sau hôn/căng."
        )
    elif registry.spice_max == 2:
        spice_line = (
            f"Spice: MAX level {registry.spice_max}. "
            "Steamy tension/kissing allowed; no explicit sex."
        )
    else:
        spice_line = f"Spice: MAX level {registry.spice_max}."

    pov_mode = str(registry.pov_mode or "third_person_limited").strip().lower().replace("-", "_")
    avoid = [str(b).strip() for b in (content_boundaries or []) if str(b).strip()]
    # Legacy callers may still pass "MUST INCLUDE …" into content_boundaries — peel them out.
    peeled_include: list[str] = []
    clean_avoid: list[str] = []
    for b in avoid:
        if b.upper().startswith("MUST INCLUDE"):
            peeled = re.sub(r"(?i)^MUST INCLUDE(\s*\(this chapter\))?\s*:\s*", "", b).strip()
            if peeled:
                peeled_include.append(peeled)
        else:
            clean_avoid.append(b)
    include = [str(b).strip() for b in (must_include or []) if str(b).strip()]
    include = include + [x for x in peeled_include if x.lower() not in {i.lower() for i in include}]

    if clean_avoid:
        bound_heading = "Content boundaries (MUST AVOID):" if lang != "vi" else "Ranh giới nội dung (CẤM):"
        bound_block = bound_heading + "\n" + "\n".join(f"- {b}" for b in clean_avoid)
    else:
        bound_block = ""

    if include:
        inc_heading = (
            "Required this chapter (MUST INCLUDE):"
            if lang != "vi"
            else "Bắt buộc chương này (MUST INCLUDE):"
        )
        include_block = inc_heading + "\n" + "\n".join(f"- {b}" for b in include)
    else:
        include_block = ""

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

    if "first" in pov_mode:
        if lang == "vi":
            pov_line = (
                f"POV: first_person — ngôi 1 khóa vào {pov_name}. "
                f"Toàn bộ narration dùng Tôi/I. CẤM ngôi 3 kể về {pov_name} "
                f"(không viết '{pov_name} đã…' ngoài dialogue)."
            )
        else:
            pov_line = (
                f"POV: first_person — narrate ONLY as {pov_name} using I/my/me. "
                f"FORBIDDEN: third-person narration about {pov_name} "
                f"(do not write '{pov_name} walked…' outside quoted dialogue)."
            )
    else:
        if lang == "vi":
            pov_line = (
                f"POV: {pov_mode}. Ngôi 3 hạn chế khóa vào {pov_name}. "
                'CẤM ngôi 1 ("tôi/I/my/me") ngoài thoại trong ngoặc kép.'
            )
        else:
            pov_line = (
                f"POV: {pov_mode}. Third-person limited locked to {pov_name}. "
                'NO first-person ("I/my/me") narration outside quoted dialogue.'
            )

    male_line = f"Male lead: {male.canonical} ONLY."
    if male_forbidden:
        male_line += f" Never write: {male_forbidden}."
    female_line = f"Female lead: {female.canonical} ONLY."
    if female_forbidden:
        female_line += f" Never write: {female_forbidden}."

    parts = [
        "## LOCKED CANON — ABSOLUTE, DO NOT VIOLATE",
        male_line,
        female_line,
        pov_line,
        spice_line,
    ]
    if is_absent_male_lead(male.canonical):
        parts.append(
            "NO male ROMANCE lead / love interest. Do NOT invent a caretaker romance, "
            "physically-present romantic doctor, or [ROMANCE] subplot with an invented man. "
            "Named male characters who are husband / target / victim / antagonist are ALLOWED "
            "when listed under LOCKED NAMES (use that exact name — do not invent a second name). "
            "Emotional tension stays with mystery/isolation (no romance subplot). "
            "Do NOT invent named doctors beyond declared supporting cast."
            if lang != "vi"
            else "KHÔNG có male love-interest. CẤM bịa romance / bác sĩ romantic / [ROMANCE]. "
            "Nhân vật nam husband/target/victim/antagonist ĐƯỢC phép nếu nằm trong LOCKED NAMES "
            "(đúng tên khóa — cấm bịa tên thứ hai)."
        )
    if support_block:
        parts.append(support_block)
    if bound_block:
        parts.append(bound_block)
    if include_block:
        parts.append(include_block)
    # Unexplained coda voice must not be read as "secretly alive"
    avoid_blob = " ".join(clean_avoid).lower()
    include_blob = " ".join(include).lower()
    coda_markers = ("whisper", "you came back", "unexplained voice", "unexplained final")
    if (
        ("secretly alive" in avoid_blob or "còn sống bí mật" in avoid_blob)
        and any(k in include_blob for k in coda_markers)
    ):
        parts.append(
            "NOTE: An unexplained voice/recording is NOT proof of secret survival — "
            "do not revive the deceased as a living character; leave the coda unexplained."
            if lang != "vi"
            else "NOTE: Giọng/recording unexplained KHÔNG chứng minh còn sống bí mật — "
            "cấm hồi sinh người chết; để coda không giải thích."
        )
    if rules_block:
        parts.append(rules_block)
    parts.append("If any instruction below conflicts with this block, THIS BLOCK WINS.")
    return "\n".join(parts)


def _load_canon_registry_for_prompt(ws: Path, direction: dict) -> CanonRegistry:
    from factory.engine.lib.canon_registry import build_canon_registry

    book = int(direction.get("book") or 1)
    return build_canon_registry(ws, book)


def _is_final_chapter(
    direction: dict,
    registry: CanonRegistry | None,
    chapter: int,
) -> bool:
    total = 0
    if registry is not None:
        try:
            total = int(registry.chapter_count or 0)
        except (TypeError, ValueError):
            total = 0
    if not total:
        try:
            total = int(direction.get("total_chapters") or 0)
        except (TypeError, ValueError):
            total = 0
    return bool(total) and int(chapter) >= int(total)


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
    chapter_days = derive_chapter_day_map([*prior_plans, plan])

    def writer_projection(value: str) -> str:
        return project_technical_chapter_refs(
            value,
            chapter_days,
            current_chapter=chapter,
        )

    prof = language_profile(lang)

    registry: CanonRegistry | None = None
    locked_canon_block = ""
    boundaries: list[str] = []
    chapter_must_include: list[str] = []
    if ws is not None:
        registry = _load_canon_registry_for_prompt(ws, direction)
        boundaries, chapter_must_include = _content_boundaries_for_prompt(
            ws, series_bible, chapter=chapter
        )
        world_rules = _world_rules_for_chapter(ws, series_bible, chapter)
        from factory.engine.lib.canon_registry import phone_only_cast_constraints

        locked_canon_block = render_locked_canon_block(
            registry,
            lang=lang,
            pov_character=_pov_character_for_prompt(ws, registry),
            content_boundaries=boundaries,
            must_include=chapter_must_include,
            world_rules=world_rules,
            supporting_constraints=phone_only_cast_constraints(ws),
        )

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
    # spice=0 must NOT fall back to Level 1 sweet
    spice_block = spice_blocks.get(spice, "")
    if not spice_block and spice > 0:
        spice_block = spice_blocks.get(1, "")
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
    prior = writer_projection(prior)
    must_not = coerce_text_list(plan.get("must_not", []))
    must_not = [writer_projection(item) for item in must_not]
    opaque_knowledge_bans: list[str] = []
    visible_must_not: list[str] = []
    for item in must_not:
        match = re.match(
            r"^\s*([^:.;]{2,80}?)\s+must\s+not\s+"
            r"(?:know|learn|discover|realize|understand)\b",
            str(item),
            re.I,
        )
        if match:
            character = match.group(1).strip()
            opaque_knowledge_bans.append(
                f"{character}: knowledge is closed-world; use only direct observations "
                "and scheduled chapter facts. Do not infer hidden causes or future discoveries."
            )
        else:
            visible_must_not.append(str(item))
    must_not = list(dict.fromkeys(visible_must_not + opaque_knowledge_bans))
    must_happen = coerce_text_list(plan.get("must_happen", []))
    must_happen = [writer_projection(item) for item in must_happen]
    opens = plan.get("opens_with", plan.get("hook_hint", ""))
    if not isinstance(opens, str):
        opens = coerce_text_field(opens)
    opens = writer_projection(opens)
    cliff = plan.get("cliffhanger", "")
    if not isinstance(cliff, str):
        cliff = coerce_text_field(cliff)
    cliff = writer_projection(cliff)
    sig = plan.get("signature_detail_hint", "")
    if not isinstance(sig, str):
        sig = coerce_text_field(sig)
    sig = writer_projection(sig)
    title = plan.get("title", f"Chương {chapter}")
    if not isinstance(title, str):
        title = coerce_text_field(title)
    task_body = plan.get("chapter_task") or plan.get("beat_summary", "")
    if not isinstance(task_body, str):
        task_body = coerce_text_field(task_body)
    task_body = writer_projection(task_body)

    must_block = ""
    if must_happen:
        lock_heading = (
            "## MUST HAPPEN — HỢP ĐỒNG KHÓA (cấm bại)"
            if lang == "vi"
            else "## MUST HAPPEN — LOCKED CONTRACT (do not betray)"
        )
        lock_note = (
            "Batch đã sinh các beat sau. Viết ĐỦ mọi mục thành scene trong chương — "
            "cấm bỏ, đổi, hoặc thay bằng nhánh khác."
            if lang == "vi"
            else "These beats were machine-generated at plan time. Realize EVERY item as "
            "on-page scene — do not drop, swap, or invent a different plot branch."
        )
        numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(must_happen, 1))
        must_block += f"\n{lock_heading}\n{lock_note}\n**{prof['must_happen_label']}:**\n{numbered}"
    if must_not:
        must_block += f"\n**{prof['must_not_label']}:** " + "; ".join(must_not)

    audience = direction.get("audience") or (
        "Độc giả nữ 18-35" if lang == "vi" else "Adult readers 18+"
    )
    ch_label = f"Chương {chapter}" if lang == "vi" else f"Chapter {chapter}"
    open_label = "Mở bằng móc câu:" if lang == "vi" else "Open with hook:"
    cliff_label = "Kết cliffhanger:" if lang == "vi" else "End cliffhanger:"
    write_label = "Viết" if lang == "vi" else "Write"

    header = role_header_for_prompt(
        lang=lang,
        audience=str(audience),
        direction=direction,
        registry=registry,
        boundaries=list(boundaries),
    )
    parts = [header]
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
            build_tech_rules(
                prof,
                min_words=int(cfg.get("min_word_count", 1250)),
                bible=series_bible,
                is_final_chapter=_is_final_chapter(direction, registry, chapter),
            ),
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
            chapter_days=chapter_days,
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
