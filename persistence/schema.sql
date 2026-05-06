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
    tier_history_json        TEXT
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
    affect_valence  REAL,                                     -- (greed - fear)
    affect_arousal  REAL,                                     -- urgency
    rationale       TEXT,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_actor_journal_actor
    ON actor_decision_journal(actor_id);
CREATE INDEX IF NOT EXISTS idx_actor_journal_tick
    ON actor_decision_journal(tick);
CREATE INDEX IF NOT EXISTS idx_actor_journal_event_type
    ON actor_decision_journal(event_type);
