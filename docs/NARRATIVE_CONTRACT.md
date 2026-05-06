# Layer 1 Narrative Assessment Contract

**PR-CONTRACT-v0** establishes the contract between Layer 1 (narrative
gap detection) and Layer 2 (sizing / timing / exit). spec stack §3.1 in
code form.

## Why this contract exists

Without a code-level contract, the next sprint of PRs (PR-NAVER /
PR-ASSEMBLY / PR-LEARN / PR-NESTED / PR-CANONICAL) would each invent
ad-hoc dicts for "the thing Layer 1 hands to Layer 2." That's spec
drift, and we'd pay for it later by retrofitting a contract over
divergent shapes.

This PR pins down five dataclasses, four DB tables, and the
serialization round-trip — and crucially, it wires the
`actor_decision_journal` hook (direction.md §5 non-negotiable) and
`prediction` logging (§6 hindsight-bias guard) so the audit trail can
never silently disappear.

## Five dataclasses

See `core/narrative.py` for definitions.

| dataclass | role |
|---|---|
| `MarketNarrativeState` | current market frame + sources contribution |
| `RealityGap` | observed gap between narrative and reality |
| `FutureNarrativeGap` | predicted narrative shift catalyzed by an event |
| `Target` | actionable opportunity unit, hands to Layer 2 |
| `NarrativeAssessment` | the bundle Layer 1 produces per window |

## Forward-compatibility

We expect each downstream PR to add fields *without changing the
schema*. The shapes that absorb future fields:

- **`MarketNarrativeState.sources`** — `dict[actor_id, dict]`. The
  inner dict can grow. Today's keys: `contribution`, `authority_type`,
  `channel`, `document_count`. PR-YOUTUBE will add `subscriber_count`,
  PR-NESTED time-varying tracking will add `dormant_power_score`.
- **`RealityGap.gap_type`** — `Literal['quantitative','qualitative',
  'cross_source','leading_follower']`. The latter two are reserved for
  PR4-CANONICAL and PR-LEARN respectively.
- **`Target.actor_decision_likelihood`** / **`evidence_weights`** —
  both `dict[actor_id, float]`. PR-LEARN's learned `power_share` maps
  directly into `evidence_weights`. PR-NESTED's nested actor IDs map
  into `actor_decision_likelihood` without schema change.
- **`NarrativeAssessment.methodology_version`** — string tag; we evolve
  through `'v0_minimal_synthesizer'` → `'v1_llm_extraction'` (PR5) →
  `'v2_nested_learned'` (PR-NESTED + PR-LEARN).

The DB stores nested JSON in `*_json` columns, so adding fields to the
inner dicts requires no schema migration.

## DB schema

Five tables (one is `actor_decision_journal`; the other four hold the
narrative contract):

```
assessments              — one row per Layer 1 cycle
assessment_targets       — Targets, FK assessment_id
reality_gap_observations — RealityGap + FutureNarrativeGap (is_future flag)
predictions              — logged at creation time, actual filled later
actor_decision_journal   — ★ direction.md §5 — every actor decision audited
```

17 indexes total. CHECK constraints on tier ranges, gap_type enum,
direction (-1/+1), confidence and severity (0~1).

## decision_journal hook — why it matters

`core/world.py:World.tick()` now calls
`db.insert_actor_decision_journal_entry(...)` for every emitted decision
event. Before this PR, the existing `decision_journal` table was unused
— no call site, despite an `insert` helper sitting in
`persistence/core_io.py:204`. That's the kind of drift the 5/5
evaluation flagged: a critical primitive that the codebase agreed to
maintain on paper, but didn't actually exercise.

We split the concerns: the legacy `decision_journal` table stays as the
trade-hypothesis journal (Layer 2's domain), and a new
`actor_decision_journal` table holds the per-tick audit trail. This
keeps both intents intact and avoids breaking whatever Layer 2 code
arrives later that reads `decision_journal`.

The hook fires once per emitted event, not per actor, so an actor that
emits both a `market_action` and a `statement` in one tick produces two
journal rows. `affect_valence` and `affect_arousal` are computed from
the existing 5-D affect (`greed - fear` and `urgency` respectively) so
the journal stays compact while preserving the most important
dimensions for downstream calibration.

## Prediction logging — hindsight bias guard

`predictions.logged_at` is set on insert via
`db.insert_prediction(...)`. `actual_outcome_json` is `NULL` until the
horizon passes and someone calls `db.update_prediction_outcome(...)`.
This split is the §6 prerequisite for Stage C/D/E backtest
verification: without it, post-hoc justification of bad calls becomes
indistinguishable from forecasting skill.

`scripts/verify_contract.py` check 03 enforces this — any prediction
row with NULL `logged_at` fails the health check.

## Stage 7 minimal synthesizer

`runtime/synthesizer.py` produces a structurally valid
`NarrativeAssessment` from Schema v2 inputs:

- `documents.outlet` / `llm_priority` / `matched_actors_json` →
  `MarketNarrativeState.sources` and `anchors`
- `raw_events.primary_actor_id` / `event_subtype` /
  `impact_magnitude` → `Target.actor_decision_likelihood`
- `edges_dyn.strength` × `confidence` → `Target.evidence_weights`

The `frame`, `dominance`, `dispersion`, `confidence` fields are
placeholder values (`'[v0_minimal] placeholder...'` / `0.5` / `0.0`).
PR5's LLM extractor will fill them properly and bump
`methodology_version` to `'v1_llm_extraction'` without touching call
sites.

`World.tick()` calls the synthesizer every N ticks (default 4,
configurable via `World(synthesizer_every_n_ticks=...)` or
`None` to disable). Empty assessments (no targets, no gaps) are
skipped — we don't pollute the table with placeholder rows.

## Verification

```bash
# unit tests (11 new, plus 46 existing Schema v2 tests = 57 total)
python -m pytest tests/test_narrative.py -v

# health check on live DB
python -m scripts.verify_contract     # 8 / 8 expected

# Schema v2 baseline still intact
python -m scripts.verify_db           # 12 / 12 expected
```
