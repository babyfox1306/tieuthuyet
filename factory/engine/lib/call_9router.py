"""LLM API wrapper — 9router OpenAI-compatible + model fallback."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from factory.engine.lib.language import render_role_template
from factory.engine.paths import ENGINE, load_config

LOG_PATH = ENGINE / "factory_log.json"
ROLES_DIR = ENGINE / "roles"


def load_role(name: str, *, direction: dict | None = None, cfg: dict | None = None) -> str:
    raw = (ROLES_DIR / f"{name}.txt").read_text(encoding="utf-8")
    if direction is None and cfg is None:
        return raw
    if cfg is None:
        cfg = load_config()
    return render_role_template(raw, direction, cfg)


def _append_log(entry: dict) -> None:
    logs: list = []
    if LOG_PATH.exists():
        logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    logs.append(entry)
    LOG_PATH.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_auto_model(model: str) -> bool:
    return model == "auto" or model.startswith("auto/")


def resolve_priority_chain(cfg: dict, role: str) -> list[str]:
    """Thứ tự model cho role.

    model_routing=flexible (mặc định): OmniRoute ``auto`` chọn provider theo quota/sức khỏe;
    ``model_preferences`` chỉ là dự phòng cuối khi mọi auto variant fail.

    model_routing=fixed: danh sách cứng trong model_priority_groups (hành vi cũ).
    """
    groups = cfg.get("model_priority_groups", {})
    by_role = cfg.get("model_priority_by_role", {})
    chain: list[str] = []

    ref = by_role.get(role)
    if isinstance(ref, list):
        chain = list(ref)
    elif isinstance(ref, str):
        if ref in groups:
            chain = list(groups[ref])
        else:
            chain = [ref]

    # Legacy fallback (config cũ)
    if not chain:
        legacy = cfg.get("model_by_role", {})
        primary = legacy.get(role) or cfg.get("model")
        if primary:
            chain.append(primary)
        chain.extend(cfg.get("model_fallback", []))

    avoid = set(cfg.get("avoid_models", []))
    role_avoid = cfg.get("avoid_models_by_role", {}).get(role, [])
    if isinstance(role_avoid, list):
        avoid.update(role_avoid)

    out: list[str] = []
    for m in chain:
        if m and m not in avoid and m not in out:
            out.append(m)

    mode = str(cfg.get("model_routing", "flexible")).lower()
    if mode == "flexible":
        prefs = cfg.get("model_preferences", [])
        if isinstance(prefs, list):
            for m in prefs:
                if m and m not in avoid and m not in out:
                    out.append(m)
    return out


def _models_to_try(cfg: dict, role: str) -> list[str]:
    return resolve_priority_chain(cfg, role)


def _should_try_next_model(exc: Exception) -> bool:
    """Quota / rate / provider down / wrong gateway model name → model kế."""
    s = str(exc).lower()
    if any(code in s for code in ("400", "402", "403", "404", "413", "429", "503")):
        return True
    keys = (
        "limit",
        "quota",
        "rate",
        "exceeded",
        "model_not_supported",
        "model_not_found",
        "not supported",
        "not found",
        "no active credentials",
        "max_prompt_tokens",
        "too large",
        "unavailable",
        "high demand",
        "tokens per minute",
    )
    return any(k in s for k in keys)


def _is_quota_error(exc: Exception) -> bool:
    return _should_try_next_model(exc)


def _format_gateway_error(exc: Exception | None, *, base_url: str, models: list[str]) -> str:
    """Humanize OmniRoute/9router failures (esp. HTML 404 dashboard pages)."""
    raw = str(exc or "unknown error")
    low = raw.lower()
    if "<!doctype html" in low or "page not found" in low or "skip to content" in low:
        return (
            f"OmniRoute gateway broken or chat route missing at {base_url} "
            f"(got HTML 404 instead of JSON). "
            f"Tried models {models}. "
            f"Fix: open {base_url.rstrip('/v1').rstrip('/')}/ → login → add provider "
            f"credentials → create API key → put key in config.json api_key → "
            f"restart OmniRoute (start omni.bat) → run probe-models. "
            f"Also check /v1/models is non-empty."
        )
    if len(raw) > 400:
        return raw[:400] + "…"
    return raw


def list_models(base_url: str | None = None, api_key: str | None = None) -> list[str]:
    cfg = load_config()
    client = OpenAI(
        base_url=base_url or cfg["base_url"],
        api_key=api_key or cfg.get("api_key", "local"),
    )
    return [m.id for m in client.models.list().data]


def probe_model(model: str, *, base_url: str | None = None, api_key: str | None = None) -> tuple[bool, str]:
    cfg = load_config()
    client = OpenAI(
        base_url=base_url or cfg["base_url"],
        api_key=api_key or cfg.get("api_key", "local"),
        timeout=60,
    )
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Tra loi dung 1 tu: OK"}],
            max_tokens=8,
            temperature=0,
        )
        text = (r.choices[0].message.content or "").strip()
        return True, text or "(empty)"
    except Exception as exc:
        return False, str(exc)[:200]


def call_9router(
    role: str,
    user_content: str,
    *,
    direction: dict | None = None,
    system_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    """Call LLM via OmniRoute/9router; walk role chain on quota/rate/provider errors."""
    cfg = load_config()
    system = system_override or load_role(role, direction=direction, cfg=cfg)
    temp = temperature if temperature is not None else cfg.get("temperature", {}).get(role, 0.7)
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key", "local"))
    retries = cfg.get("retry_max", 2)
    models = _models_to_try(cfg, role)

    last_err: Exception | None = None
    for model in models:
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temp,
                    max_tokens=max_tokens,
                )
                content = resp.choices[0].message.content or ""
                content = re.sub(
                    r"<think>.*?</think>",
                    "",
                    content,
                    flags=re.DOTALL | re.IGNORECASE,
                ).strip()
                elapsed = time.time() - t0
                usage = {}
                if resp.usage:
                    usage = {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                        "total_tokens": resp.usage.total_tokens,
                    }
                finish_reason = None
                try:
                    finish_reason = resp.choices[0].finish_reason
                except (AttributeError, IndexError, TypeError):
                    finish_reason = None
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "role": role,
                    "model": model,
                    "elapsed_sec": round(elapsed, 2),
                    "usage": usage,
                    "attempt": attempt + 1,
                    "finish_reason": finish_reason,
                }
                _append_log(entry)
                return content, entry
            except Exception as exc:
                last_err = exc
                if _should_try_next_model(exc):
                    break  # next model in priority chain
                time.sleep(2 * (attempt + 1))
    hint = _format_gateway_error(last_err, base_url=cfg["base_url"], models=models)
    raise RuntimeError(f"All models failed ({models}): {hint}")


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse LLM JSON object — strip fences, trailing commas, then json-repair fallback.

    Always returns a dict. Non-object JSON (string/list/number) raises JSONDecodeError
    so callers never hit ``'str' object has no attribute 'get'``.
    """
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    candidates: list[str] = []
    if start >= 0 and end > start:
        raw = text[start : end + 1]
        raw = re.sub(r",\s*}", "}", raw)
        raw = re.sub(r",\s*]", "]", raw)
        candidates.append(raw)
    candidates.append(text)

    last_err: json.JSONDecodeError | None = None

    def _load_object(raw: str) -> dict[str, Any] | None:
        nonlocal last_err
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_err = exc
            return None
        if isinstance(data, dict):
            return data
        last_err = json.JSONDecodeError(
            f"Expected JSON object, got {type(data).__name__}",
            raw,
            0,
        )
        return None

    for raw in candidates:
        data = _load_object(raw)
        if data is not None:
            return data

    try:
        import json_repair

        for raw in candidates:
            try:
                fixed = json_repair.repair_json(raw)
                if isinstance(fixed, dict):
                    return fixed
                if isinstance(fixed, str):
                    data = _load_object(fixed)
                    if data is not None:
                        return data
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    except ImportError:
        pass

    if last_err is not None:
        raise last_err
    raise json.JSONDecodeError("Expected JSON object", text, 0)
