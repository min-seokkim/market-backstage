"""SQLite persistence — split into 4 sub-modules.

- schema.sql    : DDL
- core_io       : actors / states / events / decisions / market_pressure /
                  edges / decision_journal (Phase 3-5 sim tables)
- ingest_io     : documents / variables / raw_events / ingestion_runs /
                  actor_calibrations / actor_utterances / eum_traces
                  (Phase 1-2 ingestion)
- dyn_catalog_io: *_dyn dynamic catalog registry + extraction_runs
                  (self-evolving schema)

`import persistence as db` preserves the historical call-site semantics
(`db.insert_event(...)`, `db.fetch_documents_for_actor(...)`).
"""

from __future__ import annotations

from .core_io import (
    DB_PATH, DEMO_DB_PATH, connect, init,
    insert_actor, insert_edge, insert_state, insert_event,
    insert_decision, insert_market_pressure,
    insert_decision_journal_entry, update_decision_journal_outcome,
    fetch_decisions, fetch_market_pressure,
    summary,
    # PR-CONTRACT-v0
    insert_assessment, insert_target,
    insert_reality_gap, insert_future_gap,
    insert_prediction, update_prediction_outcome,
    query_assessments_by_period, query_predictions_pending,
    query_recent_high_priority_documents,
    query_recent_high_impact_events,
    query_actor_edge_strengths,
    insert_actor_decision_journal_entry,
)
from .ingest_io import (
    insert_document, insert_variable, insert_raw_event,
    begin_ingestion_run, finish_ingestion_run,
    insert_calibration, latest_calibration,
    fetch_documents_for_actor, fetch_variables_since,
    insert_actor_utterance, fetch_utterances_for_actor,
    insert_eum_trace, fetch_eum_trace_for_bill,
)
from .dyn_catalog_io import (
    seed_dynamic_catalog_from_static,
    fetch_active_event_templates, fetch_active_variable_specs,
    fetch_active_actors_dyn,
    fetch_proposed_rows, promote_row, deprecate_row,
    log_extraction_decision,
    begin_extraction_run, finish_extraction_run,
    link_extraction_doc, fetch_unextracted_docs,
    insert_event_template_proposal, insert_variable_spec_proposal,
    insert_actor_proposal, insert_causal_edge_proposal,
    # PR-Z
    upsert_actor_dyn, upsert_edge,
    # PR-Z2
    upsert_alias, resolve_canonical,
)

__all__ = [
    # core_io
    "DB_PATH", "DEMO_DB_PATH", "connect", "init",
    "insert_actor", "insert_edge", "insert_state", "insert_event",
    "insert_decision", "insert_market_pressure",
    "insert_decision_journal_entry", "update_decision_journal_outcome",
    "fetch_decisions", "fetch_market_pressure",
    "summary",
    # ingest_io
    "insert_document", "insert_variable", "insert_raw_event",
    "begin_ingestion_run", "finish_ingestion_run",
    "insert_calibration", "latest_calibration",
    "fetch_documents_for_actor", "fetch_variables_since",
    "insert_actor_utterance", "fetch_utterances_for_actor",
    "insert_eum_trace", "fetch_eum_trace_for_bill",
    # dyn_catalog_io
    "seed_dynamic_catalog_from_static",
    "fetch_active_event_templates", "fetch_active_variable_specs",
    "fetch_active_actors_dyn",
    "fetch_proposed_rows", "promote_row", "deprecate_row",
    "log_extraction_decision",
    "begin_extraction_run", "finish_extraction_run",
    "link_extraction_doc", "fetch_unextracted_docs",
    "insert_event_template_proposal", "insert_variable_spec_proposal",
    "insert_actor_proposal", "insert_causal_edge_proposal",
    # PR-Z
    "upsert_actor_dyn", "upsert_edge",
    # PR-Z2
    "upsert_alias", "resolve_canonical",
]
