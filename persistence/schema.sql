-- ==== Phase 1-2: ingestion / storage ====================================

CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,                 -- 'dart' / 'govt_press:mof' / 'news' / ...
    url            TEXT,
    title          TEXT,
    body           TEXT,
    published_at   TEXT,                          -- ISO8601
    fetched_at     TEXT NOT NULL,                 -- ISO8601
    raw_hash       TEXT UNIQUE,
    metadata_json  TEXT,
    -- ==== Schema v2 hot fields (PR-SCHEMA-V2) ====
    -- Denormalized for indexable filters; keeps metadata_json as the
    -- lossless source of truth.
    outlet               TEXT,                    -- e.g. '조선일보' / 'mof' / etc
    llm_priority         INTEGER,                 -- 1=hot, higher=lower priority
    matched_actors_json  TEXT,                    -- list of canonical actor_ids found in body
    signal_extracted     INTEGER                  -- 0/1 — has the LLM extractor visited
);

CREATE TABLE IF NOT EXISTS variables (
    spec_id         TEXT NOT NULL,                -- VariableSpec.id
    ts              TEXT NOT NULL,                -- observation timestamp ISO8601
    value_json      TEXT NOT NULL,                -- numeric / categorical / etc encoded
    confidence      REAL DEFAULT 1.0,
    source_doc_id   INTEGER,
    PRIMARY KEY (spec_id, ts),
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS raw_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id   TEXT NOT NULL,                  -- EventTemplate.id
    ts            TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    source_doc_id INTEGER,
    severity      REAL,
    -- ==== Schema v2 (PR-SCHEMA-V2) ====
    -- Actor reference (denormalized from payload_json for indexable joins)
    primary_actor_id    TEXT,                     -- canonical actor_id mainly affected
    event_subtype       TEXT,                     -- e.g. 'candidate_registered', 'subsidiary_addition'
    -- Behavioural-economic lens: same event affects different actors
    -- with different magnitudes / interpretations
    impact_magnitude    REAL,                     -- 0~1, event-level intensity
    actor_targets_json  TEXT,                     -- [{actor_id, magnitude, interpretation?}, ...]
    CHECK (impact_magnitude IS NULL OR (impact_magnitude >= 0.0 AND impact_magnitude <= 1.0)),
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    doc_count    INTEGER DEFAULT 0,
    var_count    INTEGER DEFAULT 0,
    event_count  INTEGER DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS actor_calibrations (
    actor_id            TEXT NOT NULL,
    ts                  TEXT NOT NULL,
    traits_json         TEXT NOT NULL,
    interests_json      TEXT NOT NULL,
    belief_priors_json  TEXT NOT NULL,
    affect_json         TEXT,
    source_doc_ids_json TEXT,
    notes               TEXT,
    PRIMARY KEY (actor_id, ts)
);

-- ==== Phase 3-5: simulation =============================================

CREATE TABLE IF NOT EXISTS actors (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    persona_path TEXT,
    category     TEXT,
    role         TEXT,
    activation   TEXT,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS states (
    actor_id   TEXT NOT NULL,
    tick       INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (actor_id, tick)
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    tick          INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    targets_json  TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    actor_id      TEXT NOT NULL,
    tick          INTEGER NOT NULL,
    prompt_hash   TEXT,
    response_json TEXT,
    raw_response  TEXT,
    PRIMARY KEY (actor_id, tick)
);

CREATE TABLE IF NOT EXISTS decision_journal (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT NOT NULL,
    hypothesis           TEXT NOT NULL,
    affected_tickers_json TEXT NOT NULL,
    model_implied_prob   REAL NOT NULL,
    market_implied_prob  REAL,
    conviction_score     REAL,
    kelly_fraction       REAL,
    position_size_won    INTEGER,
    expected_outcome_t1  TEXT,
    expected_outcome_t30 TEXT,
    actual_outcome_t1    TEXT,
    actual_outcome_t30   TEXT,
    lessons              TEXT,
    brier_score          REAL,
    metadata_json        TEXT
);

CREATE TABLE IF NOT EXISTS market_pressure (
    tick              INTEGER NOT NULL,
    asset             TEXT NOT NULL,
    net_pressure      REAL NOT NULL,
    contributors_json TEXT NOT NULL,
    PRIMARY KEY (tick, asset)
);

CREATE TABLE IF NOT EXISTS edges (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    PRIMARY KEY (a, b),
    CHECK (a < b)
);

-- ==== Dynamic catalog registry =========================================
-- LLM agenda extractor가 row를 'proposed' 상태로 insert.
-- trust score / manual review / backtest gate를 거쳐 'active' 승격.

CREATE TABLE IF NOT EXISTS event_templates_dyn (
    id                       TEXT PRIMARY KEY,
    label                    TEXT NOT NULL,
    category                 TEXT NOT NULL,
    detection_json           TEXT NOT NULL,
    source                   TEXT NOT NULL,
    typical_severity         REAL DEFAULT 0.5,
    affects_actors_json      TEXT NOT NULL,
    variables_to_update_json TEXT,
    notes                    TEXT,
    status                   TEXT DEFAULT 'proposed',  -- proposed|reviewed|active|deprecated
    trust_score              REAL DEFAULT 0.0,
    proposal_source          TEXT,                     -- 'hardcoded'|'llm_extractor'|'manual'
    proposed_by              TEXT,
    proposed_at              TEXT,
    promoted_at              TEXT,
    promoted_by              TEXT,
    deprecated_at            TEXT,
    rationale                TEXT,
    backtest_log             TEXT
);

CREATE TABLE IF NOT EXISTS variable_specs_dyn (
    id                       TEXT PRIMARY KEY,
    label                    TEXT NOT NULL,
    source                   TEXT NOT NULL,
    source_params_json       TEXT NOT NULL,
    frequency                TEXT,
    kind                     TEXT,
    categorical_labels_json  TEXT,
    tier                     INTEGER DEFAULT 1,
    affects_actors_json      TEXT NOT NULL,
    notes                    TEXT,
    status                   TEXT DEFAULT 'proposed',
    trust_score              REAL DEFAULT 0.0,
    proposal_source          TEXT,
    proposed_by              TEXT,
    proposed_at              TEXT,
    promoted_at              TEXT,
    promoted_by              TEXT,
    deprecated_at            TEXT,
    rationale                TEXT
);

CREATE TABLE IF NOT EXISTS causal_edges_dyn (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    source_actor             TEXT NOT NULL,
    source_var               TEXT NOT NULL,
    target_actor             TEXT NOT NULL,
    target_var               TEXT NOT NULL,
    blend_targets_json       TEXT NOT NULL,
    strength                 REAL DEFAULT 0.3,
    notes                    TEXT,
    status                   TEXT DEFAULT 'proposed',
    trust_score              REAL DEFAULT 0.0,
    proposal_source          TEXT,
    proposed_by              TEXT,
    proposed_at              TEXT,
    promoted_at              TEXT,
    rationale                TEXT,
    UNIQUE(source_actor, source_var, target_actor, target_var)
);

CREATE TABLE IF NOT EXISTS actors_dyn (
    id                       TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    category                 TEXT,
    role                     TEXT,
    activation               TEXT DEFAULT 'always_on',
    identity_json            TEXT,
    sources_json             TEXT,
    schema_json              TEXT,
    decision_variables_json  TEXT,
    notes                    TEXT,
    status                   TEXT DEFAULT 'proposed',
    trust_score              REAL DEFAULT 0.0,
    proposal_source          TEXT,
    proposed_by              TEXT,
    proposed_at              TEXT,
    promoted_at              TEXT,
    promoted_by              TEXT,
    deprecated_at            TEXT,
    rationale                TEXT,
    -- Stratification — added in PR-Z. NULL means unstratified (legacy
    -- rows seeded before PR-Z; resolution is PR4-PERSON's responsibility).
    -- 'role_instance' = a person filling a role at a point in time
    -- (e.g. president = the office; lee_jaemyung as president = role_instance).
    type                     TEXT
        CHECK(type IS NULL OR type IN
              ('person', 'organization', 'role_instance', 'unknown')),
    -- ==== Schema v2 hot fields (PR-SCHEMA-V2) ====
    -- Identity hot fields denormalized from identity_json for index-driven
    -- joins. NFKC-normalized at every persist boundary (see persistence.core_io).
    hanja_name               TEXT,
    birthday                 TEXT,                -- YYYYMMDD
    external_id              TEXT,                -- huboid / jurirno / mona_cd / naas_cd
    external_id_type         TEXT
        CHECK(external_id_type IS NULL
              OR external_id_type IN ('huboid','jurirno','mona_cd','naas_cd')),
    -- Tier system: peak = highest seen across history (lowest number = highest tier)
    political_tier           INTEGER
        CHECK(political_tier IS NULL OR political_tier BETWEEN 1 AND 5),
    economic_tier            INTEGER
        CHECK(economic_tier IS NULL OR economic_tier BETWEEN 1 AND 5),
    peak_political_tier      INTEGER
        CHECK(peak_political_tier IS NULL OR peak_political_tier BETWEEN 1 AND 5),
    peak_economic_tier       INTEGER
        CHECK(peak_economic_tier IS NULL OR peak_economic_tier BETWEEN 1 AND 5),
    registered_as_candidate  INTEGER DEFAULT 0
        CHECK(registered_as_candidate IN (0, 1)),
    -- Position fields (current snapshot)
    current_governance_position TEXT,
    current_party_position      TEXT,
    current_party_name          TEXT,
    current_corp_position       TEXT,
    current_corp_group          TEXT,
    -- Tier history JSON: [{ts, political_tier, economic_tier, reason, source}, ...]
    tier_history_json        TEXT,
    -- ==== PR4-CANONICAL: cross-source canonical org reference ====
    -- chaebol_owner / executive actors carry canonical_org_id resolved via
    -- chaebol_aliases_state, so '에스케이' / 'SK' / 'ìì¤ì¼ì´' all
    -- collapse onto org_chaebol_sk. Backfilled by PR4-CANONICAL retrofit.
    canonical_org_id         TEXT,
    -- ==== PR-PARTY-CANONICAL: 정당 canonical reference ====
    -- person actors carry canonical_party_id (FK to actor_canonical_links
    -- canonical_type='party') resolved from current_party_name.
    -- 무소속 → canonical_party_id IS NULL AND is_independent=1.
    canonical_party_id       TEXT,
    is_independent           INTEGER NOT NULL DEFAULT 0
        CHECK(is_independent IN (0, 1))
);

-- ==== PR-Z: actor-actor relationship edges (separate from causal_edges_dyn,
-- which models variable→variable causal blends). edges_dyn captures
-- structural / social / political ties: subsidiary_of, owns, executive_of,
-- shareholder_of, family_relation, political_affiliation, etc.
-- Convention: edge_type strings are not enum-constrained; new types can
-- be added without schema migration.
CREATE TABLE IF NOT EXISTS edges_dyn (
    src_actor_id  TEXT NOT NULL,
    dst_actor_id  TEXT NOT NULL,
    edge_type     TEXT NOT NULL,
    ts            TEXT NOT NULL,           -- ISO8601 (PR-Z spec used TIMESTAMP;
                                           -- SQLite stores TEXT regardless)
    metadata      TEXT,                    -- JSON
    -- ==== Schema v2 (PR-SCHEMA-V2) ====
    election_id   TEXT,                    -- denormalized for fast filter (NEC edges)
    -- Behavioural-economic lens: relationship strength + observer
    -- confidence. NEC `member_of_party` = 1.0/1.0 (deterministic);
    -- FTC `shareholder_of` carries actual ownership_pct/100; LLM-extracted
    -- edges may carry strength·confidence < 1.0 to express uncertainty.
    strength      REAL,
    confidence    REAL,
    CHECK (strength IS NULL OR (strength >= 0.0 AND strength <= 1.0)),
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    PRIMARY KEY (src_actor_id, dst_actor_id, edge_type, ts)
);

CREATE INDEX IF NOT EXISTS idx_edges_dyn_src  ON edges_dyn(src_actor_id);
CREATE INDEX IF NOT EXISTS idx_edges_dyn_dst  ON edges_dyn(dst_actor_id);
CREATE INDEX IF NOT EXISTS idx_edges_dyn_type ON edges_dyn(edge_type);

-- ==== PR-Z2: person alias mapping ========================================
-- alias_actor_id (Tier C surface seed e.g. 'person_홍석조_BGF') →
-- canonical_actor_id (Tier A strong identifier e.g.
-- 'person_홍석조_洪錫祚_19460519'). Append-only: PK includes resolved_at,
-- so re-resolution at a later timestamp creates a new row instead of
-- overwriting (history preserved). `resolve_canonical()` always returns
-- the latest mapping per alias.
--
-- evidence_source convention (not enum-enforced):
--   'NEC_match'         — strong identifier match via NEC (선거관리위원회)
--   'DART_match'        — corp_code + executive disclosure cross-ref
--   'LLM_RAG'           — LLM batch resolution over RAG context
--   'manual_review'     — operator override
--   'deterministic'     — exact name+DOB or other unambiguous join
--
-- Resolution by PR4-PERSON. PR4-FTC may seed Tier C aliases without
-- canonical mapping (those rows simply have no person_aliases entry yet).
CREATE TABLE IF NOT EXISTS person_aliases (
    alias_actor_id     TEXT NOT NULL,
    canonical_actor_id TEXT NOT NULL,
    confidence         REAL,                -- 0~1, NULL allowed
    evidence_source    TEXT,
    resolved_at        TEXT NOT NULL,       -- ISO8601
    metadata           TEXT,                -- JSON
    PRIMARY KEY (alias_actor_id, canonical_actor_id, resolved_at)
);

CREATE INDEX IF NOT EXISTS idx_person_aliases_alias
    ON person_aliases(alias_actor_id);
CREATE INDEX IF NOT EXISTS idx_person_aliases_canonical
    ON person_aliases(canonical_actor_id);
CREATE INDEX IF NOT EXISTS idx_person_aliases_evidence
    ON person_aliases(evidence_source);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    docs_scanned      INTEGER DEFAULT 0,
    proposals_event   INTEGER DEFAULT 0,
    proposals_var     INTEGER DEFAULT 0,
    proposals_edge    INTEGER DEFAULT 0,
    proposals_actor   INTEGER DEFAULT 0,
    matched_existing  INTEGER DEFAULT 0,
    llm_model         TEXT,
    cost_usd          REAL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS extraction_doc_links (
    -- which docs have been extracted (avoids re-running)
    run_id     INTEGER NOT NULL,
    doc_id     INTEGER NOT NULL,
    PRIMARY KEY (run_id, doc_id),
    FOREIGN KEY (run_id) REFERENCES extraction_runs(id),
    FOREIGN KEY (doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS extraction_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_kind TEXT NOT NULL,        -- 'event'|'var'|'edge'|'actor'
    proposal_id   TEXT NOT NULL,
    action        TEXT NOT NULL,        -- 'promote'|'reject'|'edit'|'merge'|'deprecate'
    reason        TEXT,
    decided_by    TEXT,                 -- 'human:<id>' or 'auto:<rule>'
    decided_at    TEXT NOT NULL
);

-- ==== Assembly minutes =================================================

CREATE TABLE IF NOT EXISTS actor_utterances (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id          TEXT,
    raw_speaker       TEXT NOT NULL,
    meeting_id        TEXT NOT NULL,
    meeting_date      TEXT NOT NULL,
    committee         TEXT,
    bill_id           TEXT,
    content           TEXT NOT NULL,
    relevance_score   REAL,
    extracted_stance  TEXT,
    extracted_topics_json TEXT,
    source_doc_id     INTEGER,
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS eum_traces (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id              TEXT NOT NULL,
    actor_id             TEXT NOT NULL,
    meeting_date         TEXT NOT NULL,
    position_estimate    REAL,
    salience_estimate    REAL,
    stance               TEXT,
    rationale            TEXT,
    source_utterance_id  INTEGER,
    FOREIGN KEY (source_utterance_id) REFERENCES actor_utterances(id)
);

-- ==== Indexes ===========================================================

CREATE INDEX IF NOT EXISTS idx_events_tick    ON events(tick);
CREATE INDEX IF NOT EXISTS idx_events_source  ON events(source);
CREATE INDEX IF NOT EXISTS idx_journal_ts     ON decision_journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_docs_source    ON documents(source);
CREATE INDEX IF NOT EXISTS idx_docs_published ON documents(published_at);
CREATE INDEX IF NOT EXISTS idx_vars_spec      ON variables(spec_id);
CREATE INDEX IF NOT EXISTS idx_vars_ts        ON variables(ts);
CREATE INDEX IF NOT EXISTS idx_raw_events_ts  ON raw_events(ts);
CREATE INDEX IF NOT EXISTS idx_raw_events_tpl ON raw_events(template_id);
CREATE INDEX IF NOT EXISTS idx_calib_actor    ON actor_calibrations(actor_id);
CREATE INDEX IF NOT EXISTS idx_ingrun_source  ON ingestion_runs(source);
CREATE INDEX IF NOT EXISTS idx_evtdyn_status  ON event_templates_dyn(status);
CREATE INDEX IF NOT EXISTS idx_vardyn_status  ON variable_specs_dyn(status);
CREATE INDEX IF NOT EXISTS idx_edgedyn_status ON causal_edges_dyn(status);
CREATE INDEX IF NOT EXISTS idx_actdyn_status  ON actors_dyn(status);
CREATE INDEX IF NOT EXISTS idx_extlink_doc    ON extraction_doc_links(doc_id);
CREATE INDEX IF NOT EXISTS idx_utter_actor    ON actor_utterances(actor_id);
CREATE INDEX IF NOT EXISTS idx_utter_bill     ON actor_utterances(bill_id);
CREATE INDEX IF NOT EXISTS idx_eum_bill       ON eum_traces(bill_id);

-- ==== Schema v2 indexes (PR-SCHEMA-V2) =================================

-- actors_dyn
CREATE INDEX IF NOT EXISTS idx_actors_dyn_proposal_source
    ON actors_dyn(proposal_source);
CREATE INDEX IF NOT EXISTS idx_actors_dyn_type
    ON actors_dyn(type);
CREATE INDEX IF NOT EXISTS idx_actors_dyn_name
    ON actors_dyn(name);
CREATE INDEX IF NOT EXISTS idx_actors_dyn_hanja_birthday
    ON actors_dyn(hanja_name, birthday)
    WHERE hanja_name IS NOT NULL AND birthday IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_name_birthday
    ON actors_dyn(name, birthday)
    WHERE birthday IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_external
    ON actors_dyn(external_id_type, external_id)
    WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_political_tier
    ON actors_dyn(political_tier)
    WHERE political_tier IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_economic_tier
    ON actors_dyn(economic_tier)
    WHERE economic_tier IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_governance_position
    ON actors_dyn(current_governance_position)
    WHERE current_governance_position IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_corp_group
    ON actors_dyn(current_corp_group)
    WHERE current_corp_group IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actors_dyn_dual_tier
    ON actors_dyn(political_tier, economic_tier)
    WHERE political_tier IS NOT NULL AND economic_tier IS NOT NULL;

-- edges_dyn
CREATE INDEX IF NOT EXISTS idx_edges_dyn_election
    ON edges_dyn(election_id)
    WHERE election_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_edges_dyn_strength
    ON edges_dyn(strength)
    WHERE strength IS NOT NULL;

-- raw_events
CREATE INDEX IF NOT EXISTS idx_raw_events_primary_actor
    ON raw_events(primary_actor_id)
    WHERE primary_actor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_events_subtype
    ON raw_events(event_subtype)
    WHERE event_subtype IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_events_template
    ON raw_events(template_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_impact
    ON raw_events(impact_magnitude)
    WHERE impact_magnitude IS NOT NULL;

-- documents
CREATE INDEX IF NOT EXISTS idx_documents_outlet
    ON documents(outlet)
    WHERE outlet IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_llm_priority
    ON documents(llm_priority)
    WHERE llm_priority IS NOT NULL AND signal_extracted IS NULL;

-- person_aliases
CREATE INDEX IF NOT EXISTS idx_person_aliases_canonical_evidence
    ON person_aliases(canonical_actor_id, evidence_source);

-- ==== PR-CONTRACT-v0: Layer 1 산출물 contract =============================
-- spec stack §3.1 NarrativeAssessment implementation. 5 dataclass의 DB 표현
-- + actor_decision_journal (★ direction.md §5 non-negotiable drift fix).
--
-- Naming note: 기존 `decision_journal` 테이블은 trade hypothesis용 (Layer 2)
-- 으로 schema.sql line ~111에 박혀있고 호출 site 0개. PR-CONTRACT-v0가
-- 박는 actor decision audit trail은 별도 테이블 `actor_decision_journal`로
-- 분리해 기존 trade journal 의도와 충돌 회피.

CREATE TABLE IF NOT EXISTS assessments (
    assessment_id            TEXT PRIMARY KEY,
    timestamp                TEXT NOT NULL,                  -- ISO 생성 시점
    assessment_window_start  TEXT NOT NULL,
    assessment_window_end    TEXT NOT NULL,
    methodology_version      TEXT NOT NULL,
    confidence               REAL NOT NULL
        CHECK (confidence >= 0 AND confidence <= 1),
    market_narrative_json    TEXT NOT NULL,                  -- MarketNarrativeState
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_assessments_timestamp
    ON assessments(timestamp);
CREATE INDEX IF NOT EXISTS idx_assessments_window
    ON assessments(assessment_window_start, assessment_window_end);
CREATE INDEX IF NOT EXISTS idx_assessments_methodology
    ON assessments(methodology_version);


CREATE TABLE IF NOT EXISTS assessment_targets (
    target_id                       TEXT PRIMARY KEY,
    assessment_id                   TEXT NOT NULL,
    ticker                          TEXT NOT NULL,
    direction                       INTEGER NOT NULL
        CHECK (direction IN (-1, 1)),
    rationale                       TEXT NOT NULL,
    expected_horizon_days           INTEGER NOT NULL
        CHECK (expected_horizon_days > 0),
    sizing_pct_prior                REAL NOT NULL
        CHECK (sizing_pct_prior >= 0 AND sizing_pct_prior <= 1),
    actor_decision_likelihood_json  TEXT,                    -- dict[actor_id, float]
    evidence_weights_json           TEXT,                    -- dict[actor_id, float]
    associated_gap_ids_json         TEXT,                    -- list[str]
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id)
);

CREATE INDEX IF NOT EXISTS idx_targets_assessment
    ON assessment_targets(assessment_id);
CREATE INDEX IF NOT EXISTS idx_targets_ticker
    ON assessment_targets(ticker);
CREATE INDEX IF NOT EXISTS idx_targets_direction
    ON assessment_targets(direction);


CREATE TABLE IF NOT EXISTS reality_gap_observations (
    gap_id                   TEXT PRIMARY KEY,
    assessment_id            TEXT NOT NULL,
    gap_type                 TEXT NOT NULL
        CHECK (gap_type IN ('quantitative', 'qualitative',
                            'cross_source', 'leading_follower')),
    description              TEXT NOT NULL,
    quantitative_metric_json TEXT,
    qualitative_evidence     TEXT,
    severity                 REAL NOT NULL
        CHECK (severity >= 0 AND severity <= 1),
    affected_actors_json     TEXT NOT NULL,
    is_future                INTEGER NOT NULL DEFAULT 0      -- 0=RealityGap, 1=FutureNarrativeGap
        CHECK (is_future IN (0, 1)),
    catalyst                 TEXT,                            -- FutureNarrativeGap만
    catalyst_actor_ids_json  TEXT,
    horizon_days             INTEGER,
    direction                INTEGER
        CHECK (direction IS NULL OR direction IN (-1, 1)),
    confidence               REAL
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id)
);

CREATE INDEX IF NOT EXISTS idx_gaps_assessment
    ON reality_gap_observations(assessment_id);
CREATE INDEX IF NOT EXISTS idx_gaps_type
    ON reality_gap_observations(gap_type);
CREATE INDEX IF NOT EXISTS idx_gaps_severity
    ON reality_gap_observations(severity);
CREATE INDEX IF NOT EXISTS idx_gaps_future
    ON reality_gap_observations(is_future);


CREATE TABLE IF NOT EXISTS predictions (
    prediction_id            TEXT PRIMARY KEY,
    assessment_id            TEXT NOT NULL,
    target_id                TEXT NOT NULL,
    logged_at                TEXT NOT NULL,                  -- ★ 생성 시점 — hindsight bias 차단
    expected_outcome_json    TEXT NOT NULL,
    horizon_end              TEXT NOT NULL,                  -- deadline ISO
    ci_low                   REAL,
    ci_high                  REAL,
    actual_outcome_json      TEXT,                            -- 사후
    actual_logged_at         TEXT,                            -- 사후
    brier_score              REAL,                            -- 사후
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id),
    FOREIGN KEY (target_id) REFERENCES assessment_targets(target_id)
);

CREATE INDEX IF NOT EXISTS idx_predictions_assessment
    ON predictions(assessment_id);
CREATE INDEX IF NOT EXISTS idx_predictions_target
    ON predictions(target_id);
CREATE INDEX IF NOT EXISTS idx_predictions_pending
    ON predictions(actual_outcome_json)
    WHERE actual_outcome_json IS NULL;
CREATE INDEX IF NOT EXISTS idx_predictions_horizon
    ON predictions(horizon_end);


-- actor_decision_journal: ★ direction.md §5 non-negotiable drift fix.
-- world.tick() 안의 actor.decide() loop이 *모든 actor decision*에 대해
-- 이 테이블에 한 row씩 박는다. trade journal (decision_journal) 과 분리:
-- 그 테이블은 Layer 2의 trade hypothesis 용으로 따로 유지된다.
--
-- v0.1: Affect 3D raw (fear/greed/urgency) 직접 박힘 + 2D derived
-- (valence/arousal) 백워드-호환 그대로. PR-LEARN의 inverse Bayesian
-- inference에서 fear·greed trajectory 별도 학습 가능 — 행동경제 원리
-- (loss aversion · greed-driven over-confidence) 직접 측정.
CREATE TABLE IF NOT EXISTS actor_decision_journal (
    entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id        TEXT NOT NULL,
    tick            INTEGER NOT NULL,
    timestamp       TEXT NOT NULL,                            -- ISO 생성 시점
    event_type      TEXT NOT NULL,                            -- e.kind (hold/buy/sell/...)
    event_subtype   TEXT,                                     -- finer-grained
    target_id       TEXT,                                     -- target asset / actor
    magnitude       REAL,
    confidence      REAL
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    -- Affect 2D derived (Russell 1980 valence-arousal 호환, backward-compat)
    affect_valence  REAL,                                     -- = (greed - fear)
    affect_arousal  REAL,                                     -- = urgency
    -- Affect 3D raw (AffectiveState fear/greed/urgency, all ∈ [0,1])
    affect_fear     REAL
        CHECK (affect_fear IS NULL OR (affect_fear >= 0 AND affect_fear <= 1)),
    affect_greed    REAL
        CHECK (affect_greed IS NULL OR (affect_greed >= 0 AND affect_greed <= 1)),
    affect_urgency  REAL
        CHECK (affect_urgency IS NULL OR (affect_urgency >= 0 AND affect_urgency <= 1)),
    rationale       TEXT,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_actor_journal_actor
    ON actor_decision_journal(actor_id);
CREATE INDEX IF NOT EXISTS idx_actor_journal_tick
    ON actor_decision_journal(tick);
CREATE INDEX IF NOT EXISTS idx_actor_journal_event_type
    ON actor_decision_journal(event_type);


-- ============================================================================
-- PR4-CANONICAL: yaml seed + DB dynamic state pattern
-- ============================================================================
-- Self-evolving model. yaml seed = git-versioned bootstrap anchor.
-- DB dynamic state = real-time source of truth.
-- State machine: proposed | active | deprecated | retired
-- Trust accrual: verification_count >= 3 + confidence >= 0.7 → promote
-- ============================================================================


-- Cross-source canonical links. person + organization.
-- Forward-compat: PR-LEARN의 power_share·dormant_power_score 학습 결과는
-- learned_attributes_json에 박혀, schema migration 없이 evolution 가능.
CREATE TABLE IF NOT EXISTS actor_canonical_links (
    canonical_id            TEXT PRIMARY KEY,           -- e.g. 'person_canonical_정몽준_001' / 'org_chaebol_samsung'
    canonical_type          TEXT NOT NULL CHECK (canonical_type IN ('person', 'organization', 'party')),
    name                    TEXT NOT NULL,
    political_actor_ids     TEXT,                        -- JSON list — NEC·ASSEMBLY linked actor IDs
    economic_actor_ids      TEXT,                        -- JSON list — FTC·DART linked actor IDs
    political_roles         TEXT,                        -- JSON list
    political_parties       TEXT,                        -- JSON list
    economic_organizations  TEXT,                        -- JSON list (org names or canonical_ids)
    economic_roles          TEXT,                        -- JSON list
    rationale               TEXT,
    confidence              REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    state                   TEXT NOT NULL DEFAULT 'proposed' CHECK (
                              state IN ('proposed', 'active', 'deprecated', 'retired')
                            ),
    source                  TEXT NOT NULL,               -- 'yaml_seed' / 'fuzzy_match' / 'media_mention' /
                                                          --   'learned' / 'hand_correction' / 'llm_disambiguate'
    verification_count      INTEGER NOT NULL DEFAULT 0,
    last_verified_at        TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    rev_history_json        TEXT,                        -- [{ts, change_type, source, rationale}, ...]
    learned_attributes_json TEXT                         -- forward — PR-LEARN power_share / dormant 학습 결과
);

CREATE INDEX IF NOT EXISTS idx_canonical_name
    ON actor_canonical_links(name);
CREATE INDEX IF NOT EXISTS idx_canonical_type
    ON actor_canonical_links(canonical_type);
CREATE INDEX IF NOT EXISTS idx_canonical_state
    ON actor_canonical_links(state);
CREATE INDEX IF NOT EXISTS idx_canonical_source
    ON actor_canonical_links(source);
CREATE INDEX IF NOT EXISTS idx_canonical_confidence
    ON actor_canonical_links(confidence DESC);


-- chaebol alias dynamic state (org canonical resolution).
-- 에스케이 / SK / ìì¤ì¼ì´ → org_chaebol_sk
-- yaml_seed = git versioned bootstrap. llm_generated / discovered = self-evolving.
CREATE TABLE IF NOT EXISTS chaebol_aliases_state (
    alias               TEXT NOT NULL,                  -- input form (NFKC normalized)
    canonical_org_id    TEXT NOT NULL,                  -- e.g. 'org_chaebol_samsung'
    confidence          REAL,
    state               TEXT NOT NULL DEFAULT 'proposed' CHECK (
                          state IN ('proposed', 'active', 'deprecated')
                        ),
    source              TEXT NOT NULL,                  -- 'yaml_seed' / 'llm_generated' / 'discovered'
    last_seen_at        TEXT,
    seen_count          INTEGER NOT NULL DEFAULT 0,
    rev_history_json    TEXT,
    PRIMARY KEY (alias, canonical_org_id)
);

CREATE INDEX IF NOT EXISTS idx_chaebol_alias
    ON chaebol_aliases_state(alias);
CREATE INDEX IF NOT EXISTS idx_chaebol_canonical
    ON chaebol_aliases_state(canonical_org_id);
CREATE INDEX IF NOT EXISTS idx_chaebol_state
    ON chaebol_aliases_state(state);


-- DART executive trajectory (시간별 snapshot).
-- 매 보고서마다 ìì list 박힘. PRIMARY KEY (actor_id, rcept_no)로 시간 차원
-- 보존. main_career → cross-domain transition raw. mxmm_shrholdr_relate →
-- power_share prior signal (전문경영인 / owner family / 친족 etc).
CREATE TABLE IF NOT EXISTS dart_executive_state (
    actor_id              TEXT NOT NULL,                -- actors_dyn FK
    rcept_no              TEXT NOT NULL,                -- 보고서 번호 (시간 anchor)
    bsns_year             INTEGER,
    reprt_code            TEXT,
    corp_code             TEXT,
    corp_name             TEXT,
    nm                    TEXT,
    sexdstn               TEXT,
    birth_ym              TEXT,                          -- YYYYMM (Tier B matching key)
    ofcps                 TEXT,                          -- 직책
    rgist_exctv_at        TEXT,                          -- 사내 / 사외 / 감사
    fte_at                TEXT,                          -- 상근 / 비상근
    chrg_job              TEXT,                          -- 담당 업무
    main_career           TEXT,                          -- cross-domain transition trajectory
    mxmm_shrholdr_relate  TEXT,                          -- power_share prior signal
    hffc_pd               TEXT,                          -- 재직 기간
    tenure_end_on         TEXT,                          -- 임기 만료
    stlm_dt               TEXT,                          -- 결산일
    canonical_id          TEXT,                          -- actor_canonical_links FK
    ingested_at           TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (actor_id, rcept_no)
);

CREATE INDEX IF NOT EXISTS idx_dart_exec_actor
    ON dart_executive_state(actor_id);
CREATE INDEX IF NOT EXISTS idx_dart_exec_corp
    ON dart_executive_state(corp_code, bsns_year, reprt_code);
CREATE INDEX IF NOT EXISTS idx_dart_exec_birth_ym
    ON dart_executive_state(birth_ym, nm);    -- ★ Tier B matching path
CREATE INDEX IF NOT EXISTS idx_dart_exec_relate
    ON dart_executive_state(mxmm_shrholdr_relate);
CREATE INDEX IF NOT EXISTS idx_dart_exec_canonical
    ON dart_executive_state(canonical_id);


-- NEC candidate trajectory (매 선거별 snapshot).
-- 같은 person이 여러 선거에 출마하면 multiple rows. raw_record_json은
-- ingest 원본 보존 — PR-LEARN trajectory 학습 raw input.
CREATE TABLE IF NOT EXISTS nec_candidate_state (
    actor_id          TEXT NOT NULL,                    -- person canonical (기존 _canonical_id pattern)
    election_id       TEXT NOT NULL,                    -- 선거 식별 (sg_id + sg_typecode)
    huboid            TEXT,                              -- NEC 후보 ID (선거별 다름)
    sgg_name          TEXT,                              -- 선거구
    party_name        TEXT,                              -- 정당
    role              TEXT,                              -- 후보 / 당선 / 낙선 / 비례 / 사퇴
    political_tier    INTEGER CHECK (political_tier IS NULL OR political_tier BETWEEN 1 AND 5),
    raw_record_json   TEXT,                              -- NEC 원 record
    canonical_id      TEXT,                              -- actor_canonical_links FK
    ingested_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (actor_id, election_id)
);

CREATE INDEX IF NOT EXISTS idx_nec_state_actor
    ON nec_candidate_state(actor_id);
CREATE INDEX IF NOT EXISTS idx_nec_state_election
    ON nec_candidate_state(election_id);
CREATE INDEX IF NOT EXISTS idx_nec_state_party
    ON nec_candidate_state(party_name);
CREATE INDEX IF NOT EXISTS idx_nec_state_canonical
    ON nec_candidate_state(canonical_id);


-- FTC executive · owner trajectory (매년 지정 snapshot).
-- 매년 FTC 대규모기업집단 지정 시 ownership·executive structure가 바뀜.
-- canonical_org_id로 yaml seed → DB dynamic state 연결.
CREATE TABLE IF NOT EXISTS ftc_executive_state (
    actor_id          TEXT NOT NULL,
    designation_year  INTEGER NOT NULL,                  -- FTC 지정 연도
    unity_grup_code   TEXT,                              -- FTC 그룹 코드
    unity_grup_nm     TEXT,                              -- FTC 그룹명 (한글 음차)
    canonical_org_id  TEXT,                              -- chaebol_aliases_state → org_chaebol_xxx
    relation          TEXT,                              -- owner / executive / family
    economic_tier     INTEGER CHECK (economic_tier IS NULL OR economic_tier BETWEEN 1 AND 5),
    raw_record_json   TEXT,
    canonical_id      TEXT,                              -- actor_canonical_links FK (cross-sector)
    ingested_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (actor_id, designation_year)
);

CREATE INDEX IF NOT EXISTS idx_ftc_state_actor
    ON ftc_executive_state(actor_id);
CREATE INDEX IF NOT EXISTS idx_ftc_state_year
    ON ftc_executive_state(designation_year);
CREATE INDEX IF NOT EXISTS idx_ftc_state_grup
    ON ftc_executive_state(unity_grup_code);
CREATE INDEX IF NOT EXISTS idx_ftc_state_canonical_org
    ON ftc_executive_state(canonical_org_id);


-- chaebol tier ranking trajectory (매년 변동).
-- yaml seed = current year. ftc_designation = ingest 시 박힘.
-- PR-LEARN이 시간 따라 ranking 변동 학습 input.
CREATE TABLE IF NOT EXISTS chaebol_tier_state (
    canonical_org_id  TEXT NOT NULL,
    designation_year  INTEGER NOT NULL,
    tier              INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    rank_in_year      INTEGER,                           -- FTC 자산총액 순위 (있으면)
    source            TEXT NOT NULL,                     -- 'yaml_seed' / 'ftc_designation' / 'learned'
    rev_history_json  TEXT,
    PRIMARY KEY (canonical_org_id, designation_year)
);

CREATE INDEX IF NOT EXISTS idx_chaebol_tier_org
    ON chaebol_tier_state(canonical_org_id);
CREATE INDEX IF NOT EXISTS idx_chaebol_tier_year
    ON chaebol_tier_state(designation_year);


-- ASSEMBLY member trajectory (매 대수 snapshot).
-- C3에서 ALLNAMEMBER endpoint 검증 후 ingest 활성화. 현재는 schema만
-- forward-compat 박힘 — 한자·생일 박혀있다면 NEC ↔ ASSEMBLY Tier A pair 가능.
CREATE TABLE IF NOT EXISTS assembly_member_state (
    actor_id        TEXT NOT NULL,
    assembly_term   INTEGER NOT NULL,                    -- 대수 (e.g. 22)
    naas_cd         TEXT,                                 -- ASSEMBLY API 식별 (있으면)
    nm              TEXT,
    party_name      TEXT,
    elect_district  TEXT,                                 -- 선거구
    committee       TEXT,                                 -- 상임위
    role            TEXT,                                 -- 위원장 / 부위원장 / 간사 / 위원
    raw_record_json TEXT,
    canonical_id    TEXT,                                 -- actor_canonical_links FK
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (actor_id, assembly_term)
);

CREATE INDEX IF NOT EXISTS idx_assembly_state_actor
    ON assembly_member_state(actor_id);
CREATE INDEX IF NOT EXISTS idx_assembly_state_term
    ON assembly_member_state(assembly_term);
CREATE INDEX IF NOT EXISTS idx_assembly_state_party
    ON assembly_member_state(party_name);
CREATE INDEX IF NOT EXISTS idx_assembly_state_canonical
    ON assembly_member_state(canonical_id);


-- actors_dyn.canonical_org_id / canonical_party_id partial indexes —
-- created in _apply_idempotent_migrations (must run AFTER the ALTER ADD
-- COLUMN on existing v0 DBs; otherwise index creation fails on a
-- non-existent column during executescript).
