"""P2 harness helpers — golden digests, call budget, write lock, kill-point seals."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from factory.engine.lib.canon_artifacts import (
    artifact_path,
    is_sealed,
    make_seal,
    read_json,
    write_json,
)
from factory.engine.lib.canonical_ir import (
    compile_canonical_ir,
    ingest_concept_to_workspace,
    load_canonical_ir,
    load_yaml_concept,
    sha256_obj,
)
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts
from factory.engine.lib.plan_provenance import seal_chapter_plan

# ---- Call / LLM budget counters (process-local; tests reset) ----

_BUDGET_LOCK = threading.Lock()
_BUDGET: dict[str, int] = {
    "literary_qc_calls": 0,
    "fixer_calls": 0,
    "settlement_llm_calls": 0,
    "settlement_deterministic_calls": 0,
    "writer_calls": 0,
}


def reset_call_budget() -> None:
    with _BUDGET_LOCK:
        for k in list(_BUDGET):
            _BUDGET[k] = 0


def record_call(kind: str, n: int = 1) -> None:
    with _BUDGET_LOCK:
        _BUDGET[kind] = int(_BUDGET.get(kind) or 0) + n


def get_call_budget() -> dict[str, int]:
    with _BUDGET_LOCK:
        return dict(_BUDGET)


def assert_canon_fail_budget_zero() -> None:
    """P0/P1 invariant: canon fail path must not invoke literary/fixer/settlement LLM."""
    b = get_call_budget()
    bad = {
        k: b[k]
        for k in ("literary_qc_calls", "fixer_calls", "settlement_llm_calls")
        if b.get(k)
    }
    if bad:
        raise AssertionError(f"canon-fail budget violated: {bad}")


# ---- Per-book write lock ----

_LOCK_DIR_NAME = ".canon_write_locks"


@contextmanager
def book_write_lock(ws: Path, book: int = 1, *, timeout_s: float = 30.0) -> Iterator[Path]:
    """Exclusive local lock for continuity writes (not parallel-by-default)."""
    lock_root = ws / _LOCK_DIR_NAME
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"book_{int(book):02d}.lock"
    start = time.time()
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} t={time.time()}\n".encode("utf-8"))
            break
        except FileExistsError:
            if time.time() - start > timeout_s:
                raise TimeoutError(f"book write lock timeout: {lock_path}")
            time.sleep(0.05)
    try:
        yield lock_path
    finally:
        try:
            if fd is not None:
                os.close(fd)
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


# ---- Kill-point / incomplete seal ----

def begin_seal_journal(ws: Path, book: int, chapter: int, step: str) -> Path:
    """Mark an in-progress seal so crash mid-seal cannot look READY."""
    path = artifact_path(ws, book, chapter, "seal_journal.json")
    write_json(
        path,
        {
            "status": "in_progress",
            "step": step,
            "chapter": chapter,
            "started_at": time.time(),
        },
    )
    return path


def complete_seal_journal(ws: Path, book: int, chapter: int) -> None:
    path = artifact_path(ws, book, chapter, "seal_journal.json")
    write_json(
        path,
        {
            "status": "complete",
            "chapter": chapter,
            "finished_at": time.time(),
        },
    )


def assert_no_incomplete_seal_promoted(ws: Path, book: int, chapter: int) -> None:
    """READY/promote must not proceed while seal_journal is in_progress."""
    journal = read_json(artifact_path(ws, book, chapter, "seal_journal.json"))
    if journal and str(journal.get("status") or "") == "in_progress":
        raise RuntimeError(
            f"ch{chapter}: incomplete seal journal — refuse READY/promote "
            f"(step={journal.get('step')})"
        )
    # Also refuse promote if plan/contract claim sealed but journal missing after begin
    # (caller responsibility). Here we only block explicit in_progress.


def seal_incomplete_cannot_be_ready(approval: dict[str, Any] | None) -> bool:
    """True when artifact is safe to treat as sealed for READY."""
    return is_sealed(approval)


# ---- Golden helpers ----

def concept_to_workspace(ws: Path, concept: dict[str, Any] | Path) -> dict[str, Any]:
    """Ingest with stable source_path so golden digests are content-addressed."""
    import yaml

    ws.mkdir(parents=True, exist_ok=True)
    if isinstance(concept, Path):
        raw = concept.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        (ws / "concept.yaml").write_bytes(raw)
        concept_obj, _ = load_yaml_concept(ws / "concept.yaml")
    else:
        raw = yaml.safe_dump(concept, allow_unicode=True, sort_keys=False).encode("utf-8")
        raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        (ws / "concept.yaml").write_bytes(raw)
        concept_obj = concept
    # Stable path for digest — do not embed disposable workspace paths.
    ir = compile_canonical_ir(
        concept_obj, source_bytes=raw, source_path="concept.yaml"
    )
    from factory.engine.lib.canonical_ir import ir_paths

    paths = ir_paths(ws)
    paths["canonical_ir"].parent.mkdir(parents=True, exist_ok=True)
    paths["source_concept"].parent.mkdir(parents=True, exist_ok=True)
    paths["source_concept"].write_bytes(raw)
    paths["canonical_ir"].write_text(
        json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ir



def seal_minimal_chapter(
    ws: Path,
    ir: dict[str, Any],
    chapter: int,
    plan: dict[str, Any],
) -> dict[str, Any]:
    with book_write_lock(ws, 1):
        begin_seal_journal(ws, 1, chapter, "plan")
        sealed = seal_chapter_plan(ws, 1, plan, ir=ir)
        if not sealed.get("sealed"):
            raise RuntimeError(f"seal failed ch{chapter}: {sealed}")
        begin_seal_journal(ws, 1, chapter, "contract")
        built = build_and_seal_chapter_artifacts(
            ws, 1, chapter, sealed["repaired_plan"], ir=ir
        )
        complete_seal_journal(ws, 1, chapter)
        record_call("settlement_deterministic_calls", 0)  # compile path only
        return {
            "sealed": sealed,
            "contract_digest": built["contract"].get("contract_digest"),
            "packet_digest": built["packet"].get("packet_digest"),
            "ir_digest": ir.get("ir_digest"),
            "contract": built["contract"],
            "packet": built["packet"],
        }


def golden_snapshot_for_title(
    *,
    title_id: str,
    ir: dict[str, Any],
    chapter_digests: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "title_id": title_id,
        "ir_digest": ir.get("ir_digest"),
        "importer_schema_version": ir.get("schema_version"),
        "chapters": chapter_digests,
    }


def compare_golden(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    for key in ("ir_digest", "importer_schema_version"):
        if expected.get(key) != actual.get(key):
            diffs.append(f"{key}: expected={expected.get(key)} actual={actual.get(key)}")
    exp_ch = expected.get("chapters") or {}
    act_ch = actual.get("chapters") or {}
    for ch, exp_row in exp_ch.items():
        act_row = act_ch.get(ch) or {}
        for field in ("contract_digest", "packet_digest"):
            if (exp_row or {}).get(field) != (act_row or {}).get(field):
                diffs.append(
                    f"ch{ch}.{field}: expected={(exp_row or {}).get(field)} "
                    f"actual={(act_row or {}).get(field)}"
                )
    return diffs
