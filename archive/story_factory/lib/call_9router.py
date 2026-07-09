"""9router API wrapper with logging and retry."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

FACTORY_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = FACTORY_ROOT / "config.json"
LOG_PATH = FACTORY_ROOT / "factory_log.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_role(name: str) -> str:
    path = FACTORY_ROOT / "roles" / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def _append_log(entry: dict) -> None:
    logs: list = []
    if LOG_PATH.exists():
        logs = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    logs.append(entry)
    LOG_PATH.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")


def call_9router(
    role: str,
    user_content: str,
    *,
    system_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 8192,
) -> tuple[str, dict]:
    """Returns (content, log_entry)."""
    cfg = load_config()
    system = system_override or load_role(role)
    temp = temperature if temperature is not None else cfg.get("temperature", {}).get(role, 0.7)
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key", "local"))
    model = cfg["model"]
    retries = cfg.get("retry_max", 2)

    last_err: Exception | None = None
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
                "elapsed_sec": round(elapsed, 2),
                "usage": usage,
                "attempt": attempt + 1,
            }
            _append_log(entry)
            return content, entry
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"9router failed after {retries+1} attempts: {last_err}")


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text)
