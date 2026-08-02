# Decisions

## P1 Canon Intelligence clamp scope

Commit audited: see `factory/workspaces/_canon_p1_overall_verify/verify_report.json`.
Branch: `experiment/ce-canon-provenance`.

### Memory

- `knows` evaluated by `evaluate_knowledge_against_pov_clocks` (`prose_settlement.py`).
- Authority clock: **`pov_knows_chapter` only** (never `reader_reveal_chapter`).
- Missing POV clock → `unresolved_clock` BLOCK.
- Clamp at settlement derive **and** `apply_settlement_to_intelligence`.
- Continuity channels re-clamped: events / prior_realized / open_pressure.
- Writer packet scrubs locked claims; opaque `hidden_future_reveal_count` only.
- **Status: complete.**

### Belief

- `evaluate_belief_provenance`: requires provenance (`observation` | `psychology` | `settlement` | `inference` | `canonical_ir`) **or** reveal-match after POV clock.
- Missing provenance → `omitted` (fail-closed).
- Hidden true fact as misbelief before POV clock → `clamped` (same POV-clock path).
- Psychology `cognitive_dissonance` → allowed with `provenance=psychology`.
- **Status: complete.**

### Custody

- `evaluate_prop_holder_claim` / `clamp_prop_updates_to_schedule` against `physical_owner_by_chapter` + `custody_chain` / `chapter_map.prop_actions`.
- Wrong holder → clamp to IR schedule.
- Disallowed action (verb/object mismatch vs allowed_actions) → clamp.
- Poisoned settlement `prose_*` holders re-clamped on apply.
- Verified chain transfer (e.g. P1→Adrian at ch12) → allowed and carries.
- **Status: complete.**

### Strategy

- `validate_move_fact_refs(ir, chapter)` semantic STOP reasons:
  - `move_missing_fact_refs`
  - `move_irrelevant_fact_refs`
  - `move_wrong_actor`
  - `move_future_fact_ref`
  - `move_prop_action_not_allowed` / `move_wrong_prop_actor`
  - `move_forbidden_event`
- Wired into `compile_chapter_contract`.
- Lexical resolve still used to *propose* refs; seal requires semantic support.
- **Status: complete.**

### Verdict

- **P1 overall complete** when Memory + Custody + Belief + Strategy all runtime-verified.
- Evidence: `factory/workspaces/_canon_p1_overall_verify/verify_report.json`
- Memory-only evidence retained under `_canon_p1_memory_clamp_verify/`.
