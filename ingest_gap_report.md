# Ingest Gap Diagnostic — corpus_signal_rate=0.167 root cause

**Trigger**: `backtest/recall.py` reports `corpus_signal_rate=0.167` (2 of
12 target events in `target_events.yaml` had detection-keyword hits in the
ingested document corpus). Hypothesis: the 14-day default ingest window
plus RSS-only news adapter means the historical 2025-07..2025-12 window
is structurally invisible to the current ingest layer. This report
verifies that hypothesis and identifies which targets are recoverable by
config alone vs. which need new code or new sources.

Read-only investigation. No code changed.

---

## Phase 1 — Adapter capability table

| Adapter | API kind | Honors `since`? | Historical fetch? | Default behavior with no key/config | Notes |
|---|---|---|---|---|---|
| `dart` | OpenDART OpenAPI ([dart.py:34](ingest/dart.py#L34)) | ✅ Yes — `bgn_de`/`end_de` query params ([dart.py:68-76](ingest/dart.py#L68-L76)) | ✅ Yes — date-range request | Empty + warning if `DART_API_KEY` unset | Covers 공시 filings (자사주 소각, 5%보고, 분할/합병). True archive. |
| `news` | Google News RSS ([news.py:34](ingest/news.py#L34)) | ❌ **NO** — `since` param accepted but never read in `fetch()` or `_fetch_one()` ([news.py:150-179](ingest/news.py#L150-L179)) | ❌ No — RSS returns latest-N only | Always runs (no key); pulls whatever Google decides is "recent" for the keyword | The biggest source by doc count is also the only one that silently drops `since`. Increasing `since_days` does **literally nothing** here. |
| `govt_press` | Per-ministry RSS ([govt_press.py:32-41](ingest/govt_press.py#L32-L41)) | ✅ Filter only — `if pub_dt < since: continue` ([govt_press.py:100](ingest/govt_press.py#L100)) | ❌ No — RSS endpoints don't expose archives | All 8 ministries default to empty endpoint; "no endpoint configured (skip)" log line | Even with endpoints configured, RSS only returns latest items, so the `since` filter is moot for backfill. |
| `assembly` | data.go.kr OpenAPI ([assembly.py:34-37](ingest/assembly.py#L34-L37)) | ✅ Yes — `if propose_dt < since: seen_old += 1` with paginated walk ([assembly.py:88-117](ingest/assembly.py#L88-L117)) | ✅ Yes — paginated, walks back through 22대 bills | Empty unless `ASSEMBLY_API_KEY` (or fallback `ASSEMBLY_BILLS_URL`) set | Best historical adapter we have. Already wired correctly — just needs a key. |
| `assembly_minutes` | data.go.kr 회의록 OpenAPI (planned) | n/a | ⚠️ **Stub** — `fetch_meeting_metas` returns `[]` even with key set ([assembly_minutes.py:271-277](ingest/assembly_minutes.py#L271-L277)) | Always empty | TODO comment: "Sprint 1: hit data.go.kr endpoint (data/3057576)". 4-stage pipeline (metadata → relevance → body → chunk) skeleton is built; Stage 1 sweep is the missing piece. |
| `bok_ecos` | 한국은행 ECOS API ([bok_ecos.py:25](ingest/bok_ecos.py#L25)) | ✅ Yes — `start`/`end` in URL ([bok_ecos.py:55-57](ingest/bok_ecos.py#L55-L57)) | ✅ Yes — date-range API | Empty + warning if `ECOS_API_KEY` unset | Numeric series only; doesn't produce text documents. Irrelevant for catalog-recall keyword targets. |
| `krx` | data.krx.co.kr OTP-token / local CSV ([krx.py:1-11](ingest/krx.py#L1-L11)) | n/a | ⚠️ **Stub** — OTP not implemented; even `KRX_DATA_PATH` CSV path logs "not yet implemented" ([krx.py:36-38](ingest/krx.py#L36-L38)) | Always empty | Numeric-only when implemented; not in scope for catalog-recall. |
| `macro` | FRED CSV ([macro.py:31](ingest/macro.py#L31)) | ✅ Yes — full series CSV with post-filter on date ([macro.py:82](ingest/macro.py#L82)) | ✅ Yes — FRED returns full history, adapter filters | Always runs (no key needed) | Numeric only; doesn't produce text documents. |

### Key findings from Phase 1

1. **`news.fetch(since)` ignores `since`.** The biggest text source by document count silently drops the parameter. Bumping `since_days` accomplishes nothing for news. Confirmed by reading `_fetch_one()` and the outer `fetch()` loop — neither references `since`.
2. **`govt_press` defaults to all-empty endpoints.** All 8 ministries (mof / fsc / ftc / moti / nts / bok / blue_house / justice) have empty `DEFAULT_ENDPOINTS` strings. Without operator-supplied URLs, this adapter contributes 0 docs regardless of date.
3. **`assembly` *is* historically capable** but gated on `ASSEMBLY_API_KEY` from data.go.kr (free tier). The pagination + age filter is correct.
4. **`assembly_minutes` is a stub** — Stage 1 metadata sweep returns `[]` even when the API key is set. Follow-up Sprint 1 task per the docstring.
5. **DART, ECOS, macro all honor `since` correctly.** No code work needed for them.
6. **`.env.example` does not document** `ASSEMBLY_API_KEY`, `ASSEMBLY_MINUTES_API_KEY`, `GOVT_PRESS_*_URL`, or `KRX_DATA_PATH`. Operator has no way to know they're consumed.

---

## Phase 2 — Target × source coverage matrix

For each of the 12 targets in `backtest/cases/catalog_recall/target_events.yaml`,
the *ideal* sources to catch it and whether the current adapter set could
realistically catch it given today's run config (default `since_days=14`,
no env keys beyond what `.env.example` documents):

| # | Target id | Emergence | Ideal source(s) | Catchable today? | Why not / what's missing |
|---|---|---|---|---|---|
| 1 | commercial_act_first_pass_2025_07_03 | 2025-07-03 | assembly (bill text) + assembly_minutes (법사위 debate) + govt_press:justice + news archive | ❌ | assembly works for historical IF `ASSEMBLY_API_KEY` set AND `since_days≥310`. Today: key absent → 0 docs. |
| 2 | treasury_share_mandatory_cancellation_proposal_2025_07_09 | 2025-07-09 | assembly + news archive | ❌ | Same as #1 — assembly key + `since_days≥300`. |
| 3 | hmm_treasury_retire_2025_08 | 2025-08-15 | DART (자기주식 소각 공시 — definitive) + news | ⚠️ Partial | DART can fetch historically with key + `since_days≥260`. Today: also got an incidental Google News RSS hit for HMM published 2025-10-01 (50 days post-emergence — outside the 5-day window the spec wants). |
| 4 | commercial_act_second_pass_2025_08_25 | 2025-08-25 | assembly + assembly_minutes + news | ❌ | Same as #1. |
| 5 | kospi_5000_special_committee_active_2025_08 | 2025-08-01 | assembly (cosponsor filter on Kim Nam-geun, Oh Ki-hyung) + assembly_minutes + news | ❌ | assembly with key catches cosponsor metadata; minutes adapter is a stub. |
| 6 | yellow_envelope_act_passed_2025_08_26 | 2025-08-26 | assembly + news | ❌ | Same as #1. |
| 7 | corporate_tax_increase_2025_09 | 2025-09-01 | govt_press:mof (기재부 세제개편안 보도자료) + assembly + news | ❌ | mof endpoint empty by default; assembly partially covers via tax-bill metadata; news no historical. |
| 8 | lee_jaemyung_nyse_visit_2025_09_25 | 2025-09-25 | news archive + govt_press:blue_house | ❌ | News no historical fetch; blue_house endpoint empty. No other adapter covers diplomatic events. |
| 9 | mandatory_tender_offer_govt_party_agreement_2025_12_04 | 2025-12-04 | news + govt_press:fsc + assembly (downstream bill) | ❌ | The agreement event itself is news-driven (no bill yet at agreement-time); news archive missing. |
| 10 | align_partners_doosan_bobcat_campaign_2025_q4 | 2025-10-01 | DART (5% rule report — 주식등의대량보유) + news | ⚠️ Partial | DART historical works with key + `since_days≥220`. Today: also got an incidental Google News RSS hit dated 2026-02-09 (130+ days post-emergence — far outside window). |
| 11 | oasis_korea_team_expansion_2025_q4 | 2025-10-15 | news archive (recruitment / fund profile) + DART (only if filings exist) | ❌ | Pure news event; news has no historical fetch. |
| 12 | capital_gains_tax_reform_2025_09 | 2025-09-15 | govt_press:mof + news + assembly | ❌ | mof endpoint empty; assembly gated; news no historical. |

The two corpus hits today are #3 (HMM) and #10 (Align Partners), both via
incidental late Google News RSS aggregation rather than any adapter
honoring `since`. Per `metrics.json`, both `corpus_first_doc_ts` values
are far outside `expected_window_days` — meaning even with the current
two hits, *none* of them would pass a window-aware recall metric.

---

## Phase 3 — Gap categorization

### Cat A — adapter works, just needs config (since_days + key)

Targets where the adapter code already supports historical fetch and
honors `since` correctly. Fix is: bump `since_days` and provision the API
key.

- **#3 hmm_treasury_retire_2025_08** — DART works
- **#10 align_partners_doosan_bobcat_campaign_2025_q4** — DART works
- **#1, #2, #4, #5, #6** if `ASSEMBLY_API_KEY` is provisioned — assembly OpenAPI works historically

**Cheapest fix**: bump `prepare()`'s `since_days` default from 14 to ~365
(or expose it as `DEMO_SINCE_DAYS` env var); document `ASSEMBLY_API_KEY`
and `DART_API_KEY` in `.env.example`; provision both keys.

**Count: 7 of 12 targets** (#1, #2, #3, #4, #5, #6, #10).

### Cat B — adapter incomplete; needs new code on existing source

Targets where the source exists and is partially wired but the adapter
needs implementation work to cover the target's primary signal.

- **#1, #4** — `assembly_minutes` Sprint 1 implementation would add 법사위
  debate signal (currently a Stage 1 stub returning `[]`)
- **#7, #12** — `govt_press` adapter works *forward* once endpoints are
  configured, but no historical-archive code path exists. Needs new
  per-ministry archive scrapers (e.g. mof publishes 보도자료 archive
  pages indexed by 연도/월).

**Cheapest fix per item**:
- assembly_minutes: implement `fetch_meeting_metas` + `fetch_meeting_body`
  against `data.go.kr/data/3057576` — single adapter, ~1 file. Stages 2-4
  (relevance / chunk / filter) are already built.
- govt_press: separate sprint per ministry. Per-ministry archive HTML
  layouts differ; not a one-line config.

**Count: 2-4 of 12 targets** (#1, #4 partial via minutes; #7, #12 via
govt_press archive).

### Cat C — no historical source available with current adapter set

Targets that require sources we don't have an adapter for at all. The
underlying problem is news-archive coverage.

- **#8 lee_jaemyung_nyse_visit_2025_09_25** — only practical source is
  news archive
- **#9 mandatory_tender_offer_govt_party_agreement_2025_12_04** —
  agreement-time news only (no bill yet)
- **#11 oasis_korea_team_expansion_2025_q4** — recruitment news only

**Cheapest fix**: integrate one of the Korean news archive APIs.
Candidates:
- **빅카인즈 (kinds.or.kr)** — 한국언론진흥재단; free API; 11 major
  outlets archived back to 1990s. Cleanest licensing. Recommended.
- Naver News Search API — narrower archive depth, paid above quota.
- NewsBank (newsbank.com) — paid; broader Western coverage, weaker
  Korean-domestic coverage.

**Count: 3 of 12 targets** (#8, #9, #11).

### Tally

| Category | Targets | Cheapest fix |
|---|---|---|
| **A** (config only) | 7 (#1, #2, #3, #4, #5, #6, #10) | `since_days` default + `ASSEMBLY_API_KEY` + `DART_API_KEY`; document in `.env.example` |
| **B** (new code, existing source) | 2-4 (#1, #4 via minutes; #7, #12 via govt_press archive) | assembly_minutes Stage 1 impl (single file); govt_press archive scrapers (per ministry) |
| **C** (new source) | 3 (#8, #9, #11) | Integrate 빅카인즈 (kinds.or.kr) news-archive adapter |

(The total exceeds 12 because some targets — #1, #4 — are partially
served by Cat A and gain additional precision from Cat B.)

---

## 다음 PR 후보

### PR1 — Cat A only (config + 1-line default change)

- Bump `prepare()`'s `since_days` default from 14 to ~365.
- Add `ASSEMBLY_API_KEY` and `ASSEMBLY_MINUTES_API_KEY` to
  `.env.example` (documentation only).
- Operator provisions both keys.

**Estimated lift**: corpus_signal_rate from 0.167 → ~**0.58** (7 of 12
targets newly within window, given the keys). Recall stays at 0 until
the LLM extractor runs over the new corpus.

**Code change**: ~5 lines (default value + env documentation). No
adapter changes.

**Caveat**: the `news` adapter still won't honor `since`. So for the 7
Cat-A targets the historical signal comes entirely from DART (#3, #10)
and assembly OpenAPI (#1, #2, #4, #5, #6). News will continue to
contribute only incidental late-aggregation hits.

### PR2 — assembly_minutes Stage 1 implementation

Add `fetch_meeting_metas` + `fetch_meeting_body` against
`data.go.kr/data/3057576`. Stages 2-4 are already built so this is
single-adapter scope.

**Estimated additional lift**: targets #1 and #4 gain 법사위 debate-stage
catches (independent of bill metadata), letting the extractor pick up
debate-time signal a few days *before* bill passage, which is closer to
the 3-day `expected_window_days` for those targets.

**Code change**: ~1 file (`ingest/assembly_minutes.py` Stage 1 +
optional `run_adapter`-compatible `fetch()` wrapper).

### PR3 — 빅카인즈 (Kinds) news-archive adapter

New `ingest/kinds.py` adapter. Free API with date-range and outlet
filters; covers 11 major Korean outlets historically.

**Estimated additional lift**: targets #8, #9, #11 become catchable.
Caveat: the existing `news` adapter would either be replaced
(Google News RSS contributes mostly noise + duplicates) or kept for
forward-going news with Kinds providing the historical layer.

**Code change**: 1 new adapter file (~150 lines, similar shape to
`news.py`); update `prepare()` to include it; add `KINDS_API_KEY` to
`.env.example`.

### PR4 — govt_press archive scrapers (lower priority)

Per-ministry archive scrapers (mof / fsc / blue_house priority). Only
adds incremental coverage for #7, #8, #9, #12 — and Cat C news archive
likely covers most of those already. Defer until after PR3 lands and
gap is re-measured.

---

## Other drift observed (reporting only)

1. **`.env.example` does not list** `ASSEMBLY_API_KEY`,
   `ASSEMBLY_BILLS_URL`, `ASSEMBLY_MINUTES_API_KEY`, `GOVT_PRESS_<M>_URL`,
   `KRX_DATA_PATH`. The code reads them; the operator has no documentation
   that they exist. This silently nullifies the adapters that would
   otherwise be the strongest historical sources.

2. **`news.py` `fetch(since)` accepts `since` but never uses it.** The
   parameter is part of the `Adapter` protocol contract and is honored
   by every other text adapter. Either: (a) wire it through (probably
   needs a date-range capable news source — i.e. Cat C work), or (b)
   document explicitly in the adapter docstring that the param is
   ignored, so future readers don't assume otherwise.

3. **Three CLI `main()` blocks still have `import db as _db`** instead
   of `import persistence as _db`: [ingest/govt_press.py:128](ingest/govt_press.py#L128),
   [ingest/assembly.py:197](ingest/assembly.py#L197),
   [ingest/news.py:183](ingest/news.py#L183),
   [ingest/dart.py:148-150](ingest/dart.py#L148-L150) (this one is also
   doubled — calls `db.init()` then immediately reassigns `con` from
   `_db.init()`),
   [ingest/macro.py:93](ingest/macro.py#L93),
   [ingest/bok_ecos.py:89](ingest/bok_ecos.py#L89). Same package-rename
   regression as the recall.py fix in the previous PR. Each of these
   `python -m ingest.<adapter>` CLIs will fail with `ModuleNotFoundError`
   at module-entry. Not in scope; flagging.

4. **`assembly_minutes.py` lines 111, 122** — `import db as _db` inside
   helper functions, same regression. Functions go through silent path
   today because nobody calls them, but Sprint 1 minutes work will trip
   over this immediately.
