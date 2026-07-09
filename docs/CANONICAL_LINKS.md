# PR4-CANONICAL + PR-PARTY-CANONICAL — yaml seed + DB dynamic state

Self-evolving canonical resolution layer. Bridges NEC / FTC / DART /
ASSEMBLY actor identifiers and chaebol organization aliases via 7
dynamic state tables + 4 yaml seeds + Tier B/C/D fuzzy match. The
follow-up PR-PARTY-CANONICAL adds political party entity resolution on
top of the same canonical link table.

## Self-evolving model framing

```
yaml seed     = git-versioned bootstrap anchor (one-shot hand-curate)
                ↓
DB dynamic    = real-time source of truth
state machine = proposed → active → deprecated → retired
trust accrual = verification_count >= 3 AND confidence >= 0.7 → promote
self-correct  = contradicting evidence → deprecate (audit trail kept)
auto-discover = media mentions → proposed → trust accrual → active
```

Hand-curate is bootstrap-once. The model extends, corrects, and deprecates
itself from API + media signal. yaml seeds are anchors — *not load-bearing*.

## 7 dynamic state tables

| Table | Purpose | PK |
|---|---|---|
| `actor_canonical_links` | Cross-source canonical (person + organization). State machine. | canonical_id |
| `chaebol_aliases_state` | alias → canonical_org_id. Resolves 한글·영문·history transition forms. | (alias, canonical_org_id) |
| `dart_executive_state` | DART 임원 trajectory — per (actor, rcept_no) snapshot. | (actor_id, rcept_no) |
| `nec_candidate_state` | NEC 후보 trajectory — per (canonical, election) snapshot. | (actor_id, election_id) |
| `ftc_executive_state` | FTC 임원·owner trajectory — per (actor, year) snapshot. | (actor_id, designation_year) |
| `chaebol_tier_state` | Chaebol ranking trajectory — per (canonical_org, year). | (canonical_org_id, designation_year) |
| `assembly_member_state` | ASSEMBLY 의원 trajectory — per (actor, term) snapshot. | (actor_id, assembly_term) |

`actors_dyn.canonical_org_id` (column added) backfilled across all 74,486
chaebol owner / executive / role / company actors via C4 retrofit.

## Party canonical addendum

PR-PARTY-CANONICAL extends the same canonical layer to political
parties:

- `actor_canonical_links.canonical_type` now accepts `party`.
- `actors_dyn.canonical_party_id` stores the resolved `party_*` actor id.
- `actors_dyn.is_independent` marks `무소속` separately; independent actors
  keep `canonical_party_id = NULL`.
- `bootstrap_party_canonical_from_actors()` migrates existing `party_*`
  actors into `actor_canonical_links`.
- `resolve_party_canonical()` resolves `current_party_name` to a stable
  canonical party id when possible.

Live DB health after the retrofit is covered by
`python -m scripts.verify_canonical` checks 16-18.

## 4 yaml seeds

| File | Role |
|---|---|
| `chaebol_canonical.yaml` | 34 top-30 chaebol canonical_org_ids + tier + representative companies |
| `chaebol_aliases.yaml` | 34 canonical → 185 alias forms (한글·영문·한자·history transitions) |
| `chaebol_classification.yaml` | 106 chaebol forms → tier 1~5 ranking (FTC actual form, 영문 dead entries removed) |
| `cross_sector_canonical.yaml` | 126 hand-curated person seed cases (정치 ↔ 경제 cross-sector) |

## Tier strategy (NEC ↔ DART)

```
Tier A (hanja + dob)         — already covered by NEC; DART has no hanja
Tier B (name + YYYYMM)       — main path. Single candidate → confidence 0.85
Tier C (name + YYYYMM + score) — multi-candidate scored by:
                                 base 0.5
                                 + 0.20  owner-family signal
                                          (mxmm_shrholdr_relate)
                                 + 0.15  political career keyword
                                          (main_career)
                                 + 0.05  senior position (chairman etc)
                                 capped at 0.85
Tier D (LLM disambiguate)    — score < 0.7 → Sonnet ~$0.005/call
                                 high_value_only=True restricts to
                                 peak_political_tier ≤ 2 OR
                                 peak_economic_tier ≤ 2
                                 .cache/llm_cost_pr4.json daily $5 cap
Tier E (yaml seed)           — bootstrap anchor only · 모델이 extend/correct
```

## Trust accrual + state transitions

```
state = 'proposed' (initial — fuzzy match / yaml seed person / LLM gen)
      → state = 'active'    when verification_count >= 3 AND confidence >= 0.7
      → state = 'deprecated' on contradicting evidence (manual or learned)
      → state = 'retired'    on operator decision (kept for audit)

verification_count++ via:
  - media_mention co-occurrence (discover_from_documents)
  - re-confirmation via fuzzy_match (rev_history append)
  - manual operator confirmation

confidence accrual: +0.1 per evidence_strength=1.0 verification
                    capped at 1.0
```

`rev_history_json` captures every state change for audit trail. Deprecated
rows stay in DB — never deleted (PR-LEARN can reason about why a
canonical was retired).

## CLI usage

```bash
# Bootstrap yaml → DB dynamic state (idempotent)
python -m persistence.canonical --bootstrap

# Force reseed (yaml content overwrites yaml_seed source rows)
python -m persistence.canonical --bootstrap --force-reseed

# C4 retrofit for existing data (74k chaebol actors + 70k FTC + 81k NEC)
python -m scripts.retrofit_pr4_canonical               # dry-run
python -m scripts.retrofit_pr4_canonical --apply       # commit

# DART 임원 ingest (5대 chaebol smoke)
python -m ingest.dart_exec

# ASSEMBLY ALLNAMEMBER ingest (3,286 의원 base trajectory)
python -m ingest.assembly_members

# Health check (15 checks)
python -m scripts.verify_canonical
```

## API surface

```python
import persistence as db

# Bootstrap
counts = db.bootstrap_from_yaml(con, force_reseed=False)

# Resolve
canonical_org_id = db.resolve_org_canonical(con, "에스케이")  # → 'org_chaebol_sk'
canonical_org_id = db.resolve_org_canonical(con, "SK")        # → 'org_chaebol_sk'
canonical_org_id = db.resolve_org_canonical(con, "선경")       # → 'org_chaebol_sk'

# Trust accrual + promotion
state = db.update_trust_score(con, canonical_id, "media_mention", 1.0)

# LLM auto-gen (gated by daily cap)
new_aliases = db.llm_generate_chaebol_aliases(con, "org_chaebol_xxx", "그룹명")

# Cross-source matching
stats = db.fuzzy_match_cross_sector(con, high_value_only=True, llm_cap=1000)

# Auto-discovery
stats = db.discover_from_documents(con, since="2024-01-01")

# LLM cost remaining today
remaining_usd = db.llm_cost_remaining()
```

## Forward-compat for PR-LEARN

- `actor_canonical_links.learned_attributes_json` — power_share /
  dormant_power_score 학습 결과 박힘 (schema migration 없음)
- `chaebol_tier_state` 매년 row → ranking trajectory 학습
- `dart_executive_state.main_career` raw → cross-domain transition signal
- `dart_executive_state.mxmm_shrholdr_relate` raw → power_share prior
- `*_state` 모든 trajectory tables → time-varying 학습 input

## C1~C5 Commit Trail

| Commit | Scope |
|---|---|
| C1 (`c72b53e`) | 7 tables + ALTER ADD canonical_org_id + 4 yaml seeds |
| C2 (`5f3b073`) | persistence/canonical.py — bootstrap·resolve·trust·LLM gen |
| C3 (`0951979`) | ingest/dart_exec.py + ingest/assembly_members.py (Tier A pair confirmed) |
| C4 (`e433ca1`) | 74k chaebol canonical_org_id backfill + 70k FTC + 81k NEC state seeds |
| C5 (this) | fuzzy_match Tier B/C/D + verify_canonical 15 checks + this doc |

## Known follow-up

- ingest/ftc.py / ingest/nec.py — wire canonical_org_id at upsert time
  so future ingests don't need re-running retrofit (pure ergonomics;
  retrofit is idempotent).
- Multi-year `ftc_executive_state` backfill — current seed is one row
  per actor; PR-LEARN ranking-trajectory work needs per-year FTC
  re-ingest if multi-year coverage required.
- DART corp_codes 전체 list — extend `CORP_CODES_C3` from corpCode.xml
  download via DART OpenAPI; current is 5대 chaebol smoke only.
- `discover_from_documents` event_subtype markers — current marker
  prefixes are best-effort. Tune via inspection of actual
  `event_subtype` distribution in `raw_events`.
