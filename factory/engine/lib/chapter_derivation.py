"""Derive all chapter references from total_chapters — no orphan constants."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

# Canonical 50-chapter template ratios (used only as proportions, not as literals).
TEMPLATE_TOTAL = 50
TEMPLATE_MILESTONES = [1, 10, 25, 36, 50]
MILESTONE_FRACTIONS = [m / TEMPLATE_TOTAL for m in TEMPLATE_MILESTONES]

CHAPTER_FIELD_NAMES = frozenset(
    {
        "opened_chapter",
        "must_close_by",
        "must_payoff_by",
        "plant_chapter",
        "payoff_chapter",
        "debunked_chapter",
        "reveal_chapter",
        "canonical_reveal_chapter",
        "must_not_know_before",
    }
)

# Strict chapter refs only — NEVER match quantity words ("countless") or
# synonyms like "count"/"less" (those produced the "chapterless" prose leak).
_CHAPTER_IN_TEXT = re.compile(
    r"\b(?:chapter|ch)\s+(\d{1,3})\b|"
    r"\bchapters?\s+(\d{1,3})\s*[–\-]\s*(\d{1,3})\b",
    re.IGNORECASE,
)
_CHAPTER_RANGE_RE = re.compile(
    r"\bchapters?\s+(\d{1,3})\s*([–\-])\s*(\d{1,3})\b",
    re.IGNORECASE,
)
_CHAPTER_SINGLE_RE = re.compile(
    r"\b((?:chapter|ch)\s+)(\d{1,3})\b",
    re.IGNORECASE,
)
_CH_KEY = re.compile(r"^ch(\d+)$", re.IGNORECASE)

def is_prose_path(path: Path | str) -> bool:
    """True for pipeline chapter .txt/.md or catalog chapter bodies."""
    s = str(path).replace("\\", "/").lower()
    if "/pipeline/" in s and (s.endswith(".txt") or s.endswith(".md")):
        return True
    if "/chapters/" in s and s.endswith(".md"):
        return True
    if "/spot_check/" in s and s.endswith(".md"):
        return True
    return False


def derive_milestones(total: int) -> list[int]:
    """Five knowledge milestones scaled to book length (always includes 1 and N)."""
    total = max(3, int(total))
    raw = [max(1, min(total, round(total * frac))) for frac in MILESTONE_FRACTIONS]
    ms = sorted(set(raw))
    if ms[0] != 1:
        ms.insert(0, 1)
    if ms[-1] != total:
        ms.append(total)
    return ms


def rescale_chapter(ch: int, from_total: int, to_total: int) -> int:
    if ch <= 0:
        return ch
    if from_total <= 0 or from_total == to_total:
        return max(1, min(to_total, int(ch)))
    scaled = round(int(ch) * to_total / from_total)
    return max(1, min(to_total, scaled))


def rescale_chapter_optional(
    value: Any, from_total: int, to_total: int, *, end_of_book: bool = False
) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().isdigit():
        ch = int(value.strip())
        if end_of_book and ch >= max(1, from_total - 1):
            return to_total
        return rescale_chapter(ch, from_total, to_total)
    if isinstance(value, (int, float)):
        ch = int(value)
        if end_of_book and ch >= max(1, from_total - 1):
            return to_total
        return rescale_chapter(ch, from_total, to_total)
    if isinstance(value, str):
        return rescale_text_chapters(value, from_total, to_total)
    return value


def rescale_text_chapters(text: str, from_total: int, to_total: int) -> str:
    """Rewrite explicit ``chapter N`` / ``chapters A-B`` refs in structured notes.

    Never matches quantity words (``countless``, ``endless``) or bare numerals.
    Must only be applied to plan/narrative/config string fields — never prose files.
    """
    if not text or from_total <= 0 or from_total == to_total:
        return text

    def _sub_range(m: re.Match[str]) -> str:
        a, b = int(m.group(1)), int(m.group(3))
        ra = rescale_chapter(a, from_total, to_total)
        rb = rescale_chapter(b, from_total, to_total)
        sep = m.group(2)
        return f"chapters {ra}{sep}{rb}"

    out = _CHAPTER_RANGE_RE.sub(_sub_range, text)
    out = _CHAPTER_SINGLE_RE.sub(
        lambda m: f"{m.group(1)}{rescale_chapter(int(m.group(2)), from_total, to_total)}",
        out,
    )
    return out

def _collect_chapter_numbers(obj: Any, found: set[int]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in CHAPTER_FIELD_NAMES and isinstance(val, (int, float)):
                found.add(int(val))
            if key == "chapters" and isinstance(val, list):
                for item in val:
                    if isinstance(item, (int, float)):
                        found.add(int(item))
            m = _CH_KEY.match(str(key))
            if m:
                found.add(int(m.group(1)))
            if isinstance(val, str):
                for match in _CHAPTER_IN_TEXT.finditer(val):
                    for g in match.groups():
                        if g:
                            found.add(int(g))
            _collect_chapter_numbers(val, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_chapter_numbers(item, found)


def infer_narrative_extent(ws: Path) -> int:
    """Largest chapter number referenced in bible/narrative/*.json."""
    nd = ws / "bible" / "narrative"
    if not nd.exists():
        return 0
    found: set[int] = set()
    for path in nd.glob("*.json"):
        try:
            _collect_chapter_numbers(json.loads(path.read_text(encoding="utf-8")), found)
        except (json.JSONDecodeError, OSError):
            continue
    return max(found) if found else 0


def orphans_above_total(ws: Path, total: int) -> list[str]:
    """Human-readable list of chapter refs > total (for QC warnings)."""
    total = int(total)
    issues: list[str] = []
    nd = ws / "bible" / "narrative"
    if not nd.exists():
        return issues

    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                loc = f"{path}.{key}" if path else key
                if key in CHAPTER_FIELD_NAMES and isinstance(val, (int, float)):
                    if int(val) > total:
                        issues.append(f"{loc}={int(val)}")
                if key == "milestones" and isinstance(val, list):
                    for i, item in enumerate(val):
                        if isinstance(item, (int, float)) and int(item) > total:
                            issues.append(f"{loc}[{i}]={int(item)}")
                if key == "chapters" and isinstance(val, list):
                    for i, item in enumerate(val):
                        if isinstance(item, (int, float)) and int(item) > total:
                            issues.append(f"{loc}[{i}]={int(item)}")
                m = _CH_KEY.match(str(key))
                if m and int(m.group(1)) > total:
                    issues.append(f"{loc} key ch{m.group(1)}")
                if isinstance(val, str):
                    for match in _CHAPTER_IN_TEXT.finditer(val):
                        nums = [int(g) for g in match.groups() if g]
                        for n in nums:
                            if n > total:
                                issues.append(f"{loc} text mentions ch{n}")
                _walk(val, loc)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    for fpath in sorted(nd.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        _walk(data, fpath.name)
    return issues


def patch_book_arc(arc: dict[str, Any], total: int, book: int) -> dict[str, Any]:
    from factory.engine.lib.workspace_metadata import scale_act_arc

    arc = deepcopy(arc)
    arc["total_chapters"] = total
    arc["book_number"] = book
    scaled = scale_act_arc(total)
    act_names = ("Setup", "Complications", "Crisis", "Resolution")
    act_keys = (
        "act1_setup",
        "act2_complications",
        "act3_crisis",
        "act4_resolution",
    )
    acts = list(arc.get("act_structure") or [])
    for i, key in enumerate(act_keys):
        bounds = scaled[key]
        if i < len(acts) and isinstance(acts[i], dict):
            acts[i] = {**acts[i], "chapters": list(bounds)}
        else:
            acts.append(
                {
                    "act": i + 1,
                    "name": act_names[i] if i < len(act_names) else f"Act {i + 1}",
                    "chapters": list(bounds),
                    "summary": "",
                }
            )
    arc["act_structure"] = acts[:4]
    return arc


def rescale_knowledge_matrix(
    matrix: dict[str, Any], from_total: int, to_total: int
) -> dict[str, Any]:
    matrix = deepcopy(matrix)
    old_ms = list(matrix.get("milestones") or TEMPLATE_MILESTONES)
    new_ms = derive_milestones(to_total)
    matrix["milestones"] = new_ms

    old_by_ch = {int(m): i for i, m in enumerate(old_ms)}
    new_chars: dict[str, Any] = {}
    for name, char in (matrix.get("characters") or {}).items():
        if not isinstance(char, dict):
            new_chars[name] = char
            continue
        remapped: dict[str, Any] = {}
        for key, val in char.items():
            m = _CH_KEY.match(str(key))
            if m:
                old_ch = int(m.group(1))
                if old_ch in old_by_ch:
                    new_ch = new_ms[old_by_ch[old_ch]]
                else:
                    new_ch = rescale_chapter(old_ch, from_total, to_total)
                remapped[f"ch{new_ch}"] = val
            elif key == "must_not_know_before":
                remapped[key] = rescale_chapter_optional(val, from_total, to_total)
            else:
                remapped[key] = (
                    rescale_text_chapters(val, from_total, to_total)
                    if isinstance(val, str)
                    else val
                )
        new_chars[name] = remapped
    matrix["characters"] = new_chars
    return matrix


def rescale_mystery_ledger(
    ledger: dict[str, Any], from_total: int, to_total: int
) -> dict[str, Any]:
    ledger = deepcopy(ledger)
    for key in ("canonical_reveal_chapter",):
        if key in ledger:
            ledger[key] = rescale_chapter_optional(
                ledger[key], from_total, to_total, end_of_book=True
            )

    for section in ("red_herrings", "major_reveals", "clues"):
        items = ledger.get(section) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in (
                "planted_chapter",
                "plant_chapter",
                "debunked_chapter",
                "reveal_chapter",
                "payoff_chapter",
            ):
                if field in item:
                    end = field in ("reveal_chapter", "payoff_chapter", "debunked_chapter")
                    item[field] = rescale_chapter_optional(
                        item[field], from_total, to_total, end_of_book=end
                    )
    return ledger


def rescale_threads(data: dict[str, Any], from_total: int, to_total: int) -> dict[str, Any]:
    data = deepcopy(data)
    for thread in data.get("threads") or []:
        if not isinstance(thread, dict):
            continue
        for field in ("opened_chapter", "must_close_by", "must_payoff_by"):
            if field not in thread:
                continue
            end = field in ("must_close_by", "must_payoff_by")
            thread[field] = rescale_chapter_optional(
                thread[field], from_total, to_total, end_of_book=end
            )
        for field in (
            "note",
            "book1_resolution",
            "book2_promise",
            "book1_payoff",
            "name",
        ):
            if isinstance(thread.get(field), str):
                thread[field] = rescale_text_chapters(thread[field], from_total, to_total)
    if isinstance(data.get("description"), str):
        data["description"] = rescale_text_chapters(data["description"], from_total, to_total)
    return data


def normalize_narrative_pass(
    pass_name: str, data: dict[str, Any], total: int, book: int = 1
) -> dict[str, Any]:
    """Post-process develop-narrative output — clamp/derive all chapter refs from N."""
    if not isinstance(data, dict):
        return data
    total = max(3, int(total))
    extent = infer_narrative_extent_from_data(data)
    from_total = max(extent, total)

    if pass_name == "book_arc":
        return patch_book_arc(data, total, book)
    if pass_name == "knowledge_matrix":
        return rescale_knowledge_matrix(data, from_total, total)
    if pass_name == "mystery_ledger":
        return rescale_mystery_ledger(data, from_total, total)
    if pass_name == "threads":
        return rescale_threads(data, from_total, total)
    return data


def infer_narrative_extent_from_data(data: Any) -> int:
    found: set[int] = set()
    _collect_chapter_numbers(data, found)
    return max(found) if found else 0


def rescale_narrative_dir(
    ws: Path,
    to_total: int,
    *,
    from_total: int | None = None,
    book: int = 1,
) -> list[str]:
    """Rescale narrative JSON chapter refs when operator changes chapter count.

    Scope is ONLY ``bible/narrative/*.json``. Never rewrite pipeline prose,
    catalog chapters, or spot_check bodies.
    """
    nd = ws / "bible" / "narrative"
    if not nd.exists():
        return []

    to_total = max(3, int(to_total))
    if from_total is None or from_total <= 0:
        from_total = max(infer_narrative_extent(ws), to_total)
    if from_total == to_total:
        from_total = infer_narrative_extent(ws) or to_total
    if from_total < to_total:
        from_total = max(from_total, to_total)

    updated: list[str] = []
    handlers = {
        "book_arc.json": lambda d: patch_book_arc(d, to_total, book),
        "knowledge_matrix.json": lambda d: rescale_knowledge_matrix(d, from_total, to_total),
        "mystery_ledger.json": lambda d: rescale_mystery_ledger(d, from_total, to_total),
        "threads.json": lambda d: rescale_threads(d, from_total, to_total),
    }
    for fname, fn in handlers.items():
        path = nd / fname
        if not path.exists():
            continue
        if is_prose_path(path):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            new_data = fn(data)
            path.write_text(
                json.dumps(new_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            updated.append(f"bible/narrative/{fname}")
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
    return updated
