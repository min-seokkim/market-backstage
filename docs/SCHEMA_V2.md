# Schema v2 — NFKC + Hot fields + Tier system + Behavioural-economic entities

**PR-SCHEMA-V2** rebuilds the persistence layer to fix the
NFKC bug surfaced by PR-DASHBOARD-v0, denormalize identity hot
fields for index-driven joins, and add a substantive
political/economic tier system plus relationship-strength fields
on edges and impact-heterogeneity fields on events.

## Why v2

PR-DASHBOARD-v0 found that `WHERE hanja_name = '李在明'` returned
zero rows even though the person was clearly in the database.
Root cause: the NEC API ships hanja as **CJK Compatibility
Ideographs** (e.g. 李 = U+F9E1), while Python source files
default to **CJK Unified Ideographs** (U+674E). The two render
identically but compare unequal.

The dashboard worked around this with a query-time `nfkc()` SQL
function. v2 fixes the underlying problem at every persist
boundary, then keeps the dashboard's defensive normalization in
place as backstop.

While we were rebuilding the persistence layer, we also addressed:

- **Hot fields** — `actors_dyn.hanja_name`, `birthday`,
  `external_id` etc. were buried in `identity_json`, requiring
  full JSON scans for every cross-source lookup.
- **Tier system** — the abstract notion of "important politician"
  vs "fringe candidate" wasn't expressed; downstream signal
  models had no way to weight by importance.
- **Behavioural-economic fields** — relationships had no
  intensity, events had no per-actor heterogeneity. The same
  M&A announcement affects an acquirer differently from a
  minority shareholder, but the schema couldn't say so.

## Field map

### `actors_dyn` (existing + v2)

```
-- existing
id, name, category, role, activation, identity_json, sources_json,
schema_json, decision_variables_json, notes, status, trust_score,
proposal_source, proposed_by, proposed_at, promoted_at, promoted_by,
deprecated_at, rationale, type

-- v2 hot fields
hanja_name                    TEXT      NFKC-normalized at persist
birthday                      TEXT      YYYYMMDD
external_id                   TEXT      huboid / jurirno / mona_cd / naas_cd
external_id_type              TEXT      enum-checked

-- v2 tier system
political_tier                INTEGER   1~5 / NULL (CHECK)
economic_tier                 INTEGER   1~5 / NULL (CHECK)
peak_political_tier           INTEGER   min over history
peak_economic_tier            INTEGER
registered_as_candidate       INTEGER   0/1 (CHECK)
current_governance_position   TEXT
current_party_position        TEXT
current_party_name            TEXT
current_corp_position         TEXT
current_corp_group            TEXT
tier_history_json             TEXT      [{ts, political_tier, economic_tier, reason, source}, ...]
```

### `edges_dyn` (v2 additions)

```
election_id    TEXT       denormalized for fast NEC-edge filter
strength       REAL       0~1 relationship intensity (CHECK)
confidence     REAL       0~1 observer confidence (CHECK)
```

Strength meaning by edge type:
- `member_of_party`, `won_election`, `executive_of`, `subsidiary_of`,
  `owns`, `family_relation` — deterministic ties: **1.0**
- `shareholder_of` — **`ownership_pct / 100`** (e.g. 24.34% stake → 0.2434)
- `candidate_in` / `withdrew_from` / `invalidated` — 0.5 if abridged
  outcome, 1.0 otherwise
- LLM-extracted edges (future) — < 1.0 to express uncertainty

### `raw_events` (v2 additions)

```
primary_actor_id      TEXT     canonical actor mainly affected
event_subtype         TEXT     fine-grained kind (e.g. 'subsidiary_addition')
impact_magnitude      REAL     0~1 event-level intensity (CHECK)
actor_targets_json    TEXT     [{actor_id, magnitude, interpretation?}, ...]
```

Magnitudes are **seed estimates**, not derived from data — they
reflect how much the ingest layer believes a given event matters
relative to the worst-case (1.0). They're calibrated to the
following anchors:

| event              | impact_magnitude | rationale |
|--------------------|------------------|-----------|
| candidate_register | 0.3              | routine   |
| candidate_withdraw | 0.5              | meaningful |
| candidate_invalidated | 0.6           | partial crisis |
| candidate_deceased | 0.8              | full crisis |
| subsidiary_addition / removal | 0.4   | structural |
| subsidiary_postpone | 0.2             | administrative |

`actor_targets_json` spreads the impact: e.g. for `candidate_withdraw`
the primary actor gets the full hit, but the affected election and
party also receive smaller magnitudes (0.1–0.2) to drive downstream
correlation models.

### `documents` (v2 additions)

```
outlet               TEXT     '조선일보' / 'mof' / etc
llm_priority         INTEGER  1=hot, higher=lower
matched_actors_json  TEXT     canonical actor_ids found in body
signal_extracted     INTEGER  0/1 — LLM extractor visited
```

These prepare for PR-NAVER (Phase 1 LLM extraction) but don't
require any extractor to be running — they're filled by adapters
opportunistically.

## NFKC defense in depth

`persistence.core_io` exposes `nfkc()`, `nfkc_recursive()`, and
`has_compat_codepoint()`. Every persist helper
(`upsert_actor_dyn`, `upsert_edge`, `insert_raw_event`,
`upsert_alias`) NFKC-normalizes its string args and recursively
walks every JSON field before writing. Querying NFKC inside the
DB also works via the dashboard's registered custom function —
that path remains as backstop for any string the persist layer
hasn't seen yet.

## Tier system

See [TIER_SYSTEM.md](TIER_SYSTEM.md) for the substantive rules.

## Indexes

Schema v2 adds 15 new indexes covering the hot fields and tier
columns. All are partial (`WHERE col IS NOT NULL`) to keep them
small. The `idx_actors_dyn_hanja_birthday` composite is the key
one for cross-source identity resolution (PR4-PERSON).

## Migration path

This PR rebuilds the DB from scratch. The previous v1 database
is preserved at `data/world.db.bak.v1` for reference. Re-ingest
runs FTC + NEC both deterministic — actor/edge/alias counts
should match the previous baseline within RSS noise (±100
documents).

## Backwards-compatibility

Every v2 column is `NULL`-able. Adapters that pre-date v2 (e.g.
the legacy `dart`, `news`, `macro`, `bok_ecos`, `govt_press`
adapters) keep working — they just emit actors/edges/events with
the v2 fields left blank. The PR-Z `IngestedActor` / PR4-FTC
`IngestedEdge` / `IngestedRawEvent` dataclasses gained new
fields with default `None`, so existing call sites compile
unchanged.
