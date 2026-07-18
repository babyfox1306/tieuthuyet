"""Writer completeness — incomplete output must never look like success.

finish_reason=length → hard truncate (provider/cap).
Missing finish_reason → fall back to EG-01 (sentence must end cleanly).
"""

from __future__ import annotations

from typing import Any

from factory.engine.lib.export_gate import check_eg01_truncated


def extract_finish_reason(choice_or_meta: Any) -> str | None:
    """Normalize finish_reason from OpenAI choice or our call_meta dict."""
    if choice_or_meta is None:
        return None
    if isinstance(choice_or_meta, dict):
        fr = choice_or_meta.get("finish_reason")
        if fr is None and isinstance(choice_or_meta.get("choice"), dict):
            fr = choice_or_meta["choice"].get("finish_reason")
        return str(fr).strip().lower() if fr is not None else None
    fr = getattr(choice_or_meta, "finish_reason", None)
    return str(fr).strip().lower() if fr is not None else None


def writer_output_incomplete(
    text: str,
    *,
    finish_reason: str | None = None,
    chapter: int = 0,
) -> tuple[bool, str, str]:
    """Return (incomplete, code, detail).

    Codes:
      truncated_by_length — finish_reason == length (silent cap / token wall)
      truncated_eg01 — ending fails EG-01 (mid-sentence / unclosed quote / …)
    """
    fr = (finish_reason or "").strip().lower() or None
    if fr == "length":
        return (
            True,
            "truncated_by_length",
            "finish_reason=length — output hit token/body cap; incomplete chapter",
        )

    body = (text or "").strip()
    eg = check_eg01_truncated(body, chapter)
    if not eg.get("passed"):
        detail = str(eg.get("detail") or "invalid chapter ending")
        # When router omits finish_reason, EG-01 is the only signal.
        code = "truncated_eg01" if fr is None or fr == "stop" else "truncated_eg01"
        if fr is None:
            detail = f"no finish_reason from router; EG-01: {detail}"
        else:
            detail = f"finish_reason={fr}; EG-01: {detail}"
        return True, code, detail

    return False, "", ""


def continuation_suffix(
    *,
    code: str,
    detail: str,
    prior_tail: str,
    attempt: int,
) -> str:
    """Prompt patch: continue from cut-off without repeating."""
    tail = (prior_tail or "").strip()[-800:]
    return (
        f"\n\n[CONTINUATION — attempt {attempt} — {code}]\n"
        f"Previous draft was CUT OFF ({detail}).\n"
        "Continue from the exact cutoff. Do NOT restart the chapter. "
        "Do NOT repeat earlier paragraphs. Close any open dialogue/quotes. "
        "End on a complete sentence with terminal punctuation (. ! ? or closing quote).\n"
        "--- LAST LINES (continue after these) ---\n"
        f"{tail}\n"
        "--- END LAST LINES ---\n"
    )
