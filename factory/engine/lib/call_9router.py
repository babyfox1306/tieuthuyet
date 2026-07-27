"""LLM API wrapper — DeepSeek API (OpenAI-compatible) + optional external failover.

Primary: DeepSeek (``base_url`` / ``api_key`` in config.json) walking the role
model chain. All roles run non-thinking via
``extra_body={"thinking": {"type": "disabled"}}``.
Fallback: ``external_fallback`` provider(s) when primary is exhausted or down.

OmniRouter (localhost:20128) is disabled; restore via ``_omni_router_restore``
in config.json if needed.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from factory.engine.lib.language import render_role_template
from factory.engine.paths import ENGINE, load_config

LOG_PATH = ENGINE / "factory_log.json"
ROLES_DIR = ENGINE / "roles"
_DEEPSEEK_KEY_ENV = "DEEPSEEK_API_KEY"
_DOTENV_LOADED = False


def _load_dotenv(path=None) -> None:
    """Load KEY=VALUE lines from factory/engine/.env into os.environ (no overwrite).

    Pure-stdlib — avoids a python-dotenv dependency. Existing env vars win, so
    a real shell/OS env always takes precedence over the file.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED and path is None:
        return
    env_path = path or (ENGINE / ".env")
    try:
        raw = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        if path is None:
            _DOTENV_LOADED = True
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
    if path is None:
        _DOTENV_LOADED = True


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

    model_routing=fixed (mặc định DeepSeek): chỉ danh sách cứng trong
    model_priority_groups — không auto-select.

    model_routing=flexible (legacy Omni): cho phép ``model_preferences`` phụ.
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

    mode = str(cfg.get("model_routing", "fixed")).lower()
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
    if any(code in s for code in ("400", "402", "403", "404", "413", "429", "503", "502", "500")):
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
        "connection",
        "connect",
        "timeout",
        "timed out",
        "refused",
        "reset by peer",
        "temporarily",
        "overloaded",
        "capacity",
        "insufficient",
        "billing",
        "balance",
        "credits",
    )
    return any(k in s for k in keys)


def _is_quota_error(exc: Exception) -> bool:
    return _should_try_next_model(exc)


def _resolve_api_key(raw: str | None, *, env_name: str | None = None, default: str = "local") -> str:
    """Resolve api key from literal, ${ENV}, or named env var."""
    if env_name:
        from_env = (os.environ.get(env_name) or "").strip()
        if from_env:
            return from_env
    text = (raw or "").strip()
    if text.startswith("${") and text.endswith("}"):
        var = text[2:-1].strip()
        return (os.environ.get(var) or "").strip() or default
    return text or default


def _primary_api_key(cfg: dict) -> str:
    """DeepSeek key: env DEEPSEEK_API_KEY (via OS or .env) first, config last.

    The key must NOT live in config.json — keep only a placeholder there.
    """
    _load_dotenv()
    return _resolve_api_key(
        cfg.get("api_key"),
        env_name=_DEEPSEEK_KEY_ENV,
        default="",
    )


def resolve_external_providers(cfg: dict) -> list[dict[str, Any]]:
    """Normalize ``external_fallback`` into enabled provider dicts.

    Accepted shapes::

        "external_fallback": {
          "enabled": true,
          "base_url": "https://api.openai.com/v1",
          "api_key": "...",                 # or leave empty + api_key_env
          "api_key_env": "FACTORY_EXTERNAL_API_KEY",
          "models": ["gpt-4o", "gpt-4.1"],
          "timeout": 120
        }

        "external_fallback": [ { ... }, { ... } ]   # multi-provider cascade
    """
    raw = cfg.get("external_fallback")
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        base_url = (item.get("base_url") or "").strip()
        models = item.get("models") or item.get("model")
        if isinstance(models, str):
            models = [models]
        if not isinstance(models, list):
            models = []
        models = [m for m in models if m]
        key = _resolve_api_key(
            item.get("api_key"),
            env_name=item.get("api_key_env") or "FACTORY_EXTERNAL_API_KEY",
            default="",
        )
        if not base_url or not models or not key:
            continue
        out.append(
            {
                "name": item.get("name") or "external",
                "base_url": base_url.rstrip("/"),
                "api_key": key,
                "models": models,
                "timeout": int(item.get("timeout") or 180),
            }
        )
    return out


def _normalize_openai_base_url(base_url: str) -> str:
    """DeepSeek OpenAI-compatible base → ``…/chat/completions`` via SDK.

    Accept ``https://api.deepseek.com`` or ``…/v1``; strip trailing slash only.
    Do not invent paths — OpenAI client appends ``/chat/completions``.
    """
    return (base_url or "").strip().rstrip("/")


def _format_gateway_error(exc: Exception | None, *, base_url: str, models: list[str]) -> str:
    """Humanize API gateway failures (HTML 404 / bad base URL)."""
    raw = str(exc or "unknown error")
    low = raw.lower()
    if "<!doctype html" in low or "page not found" in low or "skip to content" in low:
        return (
            f"API gateway broken or chat route missing at {base_url} "
            f"(got HTML 404 instead of JSON). "
            f"Tried models {models}. "
            f"Expected OpenAI-compatible chat at {base_url.rstrip('/')}/chat/completions "
            f"(DeepSeek: https://api.deepseek.com). "
            f"Check config.json base_url + api_key, then probe-models."
        )
    if len(raw) > 400:
        return raw[:400] + "…"
    return raw


def _strip_think(content: str) -> str:
    return re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()


def _message_text(message: Any) -> str:
    """Prefer ``content``; fall back to ``reasoning_content`` if content empty."""
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is None:
        extra = getattr(message, "model_extra", None) or {}
        if isinstance(extra, dict):
            reasoning = extra.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    return content if isinstance(content, str) else ""


# DeepSeek V4 defaults to thinking-on; OpenAI SDK needs extra_body for this field.
_DEEPSEEK_NON_THINKING = {"thinking": {"type": "disabled"}}


def list_models(base_url: str | None = None, api_key: str | None = None) -> list[str]:
    cfg = load_config()
    client = OpenAI(
        base_url=_normalize_openai_base_url(base_url or cfg["base_url"]),
        api_key=api_key or _primary_api_key(cfg),
    )
    return [m.id for m in client.models.list().data]


def probe_model(model: str, *, base_url: str | None = None, api_key: str | None = None) -> tuple[bool, str]:
    cfg = load_config()
    client = OpenAI(
        base_url=_normalize_openai_base_url(base_url or cfg["base_url"]),
        api_key=api_key or _primary_api_key(cfg),
        timeout=60,
    )
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Tra loi dung 1 tu: OK"}],
            max_tokens=64,
            temperature=0,
            extra_body=dict(_DEEPSEEK_NON_THINKING),
        )
        text = _strip_think(_message_text(r.choices[0].message))
        return True, text or "(empty)"
    except Exception as exc:
        return False, str(exc)[:200]


def _chat_once(
    client: OpenAI,
    *,
    model: str,
    system: str,
    user_content: str,
    temperature: float,
    max_tokens: int,
    role: str,
    provider: str,
    attempt: int,
) -> tuple[str, dict]:
    t0 = time.time()
    # Non-thinking for every role — DeepSeek V4 defaults thinking ON.
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=dict(_DEEPSEEK_NON_THINKING),
    )
    content = _strip_think(_message_text(resp.choices[0].message))
    elapsed = time.time() - t0
    usage = {}
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "model": model,
        "provider": provider,
        "elapsed_sec": round(elapsed, 2),
        "usage": usage,
        "attempt": attempt,
    }
    return content, entry


def _try_provider_models(
    client: OpenAI,
    models: list[str],
    *,
    system: str,
    user_content: str,
    temperature: float,
    max_tokens: int,
    role: str,
    provider: str,
    retries: int,
) -> tuple[tuple[str, dict] | None, Exception | None]:
    """Walk models; return ((content, log), None) on success, else (None, last_err)."""
    last_err: Exception | None = None
    for model in models:
        for attempt in range(retries + 1):
            try:
                return (
                    _chat_once(
                        client,
                        model=model,
                        system=system,
                        user_content=user_content,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        role=role,
                        provider=provider,
                        attempt=attempt + 1,
                    ),
                    None,
                )
            except Exception as exc:
                last_err = exc
                if _should_try_next_model(exc):
                    break  # next model
                time.sleep(2 * (attempt + 1))
    return None, last_err


def call_9router(
    role: str,
    user_content: str,
    *,
    direction: dict | None = None,
    system_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    """Call LLM: DeepSeek primary (non-thinking), then external_fallback if dry/down."""
    cfg = load_config()
    system = system_override or load_role(role, direction=direction, cfg=cfg)
    temp = temperature if temperature is not None else cfg.get("temperature", {}).get(role, 0.7)
    retries = cfg.get("retry_max", 2)
    models = _models_to_try(cfg, role)

    primary_base = _normalize_openai_base_url(cfg["base_url"])
    primary = OpenAI(
        base_url=primary_base,
        api_key=_primary_api_key(cfg),
    )
    hit, primary_err = _try_provider_models(
        primary,
        models,
        system=system,
        user_content=user_content,
        temperature=temp,
        max_tokens=max_tokens,
        role=role,
        provider="deepseek",
        retries=retries,
    )
    if hit is not None:
        content, entry = hit
        _append_log(entry)
        return content, entry

    externals = resolve_external_providers(cfg)
    external_errors: list[str] = []
    for ext in externals:
        client = OpenAI(
            base_url=_normalize_openai_base_url(ext["base_url"]),
            api_key=ext["api_key"],
            timeout=ext.get("timeout", 180),
        )
        hit, ext_err = _try_provider_models(
            client,
            list(ext["models"]),
            system=system,
            user_content=user_content,
            temperature=temp,
            max_tokens=max_tokens,
            role=role,
            provider=str(ext.get("name") or "external"),
            retries=retries,
        )
        if hit is not None:
            content, entry = hit
            entry["fallback_from"] = "deepseek"
            entry["primary_error"] = _format_gateway_error(
                primary_err, base_url=primary_base, models=models
            )[:240]
            _append_log(entry)
            return content, entry
        external_errors.append(
            f"{ext.get('name')}:{ext['models']} → "
            f"{_format_gateway_error(ext_err, base_url=ext['base_url'], models=ext['models'])}"
        )

    hint = _format_gateway_error(primary_err, base_url=primary_base, models=models)
    if externals:
        raise RuntimeError(
            f"All models failed — DeepSeek ({models}): {hint}; "
            f"external fallback also failed: {' | '.join(external_errors)}"
        )
    raise RuntimeError(
        f"All models failed ({models}): {hint}. "
        f"Tip: paste DeepSeek key into config.json api_key, or set external_fallback."
    )


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
