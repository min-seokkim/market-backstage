"""국회 회의록 ingest.

bill 메타 (assembly.py) 와 별도로 *회의 자체*의 발언 trace를 수집한다.
회의록 1건이 50k~200k 토큰이라 indiscriminate fetch는 비용 폭발 — 4-stage
selective pipeline:

    Stage 1  metadata sweep   : 모든 회의 *목록*만 fetch (저렴)
    Stage 2  relevance score  : 위원회·안건 키워드·회의 종류·출석자로 본문 fetch 결정
    Stage 3  body fetch + chunk : speaker turn 단위로 분할
    Stage 4  chunk filter     : 키워드 + actor 매치로 LLM 입력 감축

이 모듈은 *Stage 1·2·3·4의 함수만* 제공한다. 실제 LLM stance/topic
추출은 별도 모듈(`extract.minutes_extractor`, 미구현)이 채운다.

데이터 source 우선순위:
1. `ASSEMBLY_MINUTES_API_KEY` — data.go.kr 회의록 OpenAPI
2. `ASSEMBLY_MINUTES_URL` — RSS/XML fallback
3. 둘 다 없으면 stub 반환 (개발 단계 기본)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger(__name__)


# ---- Stage 2: relevance scoring ---------------------------------------------

# 위원회별 reform regime 관련도. 더 광범한 sweep을 원하면 PRIORITY_COMMITTEES
# dict에 가중치 추가/조정.
PRIORITY_COMMITTEES: dict[str, float] = {
    "정무위원회": 1.0,            # FSC·금감원·공정위
    "법제사법위원회": 0.9,        # 상법 개정 관문
    "기획재정위원회": 0.85,       # 세제·국세청
    "산업통상자원중소벤처기업위원회": 0.7,
    "국토교통위원회": 0.5,
    "외교통일위원회": 0.4,
    "국방위원회": 0.4,
    "농림축산식품해양수산위원회": 0.3,
}

PRIORITY_MEETING_KIND: dict[str, float] = {
    "법안심사소위": 0.30,
    "전체회의": 0.30,
    "본회의": 0.20,
    "공청회": 0.15,
    "청문회": 0.15,
}


@dataclass
class MeetingMeta:
    """Stage 1 sweep 결과 — 회의 1건의 메타 정보."""

    meeting_id: str
    meeting_date: str            # YYYY-MM-DD
    committee: str
    kind: str                    # 본회의|법안심사소위|전체회의|공청회|...
    age: int                     # 22대 등
    session: str | None = None   # "1차", "2차" 등
    agenda_items: list[str] = field(default_factory=list)
    attendees: list[str] = field(default_factory=list)
    body_url: str | None = None  # 회의록 본문 URL (Stage 3에서 사용)


def _kw_match_count(haystack: str, kws: Iterable[str]) -> int:
    if not haystack or not kws:
        return 0
    return sum(1 for kw in kws if kw and kw in haystack)


def should_fetch_full_minutes(
    meta: MeetingMeta,
    *,
    active_event_keywords: Iterable[str] = (),
    catalog_actor_names: Iterable[str] = (),
    threshold: float = 0.7,
) -> tuple[bool, float]:
    """Stage 2: decide whether to spend tokens on body fetch.

    Returns (fetch_decision, score). Score is the sum of:
      - committee priority (0..1)
      - keyword matches in agenda items (capped 0.5)
      - meeting-kind bonus
      - attendee match to catalog actors (capped 0.3)
    """
    score = 0.0
    score += PRIORITY_COMMITTEES.get(meta.committee, 0.2)

    agenda_text = " ".join(meta.agenda_items or [])
    score += min(0.5, 0.1 * _kw_match_count(agenda_text, active_event_keywords))

    score += PRIORITY_MEETING_KIND.get(meta.kind, 0.0)

    actor_set = {n for n in catalog_actor_names if n}
    if actor_set and meta.attendees:
        hits = sum(1 for a in meta.attendees if any(name in a for name in actor_set))
        score += min(0.3, 0.05 * hits)

    return score >= threshold, round(score, 3)


def collect_active_event_keywords(con) -> list[str]:
    """Pull every 'keywords' list out of the active event templates' detection JSON."""
    import db as _db
    out: set[str] = set()
    for e in _db.fetch_active_event_templates(con):
        for kw in (e.get("detection") or {}).get("keywords") or []:
            if isinstance(kw, str) and kw.strip():
                out.add(kw.strip())
    return sorted(out)


def collect_catalog_actor_names(con) -> list[str]:
    """Pull canonical actor display names + identity keywords from the dynamic registry."""
    import db as _db
    out: set[str] = set()
    for a in _db.fetch_active_actors_dyn(con):
        if a.get("name"):
            out.add(a["name"])
        for kw in (a.get("identity") or {}).get("keywords") or []:
            if isinstance(kw, str) and kw.strip():
                out.add(kw.strip())
    return sorted(out)


# ---- Stage 3: chunking ------------------------------------------------------

# 회의록 speaker turn 시작 마커. 라인 시작의 ○ / ◯ / ◇ 뒤에 직책+이름이 옴.
# 직책+이름과 발언 본문은 보통 2칸 이상 공백 또는 괄호 시작으로 분리됨.
_TURN_START_RE = re.compile(r"^\s*[○◯◇]\s*", re.MULTILINE)
_SPEAKER_HEAD_RE = re.compile(
    r"(.{1,30}?)(?:\s{2,}|\(|\n|$)", re.DOTALL,
)


@dataclass
class MinutesChunk:
    speaker: str
    content: str
    char_offset: int = 0


def chunk_minutes_by_speaker_turn(body: str) -> list[MinutesChunk]:
    """Split a 회의록 body into per-speaker turns.

    Two-step parse: (1) split the document on speaker-bullet markers
    (○ / ◯ / ◇); (2) within each resulting turn, peel off the speaker
    head (직책+이름, ≤30 chars, terminated by 2-space gap, paren, newline,
    or buffer end) from the spoken content.
    Returns chunks in document order. Empty chunks (no content) are dropped.
    """
    if not body:
        return []
    starts = list(_TURN_START_RE.finditer(body))
    if not starts:
        return [MinutesChunk(speaker="", content=body.strip())]

    chunks: list[MinutesChunk] = []
    for i, m in enumerate(starts):
        turn_start = m.end()
        turn_end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
        turn_text = body[turn_start:turn_end].strip()
        if not turn_text:
            continue
        head = _SPEAKER_HEAD_RE.match(turn_text)
        if head:
            speaker = head.group(1).strip()
            content = turn_text[head.end():].strip()
        else:
            speaker = ""
            content = turn_text
        if speaker or content:
            chunks.append(MinutesChunk(speaker=speaker, content=content,
                                       char_offset=m.start()))
    return chunks


# ---- Stage 4: chunk relevance ----------------------------------------------

def score_chunk_relevance(
    chunk: MinutesChunk,
    *,
    active_event_keywords: Iterable[str] = (),
    catalog_actor_names: Iterable[str] = (),
) -> float:
    """Score a chunk's relevance for forwarding to the LLM extractor.

    Heuristic: keyword count in body + 1.5× boost if the speaker matches a
    catalog actor (their voice carries proportionally more signal weight).
    """
    if not chunk.content:
        return 0.0
    kw_score = min(1.0, 0.1 * _kw_match_count(chunk.content, active_event_keywords))
    speaker_match = any(
        name and name in chunk.speaker for name in catalog_actor_names
    )
    return kw_score * (1.5 if speaker_match else 1.0)


def filter_relevant_chunks(
    chunks: list[MinutesChunk],
    *,
    active_event_keywords: Iterable[str] = (),
    catalog_actor_names: Iterable[str] = (),
    threshold: float = 0.2,
) -> list[tuple[MinutesChunk, float]]:
    """Return [(chunk, score), ...] ordered by score desc, threshold-filtered."""
    scored = [
        (c, score_chunk_relevance(
            c,
            active_event_keywords=active_event_keywords,
            catalog_actor_names=catalog_actor_names,
        ))
        for c in chunks
    ]
    scored = [(c, s) for c, s in scored if s >= threshold]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


# ---- Speaker → catalog actor matcher ---------------------------------------

def match_speaker_to_actor(
    raw_speaker: str,
    catalog_actors: list[dict[str, Any]],
) -> str | None:
    """Try to map a 회의록 speaker label onto a known catalog actor id.

    Conservative: returns an actor id only when the speaker string contains
    one of the actor's identity keywords or display name. Returns None on
    ambiguity (>1 hit) or no hit.
    """
    if not raw_speaker:
        return None
    hits: list[str] = []
    for a in catalog_actors:
        candidates = [a.get("name", "")]
        candidates.extend((a.get("identity") or {}).get("keywords") or [])
        for cand in candidates:
            if cand and cand in raw_speaker:
                hits.append(a["id"])
                break
    if len(hits) == 1:
        return hits[0]
    return None


# ---- Stage 1 stub -----------------------------------------------------------

class AssemblyMinutesAdapter:
    """Stage 1: metadata sweep.

    Real OpenAPI wiring is left for Sprint 1 — operator plugs in via env var
    `ASSEMBLY_MINUTES_API_KEY`. This adapter exposes the *contract* — call
    `fetch_meeting_metas(since)` to get a list[MeetingMeta]; call
    `fetch_meeting_body(meta)` only after relevance gating.
    """

    name = "assembly_minutes"

    def __init__(self, *, age: int = 22):
        self.age = age

    def fetch_meeting_metas(self, since: datetime) -> list[MeetingMeta]:  # pragma: no cover
        api_key = os.environ.get("ASSEMBLY_MINUTES_API_KEY")
        if not api_key:
            log.info("assembly_minutes: no ASSEMBLY_MINUTES_API_KEY — stub.")
            return []
        # TODO Sprint 1: hit data.go.kr endpoint (data/3057576).
        return []

    def fetch_meeting_body(self, meta: MeetingMeta) -> str:  # pragma: no cover
        if not meta.body_url:
            return ""
        # TODO Sprint 1: requests.get(meta.body_url); strip nav HTML; return text.
        return ""
