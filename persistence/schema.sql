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
    metadata_json  TEXT
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
    rationale                TEXT
);

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
