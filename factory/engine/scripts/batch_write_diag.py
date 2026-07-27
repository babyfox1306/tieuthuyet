"""Batch-write chapters in skip-on-error mode with fault attribution.

Runs the real write pipeline (writer -> machine QC -> QC model -> promote) for a
chapter range. On ANY failure it records the outcome and CONTINUES to the next
chapter ("sai bo qua"), so a full-book run reveals every failure at once and
attributes each to a layer: WRITER (AI), QC (AI), ENGINE (code/machine), or
PROMPT/PLAN (locked-chain fidelity).

Usage:
  python factory/engine/scripts/batch_write_diag.py --workspace the-ninth-bell \
      --book 1 --from 1 --to 10 [--auto] [--force] [--fresh]
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.catalog import safe_print
from factory.engine.lib.machine_qc import classify_machine_issues
from factory.engine.paths import chapter_pipeline_path, load_config, workspace_dir
from factory.engine.run_factory import (
    _clear_chapter_pipeline,
    issues_path,
    load_json,
    qc_report_path,
    write_one_chapter,
)


def _read_json(path: Path) -> dict:
    try:
        return load_json(path)
    except Exception:
        return {}


def attribute_fault(ws: Path, book: int, ch: int, status: str, error: str | None) -> dict:
    """Map a chapter outcome to the responsible layer + evidence."""
    if error is not None:
        return {
            "fault": "ENGINE",
            "detail": "Uncaught exception in pipeline (code/machine bug).",
            "evidence": error.splitlines()[-1] if error else "",
        }
    if status == "ready":
        return {"fault": "-", "detail": "Passed writer + machine QC + QC model.", "evidence": ""}
    if status == "skipped":
        return {"fault": "-", "detail": "Already ready; not rewritten.", "evidence": ""}

    if status == "needs_fix":
        issues = _read_json(issues_path(ws, book, "needs_fix", ch))
        cls = issues.get("classification") or classify_machine_issues(issues)
        buckets = []
        if cls.get("has_length"):
            buckets.append("length")
        if cls.get("has_format"):
            buckets.append("format/markdown")
        return {
            "fault": "WRITER",
            "detail": "Writer output failed machine format/length after retries: "
            + (", ".join(buckets) or "format"),
            "evidence": "; ".join(str(k) for k in issues if k not in ("classification", "retry_meta"))[:200],
        }

    if status == "needs_review":
        qc = _read_json(qc_report_path(ws, book, "needs_review", ch))
        source = qc.get("source")
        reasons = qc.get("fail_reasons") or []
        if source == "machine_content_cap":
            # Writer never satisfied locked canon (POV/name/bible) within retry cap.
            return {
                "fault": "WRITER/PROMPT",
                "detail": (
                    "Machine content check kept failing (POV / name drift / bible / boundary). "
                    "If reasons look wrong, prompt/plan fidelity is the cause; else writer AI."
                ),
                "evidence": "; ".join(str(r) for r in reasons)[:200]
                or str(qc.get("classification", ""))[:200],
            }
        # QC model verdict FAIL
        return {
            "fault": "QC",
            "detail": "QC model returned FAIL (may be genuine or QC false-positive; inspect reasons).",
            "evidence": "; ".join(str(r) for r in reasons)[:200],
        }

    if status == "blocked":
        return {
            "fault": "ENGINE",
            "detail": "Write gate blocked (sequential chain gap).",
            "evidence": "",
        }
    return {"fault": "?", "detail": f"Unknown status {status}", "evidence": ""}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="the-ninth-bell")
    ap.add_argument("--book", type=int, default=1)
    ap.add_argument("--from", dest="from_ch", type=int, default=1)
    ap.add_argument("--to", dest="to_ch", type=int, default=10)
    ap.add_argument("--auto", action="store_true", help="writer_auto_max_retries for length/content")
    ap.add_argument("--force", action="store_true", help="bypass write gate (default on for diag)")
    ap.add_argument("--fresh", action="store_true", help="clear each chapter pipeline before writing")
    args = ap.parse_args()

    cfg = load_config()
    ws = workspace_dir(args.workspace)
    force = True if args.force else True  # diag always bypasses gate; keeps going on failure

    results: list[dict] = []
    counts: dict[str, int] = {}

    safe_print(
        f"=== BATCH WRITE (skip-on-error) ws={args.workspace} book={args.book} "
        f"ch {args.from_ch}..{args.to_ch} auto={args.auto} fresh={args.fresh} ==="
    )

    for ch in range(args.from_ch, args.to_ch + 1):
        if args.fresh:
            _clear_chapter_pipeline(ws, args.book, ch)
            ready = chapter_pipeline_path(ws, args.book, "ready", ch)
            if ready.exists():
                ready.unlink()
        error_text: str | None = None
        status = "error"
        try:
            _, status = write_one_chapter(
                ws, args.book, ch, cfg, args.workspace, force=force, auto=args.auto
            )
        except Exception:
            error_text = traceback.format_exc()
            safe_print(f"  ch_{ch:03d} ENGINE_ERROR — {error_text.splitlines()[-1]}")

        fault = attribute_fault(ws, args.book, ch, status, error_text)
        counts[status] = counts.get(status, 0) + 1
        results.append(
            {
                "chapter": ch,
                "status": status,
                "fault": fault["fault"],
                "detail": fault["detail"],
                "evidence": fault["evidence"],
                "error": (error_text.splitlines()[-1] if error_text else None),
            }
        )

    safe_print("\n================ DIAGNOSIS TABLE ================")
    safe_print(f"{'CH':>3} | {'STATUS':<13} | {'FAULT':<14} | EVIDENCE")
    safe_print("-" * 78)
    for r in results:
        safe_print(
            f"{r['chapter']:>3} | {r['status']:<13} | {r['fault']:<14} | {r['evidence'][:60]}"
        )
    safe_print("-" * 78)
    safe_print(f"counts: {counts}")

    # Fault rollup
    fault_counts: dict[str, int] = {}
    for r in results:
        if r["fault"] not in ("-", "?"):
            fault_counts[r["fault"]] = fault_counts.get(r["fault"], 0) + 1
    safe_print(f"faults: {fault_counts or 'none'}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": args.workspace,
        "book": args.book,
        "range": [args.from_ch, args.to_ch],
        "auto": args.auto,
        "counts": counts,
        "fault_counts": fault_counts,
        "results": results,
    }
    out = ws / "books" / f"{args.book:02d}" / "batch_write_diag.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    safe_print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
