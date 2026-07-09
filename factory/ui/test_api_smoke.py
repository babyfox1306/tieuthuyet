"""Smoke-test Factory UI API routes (no 9router calls)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8767"
WS = "ceo-contract"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw}
        return e.code, payload


def main() -> None:
    tests: list[tuple[str, str, str, dict | None]] = [
        ("GET", "/api/workspaces", "list workspaces", None),
        ("GET", f"/api/pipeline/{WS}", "pipeline status", None),
        ("GET", f"/api/chapters/{WS}", "chapter list", None),
        ("GET", f"/api/chapters/{WS}/1", "chapter 1 detail", None),
        ("POST", f"/api/pipeline/{WS}/step", "validate-narrative", {"action": "validate-narrative"}),
        ("POST", f"/api/pipeline/{WS}/step", "validate-bible", {"action": "validate-bible"}),
        ("POST", f"/api/chapters/{WS}/1/discard", "discard ch1", {}),
    ]

    print(f"Testing {BASE} workspace={WS}\n")
    failed = 0
    for method, path, label, body in tests:
        code, payload = call(method, path, body)
        ok = code < 400 or payload.get("gates") is not None
        status = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        extra = ""
        if "validate-bible" in label:
            extra = f" bible_ok={payload.get('ok')} errors={payload.get('errors', [])[:2]}"
        elif "validate-narrative" in label:
            extra = f" narr_ok={payload.get('ok')} errors={len(payload.get('errors') or [])}"
        elif path.endswith("/step"):
            extra = f" ok={payload.get('ok')} action={body.get('action') if body else ''}"
        print(f"[{status}] {code} {method} {path} — {label}{extra}")

    # approve-bible dry: only if validate passes
    code, vb = call("POST", f"/api/pipeline/{WS}/step", {"action": "validate-bible"})
    if vb.get("ok"):
        code2, ab = call("POST", f"/api/pipeline/{WS}/step", {"action": "approve-bible"})
        print(f"[{'OK' if code2 < 400 else 'FAIL'}] {code2} POST approve-bible ok={ab.get('ok')} bible_status={ab.get('gates', {}).get('bible', {}).get('status')}")
    else:
        print(f"[SKIP] approve-bible — validate failed: {vb.get('errors')}")
        failed += 1

    print(f"\nDone. failures={failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
