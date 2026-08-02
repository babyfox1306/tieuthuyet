# Decisions

## P0 / P1 / P2 Canon verdict

Branch: `experiment/ce-canon-provenance`.

```text
P0 enforcement: COMPLETE
P1 Memory: COMPLETE
P1 Custody: COMPLETE
P1 Belief: COMPLETE
P1 Strategy: COMPLETE
P1 overall: COMPLETE — by reproducible raw-evidence harness at commit 6e141f7+
P2 harness: COMPLETE — golden + mutation battery + corpus + budget + CI gate
```

### Baseline lock (do not reopen architecture)

```text
commit: 01bddb446e43a6dc54a47be1ac62b53e382dc82d
tag:    canon-p2-harness-complete
prove:  python factory/engine/scripts/verify_p2_ci.py
```

> **P2 COMPLETE only counts when the harness re-runs green** — not because a tag or prose report says so. Artifact: `factory/engine/tests/fixtures/canon_p2_ci/P2_CI_GATE.json` (+ `P2_CI_LAST_RUN.log`).

Next business step (not architecture): clean end-to-end book from a CE RELEASED title **not** used as Zero-Day fixture; human-read first EPUB.

Authoritative closeout:

> **P1 overall complete by reproducible raw-evidence harness at commit `6e141f7` (exporter/fixtures follow-up on same tag line). Independent artifact inspection remains optional, not a known blocker.**

> **P2 harness complete** when `verify_p2_ci.py` is green: golden digests (≥2 titles, dual-run identical), mutation battery expect-fail đúng reason/layer (`RAW_MUTATION_GATE.json`), infection + synthetic corpus, call/token budget docs + canon-fail counters = 0, kill-point seal + local write lock.

Caveat (release note):

> P1 does **not** guarantee the Writer produces clean prose on the first pass. It guarantees cognition, belief, custody, and strategy **must not enter packet/state** when they contradict Canonical IR. P2 does **not** open new intelligence — it proves the sealed stack stays stable.

Do not expand P1 further unless a raw artifact directly exposes a false PASS. Do not reopen P1 from P2 unless mutation battery shows a false PASS. Do not add architecture after this baseline — ship books.

---

## Final authority order

```text
Canonical IR
> clock / custody / belief / strategy validators
> verified settlement
> Outliner carries_to_next
> Writer proposal
```

---

## P1 Canon Intelligence clamp scope

### Memory

- `knows` via `evaluate_knowledge_against_pov_clocks` (`prose_settlement.py`).
- Authority clock: **`pov_knows_chapter` only** (never `reader_reveal_chapter`).
- Missing POV clock → `unresolved_clock` BLOCK.
- Clamp at settlement derive **and** `apply_settlement_to_intelligence`.
- Continuity channels re-clamped: events / prior_realized / open_pressure.
- Writer packet scrubs locked claims; opaque `hidden_future_reveal_count` only.
- **Status: COMPLETE.**

### Belief

- `evaluate_belief_provenance`: requires provenance (`observation` | `psychology` | `settlement` | `inference` | `canonical_ir`) **or** reveal-match after POV clock.
- Missing provenance → `omitted` (fail-closed).
- Hidden true fact as misbelief before POV clock → `clamped`.
- Psychology `cognitive_dissonance` → allowed with `provenance=psychology`.
- **Status: COMPLETE.**

### Custody

- `evaluate_prop_holder_claim` / `clamp_prop_updates_to_schedule` against `physical_owner_by_chapter` + `custody_chain` / `chapter_map.prop_actions`.
- Wrong holder → clamp to IR schedule.
- Disallowed action → clamp.
- Poisoned settlement `prose_*` holders re-clamped on apply.
- Verified chain transfer (e.g. P1→Adrian at ch12) → allowed and carries.
- **Status: COMPLETE.**

### Strategy

- `validate_move_fact_refs(ir, chapter)` semantic STOP:
  - `move_missing_fact_refs`
  - `move_irrelevant_fact_refs`
  - `move_wrong_actor`
  - `move_future_fact_ref`
  - `move_prop_action_not_allowed` / `move_wrong_prop_actor`
  - `move_forbidden_event`
- Wired into `compile_chapter_contract`.
- **Status: COMPLETE.**

### Evidence harness (P1)

- Exporter: `factory/engine/scripts/export_p1_raw_evidence.py`
- Gate: `factory/workspaces/_canon_p1_raw_evidence/RAW_EVIDENCE_GATE.json`
- Fixtures (regression): `factory/engine/tests/fixtures/canon_p1_raw_evidence/`
- Structure: positive + negative + poisoned + control + live packet diff + reproducible exporter.
- Memory-only prior evidence: `_canon_p1_memory_clamp_verify/`
- Overall summary prior: `_canon_p1_overall_verify/`

---

## P2 Harness (stability)

P2 hardens P0+P1 — **no** new SoT, **no** validator redesign unless false PASS.

| Slice | Entry |
|-------|--------|
| Golden | `verify_p2_golden.py` + `fixtures/canon_p2_golden/` |
| Mutation | `export_p2_mutation_evidence.py` + `RAW_MUTATION_GATE.json` |
| Corpus | `verify_p2_corpus.py` + infection + romance/mystery-lite |
| Budget | `factory/docs/P2_BUDGET.md` + `p2_harness` counters / kill-point / write lock |
| CI | `verify_p2_ci.py` → tag `canon-p2-harness-complete` |

Export still requires `canon_qc: pass` + sealed ancestors (P0 invariant).
