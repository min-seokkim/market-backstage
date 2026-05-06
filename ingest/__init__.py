"""Ingestion package — Phase 1.

Each adapter implements the `Adapter` protocol: takes a `since` cutoff,
returns an `IngestResult` with documents + variable observations + raw
events. Adapters never write to DB themselves; `run_adapter()` here does
the persistence so all adapters share consistent ingestion-run logging
and de-duplication.

Adapters:
- `dart`         : DART OpenAPI (key required)
- `govt_press`   : 정부 부처 RSS (ministry-specific)
- `assembly`     : 국회 의안정보시스템 (HTML scrape)
- `news`         : 네이버 뉴스 검색 (HTML scrape)
- `macro`        : FRED CSV (no key)
- `bok_ecos`     : 한국은행 ECOS API (key required)
- `krx`          : KRX 일별 매매 (stub for now)

Missing API keys downgrade gracefully: warning logged, empty result.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import persistence as db


log = logging.getLogger(__name__)


# ---- Common types -----------------------------------------------------------


@dataclass
class Document:
    source: str                 # e.g. "dart" / "govt_press:mof" / "news"
    url: str
    title: str
    body: str
    published_at: datetime
    fetched_at: datetime
    metadata: dict = field(default_factory=dict)
    raw_hash: str = ""

    def __post_init__(self):
        if not self.raw_hash:
            h = hashlib.sha1()
            h.update(self.url.encode("utf-8"))
            h.update(b"\x00")
            h.update(self.title.encode("utf-8"))
            h.update(b"\x00")
            # only first 4KB of body — enough for dedup, not too expensive
            h.update(self.body[:4096].encode("utf-8"))
            self.raw_hash = h.hexdigest()


@dataclass
class IngestedVariable:
    spec_id: str               # VariableSpec.id
    value: Any                 # numeric / string / bool — JSON-serializable
    ts: datetime
    confidence: float = 1.0
    source_doc_idx: int | None = None   # index into IngestResult.documents (resolved at persist)


@dataclass
class IngestedRawEvent:
    template_id: str           # EventTemplate.id
    ts: datetime
    payload: dict
    severity: float | None = None
    source_doc_idx: int | None = None
    # ==== Schema v2 ====
    primary_actor_id: str | None = None
    event_subtype: str | None = None
    impact_magnitude: float | None = None    # 0~1 event-level intensity
    actor_targets: list | None = None        # [{actor_id, magnitude, interpretation?}, ...]


@dataclass
class IngestedActor:
    # Reference-Layer actor for bulk authoritative ingest (PR4-FTC). Maps
    # 1:1 onto persistence.upsert_actor_dyn — `identity` becomes
    # identity_json, `proposal_source` keeps the adapter-name + endpoint
    # tag (e.g. 'ftc_appnGroup') so deprecation/audit can trace origin.
    actor_id: str
    name: str
    type_: str | None = None              # person | organization | role_instance | unknown | None
    category: str | None = None
    role: str | None = None
    identity: dict = field(default_factory=dict)
    status: str = "active"                # FTC = authoritative, not "proposed"
    proposal_source: str | None = None
    sources: list = field(default_factory=list)
    # ==== Schema v2 hot fields ====
    hanja_name: str | None = None
    birthday: str | None = None             # YYYYMMDD
    external_id: str | None = None
    external_id_type: str | None = None     # 'huboid'|'jurirno'|'mona_cd'|'naas_cd'
    political_tier: int | None = None
    economic_tier: int | None = None
    peak_political_tier: int | None = None
    peak_economic_tier: int | None = None
    registered_as_candidate: int = 0
    current_governance_position: str | None = None
    current_party_position: str | None = None
    current_party_name: str | None = None
    current_corp_position: str | None = None
    current_corp_group: str | None = None
    tier_history_json: str | None = None


@dataclass
class IngestedEdge:
    # Actor-actor relationship for edges_dyn (PR-Z). `ts` is a python
    # datetime; run_adapter serializes to ISO8601 at persist time.
    src_actor_id: str
    dst_actor_id: str
    edge_type: str
    ts: datetime
    metadata: dict = field(default_factory=dict)
    # ==== Schema v2 ====
    election_id: str | None = None
    strength: float | None = None     # 0~1 relationship intensity
    confidence: float | None = None   # 0~1 observer confidence


@dataclass
class IngestedAlias:
    # alias→canonical mapping for person_aliases (PR-Z2). Used by PR4-NEC
    # to bulk-insert Tier A (hanjaName + birthday) cross-election identity
    # resolutions; also available to PR4-PERSON for cross-source resolves.
    # confidence ∈ [0.0, 1.0] enforced by db.upsert_alias.
    alias_actor_id: str
    canonical_actor_id: str
    confidence: float | None = None
    evidence_source: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class IngestResult:
    documents: list[Document] = field(default_factory=list)
    variables: list[IngestedVariable] = field(default_factory=list)
    raw_events: list[IngestedRawEvent] = field(default_factory=list)
    actors: list[IngestedActor] = field(default_factory=list)
    edges: list[IngestedEdge] = field(default_factory=list)
    aliases: list[IngestedAlias] = field(default_factory=list)


class Adapter(Protocol):
    name: str

    def fetch(self, since: datetime) -> IngestResult: ...


# ---- Driver -----------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class _AdapterWarningCapture(logging.Handler):
    # Captures WARNING+ records from `ingest.*` loggers during a single
    # adapter run. Adapters silently swallow API rejections (e.g. DART
    # status=100, ECOS spec failures, news fetch errors) by returning empty
    # results — those warnings are the *only* signal that something went
    # wrong, so we surface them on `ingestion_runs.error`.
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        self.records.append(f"{record.name}: {msg}")


def run_adapter(con, adapter: Adapter, since: datetime) -> dict[str, int]:
    """Fetch + persist; returns {docs, vars, events, dups}."""
    started_at = _iso(datetime.now(timezone.utc))
    t_start = time.monotonic()
    log.info("ingest %s: starting (since=%s)",
             adapter.name, since.date().isoformat())
    run_id = db.begin_ingestion_run(con, adapter.name, started_at)
    docs = vars_ = events = dups = 0
    actors_n = edges_n = aliases_n = 0
    err: str | None = None

    warn_capture = _AdapterWarningCapture()
    ingest_logger = logging.getLogger("ingest")
    ingest_logger.addHandler(warn_capture)

    try:
        try:
            result = adapter.fetch(since)

            # Insert documents and remember their assigned ids by index
            doc_ids: list[int | None] = []
            for d in result.documents:
                new_id = db.insert_document(
                    con, source=d.source, url=d.url, title=d.title, body=d.body,
                    published_at=_iso(d.published_at) if d.published_at else None,
                    fetched_at=_iso(d.fetched_at), raw_hash=d.raw_hash,
                    metadata=d.metadata,
                )
                if new_id is None:
                    dups += 1
                    # Look up existing id by hash so vars/events can still link
                    row = con.execute(
                        "SELECT id FROM documents WHERE raw_hash=?", (d.raw_hash,)
                    ).fetchone()
                    doc_ids.append(row[0] if row else None)
                else:
                    docs += 1
                    doc_ids.append(new_id)

            for v in result.variables:
                doc_id = doc_ids[v.source_doc_idx] if v.source_doc_idx is not None and v.source_doc_idx < len(doc_ids) else None
                db.insert_variable(con, spec_id=v.spec_id, ts=_iso(v.ts),
                                   value=v.value, confidence=v.confidence,
                                   source_doc_id=doc_id)
                vars_ += 1

            for ev in result.raw_events:
                doc_id = doc_ids[ev.source_doc_idx] if ev.source_doc_idx is not None and ev.source_doc_idx < len(doc_ids) else None
                db.insert_raw_event(con, template_id=ev.template_id,
                                    ts=_iso(ev.ts), payload=ev.payload,
                                    source_doc_id=doc_id, severity=ev.severity,
                                    primary_actor_id=ev.primary_actor_id,
                                    event_subtype=ev.event_subtype,
                                    impact_magnitude=ev.impact_magnitude,
                                    actor_targets=ev.actor_targets)
                events += 1

            # PR4-FTC: actors_dyn / edges_dyn bulk ingest. Adapters that
            # don't populate these keep the lists empty — no behavior
            # change for legacy adapters.
            for a in result.actors:
                db.upsert_actor_dyn(
                    con,
                    actor_id=a.actor_id, name=a.name,
                    type_=a.type_, category=a.category, role=a.role,
                    identity=a.identity or None,
                    sources=a.sources or None,
                    status=a.status,
                    proposal_source=a.proposal_source,
                    proposed_by=adapter.name,
                    # Schema v2 hot fields
                    hanja_name=a.hanja_name,
                    birthday=a.birthday,
                    external_id=a.external_id,
                    external_id_type=a.external_id_type,
                    political_tier=a.political_tier,
                    economic_tier=a.economic_tier,
                    peak_political_tier=a.peak_political_tier,
                    peak_economic_tier=a.peak_economic_tier,
                    registered_as_candidate=a.registered_as_candidate,
                    current_governance_position=a.current_governance_position,
                    current_party_position=a.current_party_position,
                    current_party_name=a.current_party_name,
                    current_corp_position=a.current_corp_position,
                    current_corp_group=a.current_corp_group,
                    tier_history_json=a.tier_history_json,
                )
                actors_n += 1

            for edge in result.edges:
                ts_iso = _iso(edge.ts) if isinstance(edge.ts, datetime) else str(edge.ts)
                db.upsert_edge(
                    con,
                    src_actor_id=edge.src_actor_id,
                    dst_actor_id=edge.dst_actor_id,
                    edge_type=edge.edge_type,
                    ts=ts_iso,
                    metadata=edge.metadata or None,
                    # Schema v2
                    election_id=edge.election_id,
                    strength=edge.strength,
                    confidence=edge.confidence,
                )
                edges_n += 1

            # PR4-NEC: person_aliases bulk ingest. PR-Z2 added the
            # (alias, canonical) schema; this loop is the first
            # adapter-driven population. Adapters that don't populate
            # aliases keep result.aliases empty.
            for al in result.aliases:
                db.upsert_alias(
                    con,
                    alias_actor_id=al.alias_actor_id,
                    canonical_actor_id=al.canonical_actor_id,
                    confidence=al.confidence,
                    evidence_source=al.evidence_source,
                    metadata=al.metadata or None,
                )
                aliases_n += 1
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.exception("adapter %s failed", adapter.name)
    finally:
        ingest_logger.removeHandler(warn_capture)

    if warn_capture.records:
        warn_str = " | ".join(warn_capture.records[:10])
        if len(warn_capture.records) > 10:
            warn_str += f" | ...(+{len(warn_capture.records) - 10} more)"
        err = f"{err} | warnings: {warn_str}" if err else f"warnings: {warn_str}"

    finished_at = _iso(datetime.now(timezone.utc))
    elapsed = int(time.monotonic() - t_start)
    db.finish_ingestion_run(con, run_id, finished_at=finished_at,
                            doc_count=docs, var_count=vars_,
                            event_count=events, error=err)
    con.commit()
    log.info("ingest %s: done — docs=%d, vars=%d, events=%d, "
             "actors=%d, edges=%d, aliases=%d, dups=%d, elapsed=%ds%s",
             adapter.name, docs, vars_, events,
             actors_n, edges_n, aliases_n, dups, elapsed,
             f", error={err[:100]}" if err else "")
    return {"docs": docs, "vars": vars_, "events": events,
            "actors": actors_n, "edges": edges_n,
            "aliases": aliases_n, "dups": dups,
            "error": err}
