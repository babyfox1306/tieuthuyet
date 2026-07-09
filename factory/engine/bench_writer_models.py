#!/usr/bin/env python3
"""Benchmark Writer models — same ch1 prompt, score Vietnamese output."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from factory.engine.lib.call_9router import load_role, probe_model
from factory.engine.lib.machine_qc import machine_qc, word_count_vi
from factory.engine.lib.catalog import safe_print
from factory.engine.paths import load_config

CANDIDATES = [
    "gemini/gemini-2.0-flash-lite",
    "gemini/gemini-3-flash-preview",
    "gc/gemini-3-flash-preview",
    "gh/goldeneye-free-auto",
    "gh/gemini-3-flash-preview",
    "gh/gpt-4o-mini",
    "gh/claude-haiku-4.5",
    "groq/qwen/qwen3-32b",
    "groq/llama-3.3-70b-versatile",
    "kr/deepseek-3.2",
    "qw/qwen3-coder-flash",
    "gh/gpt-4o",  # baseline
]

OUT_DIR = ROOT / "factory" / "workspaces" / "ceo-contract" / "books" / "01" / "bench_models"


def score_vi(text: str, min_words: int = 1500) -> dict:
    issues = machine_qc(text, min_words=min_words)
    body = text.strip()
    lines = [ln for ln in body.splitlines() if ln.strip()]
    first3 = " ".join(lines[:4])[:400]
    opens_hook = bool(re.search(r"một tỷ|ký tên|tỷ đồng", first3, re.I))
    cjk = bool(issues.get("cjk_chars"))
    wc = word_count_vi(text)
    # crude fluency: penalize awkward patterns
    awkward = len(re.findall(r"\b(là là|được được|một một)\b", body, re.I))
    return {
        "word_count": wc,
        "issues": list(issues.keys()),
        "opens_hook": opens_hook,
        "cjk": cjk,
        "awkward": awkward,
        "score": wc
        + (200 if opens_hook else 0)
        + (-500 if cjk else 0)
        + (-300 if wc < 1500 else 0)
        + (-50 * awkward),
    }


def write_ch1(client: OpenAI, model: str, prompt: str, system: str, temp: float) -> tuple[str, dict]:
    t0 = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=temp,
        max_tokens=8192,
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = {}
    if resp.usage:
        usage = {
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    return text, {"elapsed": round(time.time() - t0, 1), **usage}


def main() -> None:
    cfg = load_config()
    prompt_path = ROOT / "factory/workspaces/ceo-contract/books/01/prompts/ch_001.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    system = load_role("writer")
    temp = cfg.get("temperature", {}).get("writer", 0.88)
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key", "local"), timeout=300)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    print("=== PROBE ===")
    alive: list[str] = []
    for m in CANDIDATES:
        ok, msg = probe_model(m)
        tag = "OK" if ok else "FAIL"
        safe_print(f"  {tag} {m}: {msg[:80]}")
        if ok:
            alive.append(m)

    print("\n=== BENCH ch1 ===")
    for model in alive:
        safe = model.replace("/", "_")
        out = OUT_DIR / f"{safe}.txt"
        print(f"  {model}...", flush=True)
        try:
            text, meta = write_ch1(client, model, prompt, system, temp)
            out.write_text(text, encoding="utf-8")
            sc = score_vi(text)
            row = {"model": model, **sc, **meta}
            results.append(row)
            safe_print(
                f"    wc={sc['word_count']} score={sc['score']} "
                f"hook={sc['opens_hook']} issues={sc['issues']} ({meta['elapsed']}s)"
            )
        except Exception as exc:
            safe_print(f"    FAIL: {str(exc)[:120]}")
            results.append({"model": model, "error": str(exc)[:200]})
        time.sleep(2)

    results.sort(key=lambda r: r.get("score", -9999), reverse=True)
    report = OUT_DIR / "report.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RANKING ===")
    for i, r in enumerate(results, 1):
        if "error" in r:
            print(f"{i}. {r['model']} — ERROR")
        else:
            print(
                f"{i}. {r['model']} — score={r['score']} wc={r['word_count']} "
                f"hook={r['opens_hook']} issues={r['issues']}"
            )
    if results and "model" in results[0] and "error" not in results[0]:
        print(f"\nWINNER: {results[0]['model']}")


if __name__ == "__main__":
    main()
