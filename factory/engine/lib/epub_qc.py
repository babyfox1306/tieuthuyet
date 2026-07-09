"""EPUB QC — W3C EPUBCheck as the technical ruler for export."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factory.engine.paths import load_config


def resolve_epubcheck_jar(cfg: dict | None = None) -> Path | None:
    """Find epubcheck.jar from config, env, or common install paths."""
    cfg = cfg or load_config()
    candidates: list[str] = []
    if cfg.get("epubcheck_jar"):
        candidates.append(str(cfg["epubcheck_jar"]))
    env = os.environ.get("EPUBCHECK_JAR", "").strip()
    if env:
        candidates.append(env)
    candidates.extend(
        [
            r"F:\phanmem\epubcheck-5.3.0\epubcheck.jar",
            r"F:\phanmem\epubcheck\epubcheck.jar",
            r"C:\tools\epubcheck\epubcheck.jar",
        ]
    )
    for raw in candidates:
        p = Path(raw).expanduser()
        if p.is_file():
            return p.resolve()
    return None


def parse_epubcheck_output(text: str) -> dict[str, Any]:
    """Parse EPUBCheck CLI stdout/stderr into structured counts + messages."""
    counts = {"fatals": 0, "errors": 0, "warnings": 0, "infos": 0}
    summary_match = re.search(
        r"(\d+)\s+fatals?\s*/\s*(\d+)\s+errors?\s*/\s*(\d+)\s+warnings?\s*/\s*(\d+)\s+infos?",
        text,
        re.IGNORECASE,
    )
    if summary_match:
        counts = {
            "fatals": int(summary_match.group(1)),
            "errors": int(summary_match.group(2)),
            "warnings": int(summary_match.group(3)),
            "infos": int(summary_match.group(4)),
        }

    messages: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(
            r"^(FATAL|ERROR|WARNING|INFO)\(([^)]+)\):\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if m:
            messages.append(
                {
                    "level": m.group(1).upper(),
                    "code": m.group(2),
                    "message": m.group(3).strip(),
                }
            )

    no_issues = "no errors or warnings detected" in text.lower()
    passed = counts["fatals"] == 0 and counts["errors"] == 0
    if no_issues:
        passed = True

    version_match = re.search(r"EPUB version ([\d.]+)", text, re.IGNORECASE)
    return {
        "passed": passed,
        "counts": counts,
        "messages": messages,
        "epub_version": version_match.group(1) if version_match else None,
        "raw_tail": "\n".join(text.splitlines()[-12:]),
    }


def run_epubcheck(
    epub_path: Path,
    *,
    jar_path: Path | None = None,
    cfg: dict | None = None,
    timeout_sec: int = 300,
) -> dict[str, Any]:
    """Run EPUBCheck on an EPUB file. Returns QC report dict."""
    cfg = cfg or load_config()
    epub_path = Path(epub_path).resolve()
    if not epub_path.is_file():
        return {
            "ok": False,
            "passed": False,
            "error": f"epub not found: {epub_path}",
            "epub_path": str(epub_path),
        }

    jar = jar_path or resolve_epubcheck_jar(cfg)
    if not jar:
        return {
            "ok": False,
            "passed": False,
            "error": "epubcheck.jar not found — set epubcheck_jar in config.json or EPUBCHECK_JAR env",
            "epub_path": str(epub_path),
        }

    java = shutil.which("java")
    if not java:
        return {
            "ok": False,
            "passed": False,
            "error": "java not found on PATH — EPUBCheck needs Java",
            "epub_path": str(epub_path),
            "epubcheck_jar": str(jar),
        }

    t0 = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [java, "-jar", str(jar), str(epub_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "passed": False,
            "error": f"epubcheck timeout after {timeout_sec}s",
            "epub_path": str(epub_path),
            "epubcheck_jar": str(jar),
        }

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    parsed = parse_epubcheck_output(combined)
    fail_on_warnings = bool(cfg.get("epub_qc_fail_on_warnings", False))
    passed = parsed["passed"] and (
        parsed["counts"]["warnings"] == 0 if fail_on_warnings else True
    )

    return {
        "ok": True,
        "passed": passed,
        "exit_code": proc.returncode,
        "epub_path": str(epub_path),
        "epubcheck_jar": str(jar),
        "checked_at": t0.isoformat(),
        "duration_sec": round((datetime.now(timezone.utc) - t0).total_seconds(), 2),
        **parsed,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def save_epub_qc_report(epub_path: Path, report: dict[str, Any]) -> Path:
    """Save QC report as JSON next to the EPUB."""
    out = Path(epub_path).with_suffix(".qc.json")
    payload = {k: v for k, v in report.items() if k not in ("stdout", "stderr")}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def qc_epub_file(epub_path: Path, *, cfg: dict | None = None, save: bool = True) -> dict[str, Any]:
    """Run EPUBCheck and optionally persist `.qc.json` beside the EPUB."""
    report = run_epubcheck(epub_path, cfg=cfg)
    if save and report.get("epub_path"):
        save_epub_qc_report(Path(report["epub_path"]), report)
    return report


def format_epub_qc_summary(report: dict[str, Any]) -> str:
    """One-line human summary for CLI / UI."""
    if not report.get("ok"):
        return f"EPUBCheck SKIP: {report.get('error', 'unknown')}"
    c = report.get("counts") or {}
    if report.get("passed"):
        return (
            f"EPUBCheck PASS — {c.get('warnings', 0)} warnings, "
            f"EPUB {report.get('epub_version') or '?'}"
        )
    return (
        f"EPUBCheck FAIL — {c.get('fatals', 0)} fatals, {c.get('errors', 0)} errors, "
        f"{c.get('warnings', 0)} warnings"
    )
