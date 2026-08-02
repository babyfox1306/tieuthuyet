# P2 Call / Token Budget

Branch: `experiment/ce-canon-provenance`.

## Targets

| Phase | Budget rule |
|-------|-------------|
| P0 fail-closed | ≈ +0..1 LLM vs pre-canon baseline on the **fail** path (usually **0** literary / Fixer / settlement LLM). |
| P1 | No large audit-LLM loops. Memory/Custody/Belief/Strategy are deterministic validators. |
| P2 | Regress above documented counters → CI red via `verify_p2_ci.py`. |

## Counters (`factory.engine.lib.p2_harness`)

```text
literary_qc_calls
fixer_calls
settlement_llm_calls
settlement_deterministic_calls
writer_calls
```

### Canon-fail path (invariant)

When `canon_qc.status != pass`:

- `should_skip_literary_fixer` → True
- `literary_qc_calls` / `fixer_calls` / `settlement_llm_calls` must remain **0**
- Enforced by `assert_canon_fail_budget_zero()` in `run_factory` before NEEDS_FIX return

### Canon-pass path

- Settlement is **deterministic** by default (`settlement_deterministic_calls += 1`)
- LLM settlement only if explicitly configured / violation path (not the default)

## Kill-point / crash safety

- `begin_seal_journal` / `complete_seal_journal` under chapter artifacts
- `assert_no_incomplete_seal_promoted` refuses READY/promote while `status=in_progress`
- Incomplete seals must not look READY

## Per-book write lock

- `book_write_lock(ws, book)` — exclusive local file lock under `.canon_write_locks/`
- Prepares parallel books; **parallel write is not default**

## CI

`python factory/engine/scripts/verify_p2_ci.py` asserts golden + mutation + corpus + budget cases.
