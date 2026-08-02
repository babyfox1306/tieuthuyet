"""P1 prose settlement — feed verified character/prop updates to next chapter."""

from __future__ import annotations

from typing import Any

from factory.engine.lib.canon_artifacts import artifact_path, write_json
from factory.engine.lib.canonical_ir import sha256_obj


def build_settlement(
    *,
    chapter: int,
    canon_qc: dict[str, Any],
    intelligence: dict[str, Any] | None = None,
    prose_len: int = 0,
) -> dict[str, Any]:
    if canon_qc.get("status") != "pass":
        return {
            "status": "blocked",
            "chapter": chapter,
            "reason": "canon_qc_not_pass",
        }
    # Generic texture / ephemeral never enters verified state payload.
    expressed = []
    for c in canon_qc.get("claims") or []:
        if c.get("kind") in {"generic_texture", "ephemeral_texture"}:
            continue
        if c.get("enter_state") is False:
            continue
        expressed.append(
            {
                "claim": c.get("claim"),
                "kind": c.get("kind"),
                "span_type": c.get("span_type"),
            }
        )
    settlement = {
        "status": "sealed",
        "chapter": chapter,
        "events_realized": [],
        "facts_expressed": expressed,
        "new_claims": [],
        "character_updates": {
            "psychology_active": (intelligence or {}).get("psychology_active"),
            "villain_knowledge": (intelligence or {}).get("villain_knowledge"),
        },
        "prop_updates": (intelligence or {}).get("prop_state"),
        "honeytoken_state": (intelligence or {}).get("honeytoken_state"),
        "relationship_delta": (intelligence or {}).get("moves"),
        "prose_len": prose_len,
        "texture_excluded_from_state": len(
            canon_qc.get("texture_claims_excluded_from_state") or []
        ),
        "violations": [],
    }
    settlement["settlement_digest"] = sha256_obj(
        {k: v for k, v in settlement.items() if k != "settlement_digest"}
    )
    return settlement


def write_settlement(ws, book: int, chapter: int, settlement: dict[str, Any]) -> None:
    write_json(artifact_path(ws, book, chapter, "settlement.json"), settlement)
