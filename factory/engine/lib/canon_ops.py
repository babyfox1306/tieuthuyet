"""P1 ops helpers — hash cache keys, descendant invalidation, error-layer classify."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.engine.lib.canonical_ir import load_canonical_ir, sha256_obj
from factory.engine.lib.canon_artifacts import (
    artifact_path,
    is_stale,
    mark_stale_descendants,
    read_json,
)


def cache_key_for_chapter(
    ir_digest: str,
    plan_hash: str,
    contract_digest: str,
) -> str:
    return sha256_obj(
        {
            "ir": ir_digest,
            "plan": plan_hash,
            "contract": contract_digest,
        }
    )


def invalidate_on_ir_change(ws: Path, book: int) -> list[str]:
    ir = load_canonical_ir(ws)
    if not ir:
        return []
    return mark_stale_descendants(
        ws,
        book,
        reason=f"ir_digest={ir.get('ir_digest')}",
    )


def classify_error_layer(message: str) -> str:
    text = (message or "").casefold()
    if "canonical_ir" in text or "ingest" in text or "concept" in text:
        return "importer_or_ce"
    if (
        "provenance" in text
        or "plan_" in text
        or "unverified" in text
        or "move_missing_fact_refs" in text
        or "fact_refs" in text
    ):
        return "planner"
    if "canon_qc" in text or "writer" in text or "prose" in text or "settlement" in text:
        return "writer"
    return "unknown"


def chapter_cache_record(
    ws: Path,
    book: int,
    chapter: int,
    *,
    ir_digest: str,
) -> dict[str, Any]:
    approval = read_json(artifact_path(ws, book, chapter, "plan.approval.json")) or {}
    contract = read_json(artifact_path(ws, book, chapter, "contract.json")) or {}
    plan_hash = str(
        approval.get("artifact_hash")
        or approval.get("plan_hash")
        or ""
    )
    contract_digest = str(contract.get("contract_digest") or "")
    key = cache_key_for_chapter(ir_digest, plan_hash, contract_digest)
    stale = bool(
        approval
        and is_stale(approval, ir_digest)
        or (
            read_json(artifact_path(ws, book, chapter, "contract.approval.json"))
            and is_stale(
                read_json(artifact_path(ws, book, chapter, "contract.approval.json"))
                or {},
                ir_digest,
            )
        )
    )
    return {
        "cache_key": key,
        "ir_digest": ir_digest,
        "plan_hash": plan_hash,
        "contract_digest": contract_digest,
        "stale": stale,
    }


def assert_chapter_not_stale(ws: Path, book: int, chapter: int, ir_digest: str) -> None:
    """Gate write/regen: refuse when sealed ancestors are stale vs IR."""
    rec = chapter_cache_record(ws, book, chapter, ir_digest=ir_digest)
    if rec.get("stale"):
        raise RuntimeError(
            f"ch{chapter}: stale vs IR — regenerate descendants only "
            f"(cache_key={rec.get('cache_key')})"
        )


def should_skip_literary_fixer(canon_qc: dict[str, Any] | None) -> bool:
    """Provenance / canon claim failures must not invoke Fixer LLM."""
    if not canon_qc:
        return False
    if canon_qc.get("status") == "fail":
        return True
    if canon_qc.get("violations"):
        return True
    return False


def record_canon_fail_skip() -> dict[str, int]:
    """P2: document that literary/fixer/settlement LLM stayed at 0 on canon fail."""
    from factory.engine.lib.p2_harness import assert_canon_fail_budget_zero, get_call_budget

    assert_canon_fail_budget_zero()
    return get_call_budget()
