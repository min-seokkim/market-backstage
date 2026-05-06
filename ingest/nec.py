"""NEC OpenAPI adapter — Korean political archive (PR4-NEC).

National Election Commission (중앙선거관리위원회) data.go.kr/9760000.
38년 archive (1987~2025) + 2026 진행 중 9회 지선.

Tier A 강식별자 cross-election identity resolution: hanjaName + birthday
일치 = 같은 사람. PR-Z2의 person_aliases 첫 진짜 사용자 — confidence=1.0,
evidence_source='nec_hanja_dob_match'로 박는다.

Endpoints (모두 검증됨):
  CommonCodeService/getCommonSgCodeList      — 선거 ID list (totalCount=192)
  PofelcddInfoInqireService/getPofelcdd…     — 정식 후보자 (모든 선거)
  PofelcddInfoInqireService/getPoelpcdd…     — 예비후보자 (대선 INFO-03 fail tolerant)
  WinnerInfoInqireService2/getWinnerInfoInqire — 당선인 (100% Tier A)

호출 X — boundary:
  ElecPrmsInfoInqireService    선거공약    PR4-NEC.2 후속
  VoteXmntckInfoInqireService2 투·개표     PR4-NEC.2 후속
  PolplcInfoInqireService2     투표소     skip
  CountingSttnInfoInqireService 개표소    skip

Cursor: 마지막 successful run < 30일이면 silent skip; --fresh는 무시.

★ FTC와의 차이:
  - JSON resultType (FTC는 XML)
  - resultCode prefix "INFO-00" / "INFO-03"
  - upsert_alias 직접 호출 (FTC는 boundary로 안 함)
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from . import (IngestedActor, IngestedAlias, IngestedEdge, IngestedRawEvent,
               IngestedVariable, IngestResult)
from persistence.tier import compute_political_tier, update_tier_history

load_dotenv()
log = logging.getLogger(__name__)


class NecApiError(RuntimeError):
    """resultCode prefix not 'INFO-00' or HTTP >= 400. INFO-03 (no data) is
    NOT an error — _fetch_json returns None for that case so callers can
    fail-tolerant skip."""


# Forbidden services — boundary enforcement (PR4-NEC.2 / scrape PR 후속)
_FORBIDDEN_SERVICES = (
    "ElecPrmsInfoInqireService",
    "VoteXmntckInfoInqireService2",
    "PolplcInfoInqireService2",
    "CountingSttnInfoInqireService",
)


# ---- parsing helpers ------------------------------------------------------

def _parse_yyyymmdd(s):
    if s is None:
        return None
    s = str(s).strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]),
                        tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _safe_int(s):
    if s is None or s == "":
        return None
    try:
        return int(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _safe_float(s):
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _normalize(s):
    if not s:
        return ""
    return (str(s).replace(" ", "")
                  .replace("·", "")
                  .replace("ㆍ", "")
                  .replace("(", "")
                  .replace(")", "")
                  .strip())


def _now_utc():
    return datetime.now(timezone.utc)


# ---- canonical / alias id derivation --------------------------------------

def _canonical_key(rec):
    """De-dup key for canonical person lookup. Tier-prefixed so empty hanja
    doesn't collide with empty-hanja entries from different birthdays
    (and so missing-birthday entries don't collapse into one)."""
    hanja = (rec.get("hanja_name") or "").strip()
    dob = (rec.get("birthday") or "").strip()
    name = (rec.get("name") or "").strip()
    huboid = (rec.get("huboid") or "").strip()
    if hanja and dob:
        return ("hanja_dob", hanja, dob)
    if dob and name:
        return ("dob_name", _normalize(name), dob)
    return ("huboid", huboid)


def _canonical_id(rec):
    """Stable canonical_actor_id from the same key tuple as _canonical_key.
    Use Tier A path (hanja+dob) when available; fall back through dob,
    then huboid."""
    name_norm = _normalize(rec.get("name"))
    hanja = (rec.get("hanja_name") or "").strip()
    dob = (rec.get("birthday") or "").strip()
    huboid = (rec.get("huboid") or "").strip()
    if hanja and dob:
        return f"person_{name_norm}_{hanja}_{dob}"
    if dob:
        return f"person_{name_norm}_{dob}"
    return f"person_{name_norm}_huboid_{huboid}"


def _alias_id(rec):
    huboid = (rec.get("huboid") or "").strip()
    return f"person_huboid_{huboid}"


def _alias_evidence(rec):
    """Returns (confidence, evidence_source) for person_aliases entry."""
    if rec.get("hanja_name") and rec.get("birthday"):
        return (1.0, "nec_hanja_dob_match")
    if rec.get("birthday"):
        return (0.7, "nec_dob_match")
    return (0.3, "nec_name_only")


# ---- candidate status → edge_type / event template ------------------------

_STATUS_TO_EDGE = {
    "사퇴": "withdrew_from",
    "사망": "deceased_during_election",
    "등록무효": "invalidated",
}

_STATUS_TO_TEMPLATE = {
    "등록": "candidate_register",
    "사퇴": "candidate_withdraw",
    "사망": "candidate_deceased",
    "등록무효": "candidate_invalidated",
}


class NecAdapter:
    name = "nec"
    BASE_URL = "https://apis.data.go.kr/9760000"
    CURSOR_DAYS = 30

    def __init__(self, api_key=None, con=None, recent_years=None,
                 force_refresh=False):
        self.api_key = api_key or os.environ.get("DATA_OR_KR_API_KEY")
        self.con = con
        self.recent_years = recent_years
        self.force_refresh = force_refresh
        self._calls_made = 0
        self._t_start = None

    # ---- cursor ----

    def _cursor_should_skip(self):
        if self.force_refresh or self.con is None:
            return False
        row = self.con.execute(
            "SELECT finished_at FROM ingestion_runs "
            "WHERE source = ? AND finished_at IS NOT NULL "
            "  AND error IS NULL "
            "ORDER BY finished_at DESC LIMIT 1",
            (self.name,),
        ).fetchone()
        if not row or not row[0]:
            return False
        try:
            last = datetime.fromisoformat(row[0])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return False
        delta_days = (_now_utc() - last).days
        if delta_days < self.CURSOR_DAYS:
            log.info("nec: skipping — last successful run %d일 전 "
                     "(< %d-day cursor; pass force_refresh=True or "
                     "--fresh to override)",
                     delta_days, self.CURSOR_DAYS)
            return True
        return False

    # ---- HTTP ----

    def _fetch_json(self, service, operation, params):
        """GET + JSON parse. Returns:
          dict on INFO-00
          None on INFO-03 (no data — caller fail-tolerant skips)
          raises NecApiError on other resultCodes / HTTP errors.
        """
        if any(f in service for f in _FORBIDDEN_SERVICES):
            raise NecApiError(f"forbidden service: {service}")

        url = f"{self.BASE_URL}/{service}/{operation}"
        full = {**params, "serviceKey": self.api_key, "resultType": "json"}
        try:
            r = requests.get(url, params=full, timeout=30)
        except requests.exceptions.Timeout:
            log.warning("nec %s/%s: timeout (timeout=30s)",
                        service, operation)
            raise
        self._calls_made += 1
        if r.status_code >= 400:
            log.warning("nec %s/%s: HTTP %d body[:200]=%s",
                        service, operation, r.status_code, r.text[:200])
            raise NecApiError(f"{service}/{operation} HTTP {r.status_code}")
        try:
            data = r.json()
        except json.JSONDecodeError:
            log.warning("nec %s/%s: json parse failed body[:200]=%s",
                        service, operation, r.text[:200])
            raise

        header = data.get("response", {}).get("header", {})
        rc = header.get("resultCode", "")
        if rc == "INFO-03":
            return None
        if not rc.startswith("INFO-00"):
            log.warning("nec %s/%s: resultCode=%s msg=%s",
                        service, operation, rc, header.get("resultMsg"))
            raise NecApiError(f"{service}/{operation} resultCode={rc}")
        return data

    def _fetch_paginated(self, service, operation, base_params):
        all_items = []
        page = 1
        page_size = 100
        log.info("nec %s/%s: starting fetch — params=%s",
                 service, operation,
                 {k: v for k, v in base_params.items()})
        while True:
            params = {**base_params, "pageNo": str(page),
                      "numOfRows": str(page_size)}
            data = self._fetch_json(service, operation, params)
            if data is None:  # INFO-03 — fail tolerant
                log.info("nec %s/%s: INFO-03 (no data) — skip params=%s",
                         service, operation, base_params)
                return []
            body = data.get("response", {}).get("body", {})
            total = int(body.get("totalCount") or 0)
            wrapper = body.get("items") or {}
            if isinstance(wrapper, dict):
                items = wrapper.get("item", [])
            else:
                items = wrapper or []
            if isinstance(items, dict):
                items = [items]  # single-item sometimes returned as dict
            all_items.extend(items)

            elapsed = int(time.monotonic() - self._t_start)
            log.info("nec %s/%s: page %d — got %d items "
                     "(cumulative=%d/%d, calls=%d, elapsed=%ds)",
                     service, operation, page, len(items),
                     len(all_items), total, self._calls_made, elapsed)
            if len(all_items) >= total or len(items) == 0:
                break
            prev_milestone = (len(all_items) - len(items)) // 1000
            cur_milestone = len(all_items) // 1000
            if cur_milestone > prev_milestone:
                log.info("nec %s/%s: milestone %d items, calls=%d, "
                         "elapsed=%ds",
                         service, operation, len(all_items),
                         self._calls_made, elapsed)
            page += 1
            time.sleep(0.1)
        return all_items

    # ---- 4 endpoint methods ----

    def fetch_sg_codes(self):
        items = self._fetch_paginated(
            "CommonCodeService", "getCommonSgCodeList", {})
        return [self._parse_sg_code(i) for i in items]

    def fetch_winners(self, sg_id, sg_typecode):
        items = self._fetch_paginated(
            "WinnerInfoInqireService2", "getWinnerInfoInqire",
            {"sgId": sg_id, "sgTypecode": sg_typecode})
        return [self._parse_winner(i, sg_id, sg_typecode) for i in items]

    def fetch_official_candidates(self, sg_id, sg_typecode):
        items = self._fetch_paginated(
            "PofelcddInfoInqireService",
            "getPofelcddRegistSttusInfoInqire",
            {"sgId": sg_id, "sgTypecode": sg_typecode})
        return [self._parse_candidate(i, sg_id, sg_typecode, "official")
                for i in items]

    def fetch_preliminary_candidates(self, sg_id, sg_typecode):
        items = self._fetch_paginated(
            "PofelcddInfoInqireService",
            "getPoelpcddRegistSttusInfoInqire",
            {"sgId": sg_id, "sgTypecode": sg_typecode})
        return [self._parse_candidate(i, sg_id, sg_typecode, "preliminary")
                for i in items]

    # ---- parsers ----

    def _parse_sg_code(self, item):
        return {
            "num": _safe_int(item.get("num")),
            "sg_id": (item.get("sgId") or "").strip(),
            "sg_name": (item.get("sgName") or "").strip(),
            "sg_typecode": (item.get("sgTypecode") or "").strip(),
            "sg_votedate": (item.get("sgVotedate") or "").strip(),
        }

    def _parse_candidate(self, item, sg_id, sg_typecode, candidate_type):
        return {
            "candidate_type": candidate_type,
            "sg_id": sg_id,
            "sg_typecode": sg_typecode,
            "huboid": (item.get("huboid") or "").strip(),
            "name": (item.get("name") or "").strip(),
            "hanja_name": (item.get("hanjaName") or "").strip() or None,
            "gender": item.get("gender"),
            "birthday": (item.get("birthday") or "").strip() or None,
            "age": item.get("age"),
            "addr": item.get("addr"),
            "sgg_name": item.get("sggName"),
            "sd_name": item.get("sdName"),
            "wiw_name": item.get("wiwName"),
            "giho": item.get("giho"),
            "giho_sangse": item.get("gihoSangse"),
            "jd_name": (item.get("jdName") or "").strip() or None,
            "job_id": item.get("jobId"),
            "job": item.get("job"),
            "edu_id": item.get("eduId"),
            "edu": item.get("edu"),
            "career1": item.get("career1"),
            "career2": item.get("career2"),
            "regdate": (item.get("regdate") or "").strip() or None,
            "status": (item.get("status") or "").strip() or "등록",
        }

    def _parse_winner(self, item, sg_id, sg_typecode):
        rec = self._parse_candidate(item, sg_id, sg_typecode, "winner")
        rec["dugsu"] = _safe_int(item.get("dugsu"))
        rec["dugyul"] = _safe_float(item.get("dugyul"))
        rec["status"] = "당선"  # winner endpoint doesn't have status field
        return rec

    # ---- builders ----

    def _build_actors_and_aliases(self, result, sg_codes, all_records):
        """politician (canonical + per-election alias) + 정당 + election.

        Schema v2: two-pass. First pass collects per-alias political_tier
        and tracks the *peak* (highest = lowest number) per canonical_id.
        Second pass emits canonical actors carrying that peak. This
        captures cross-election trajectories — a 기초장 who runs for
        president gets canonical.peak_political_tier = 1.
        """
        sg_meta_by_key = {(s["sg_id"], s["sg_typecode"]): s for s in sg_codes}

        seen_actor_ids: set[str] = set()

        def add_actor(a):
            if a.actor_id in seen_actor_ids:
                return
            seen_actor_ids.add(a.actor_id)
            result.actors.append(a)

        # 1) 정당 actor (organization). Use first-seen election as identity
        #    anchor — historical 1987 entries get older anchors automatically.
        seen_party = set()
        for r in all_records:
            party = r.get("jd_name")
            if not party:
                continue
            party_id = f"party_{_normalize(party)}"
            if party_id in seen_party:
                continue
            seen_party.add(party_id)
            add_actor(IngestedActor(
                actor_id=party_id,
                name=party,
                type_="organization",
                category="reference_political_party",
                identity={
                    "kind": "political_party",
                    "first_seen_election": r["sg_id"],
                    "first_seen_typecode": r["sg_typecode"],
                },
                proposal_source="nec_party",
            ))

        # 2) election actor (event-as-organization)
        seen_election = set()
        for r in all_records:
            eid = f"election_{r['sg_id']}_{r['sg_typecode']}"
            if eid in seen_election:
                continue
            seen_election.add(eid)
            sg_meta = sg_meta_by_key.get((r["sg_id"], r["sg_typecode"]))
            add_actor(IngestedActor(
                actor_id=eid,
                name=(sg_meta["sg_name"] if sg_meta
                      else f"election_{r['sg_id']}_{r['sg_typecode']}"),
                type_="organization",
                category="reference_election_event",
                identity={
                    "kind": "election",
                    "sg_id": r["sg_id"],
                    "sg_typecode": r["sg_typecode"],
                    "sg_votedate": (sg_meta or {}).get("sg_votedate"),
                },
                proposal_source="nec_election",
            ))

        # 3) politician canonical + per-election alias (two-pass).
        canonical_seen: dict[tuple, str] = {}
        canonical_first_record: dict[str, dict] = {}  # canonical_id → first record
        canonical_peak: dict[str, int] = {}           # canonical_id → best (lowest) tier
        canonical_history_entries: dict[str, list] = {}
        alias_seen: set[str] = set()
        alias_records: list[tuple] = []  # (alias_id, canonical_id, record, tier)

        for r in all_records:
            if not r.get("name") or not r.get("huboid"):
                continue

            key = _canonical_key(r)
            if key in canonical_seen:
                canonical_id = canonical_seen[key]
            else:
                canonical_id = _canonical_id(r)
                canonical_seen[key] = canonical_id
                canonical_first_record[canonical_id] = r

            alias_id = _alias_id(r)
            if alias_id in alias_seen:
                continue
            alias_seen.add(alias_id)

            # ==== Schema v2: tier computation per appearance ====
            sg_typecode = r["sg_typecode"]
            party_name = r.get("jd_name")
            election_ts = r["sg_id"]  # YYYYMMDD; classification normalizes
            alias_political_tier = compute_political_tier(
                candidate_type=sg_typecode,
                party_name=party_name,
                election_ts=election_ts,
            )

            # Track peak for canonical (lower = higher tier)
            if alias_political_tier is not None:
                prev = canonical_peak.get(canonical_id)
                if prev is None or alias_political_tier < prev:
                    canonical_peak[canonical_id] = alias_political_tier
                # Stash an entry for tier_history (chronological appearance)
                canonical_history_entries.setdefault(canonical_id, []).append({
                    "ts": election_ts,
                    "political_tier": alias_political_tier,
                    "economic_tier": None,
                    "reason": f"candidate_in_{sg_typecode}",
                    "source": "nec_alias",
                })

            alias_records.append(
                (alias_id, canonical_id, r, alias_political_tier)
            )

            confidence, evidence = _alias_evidence(r)
            result.aliases.append(IngestedAlias(
                alias_actor_id=alias_id,
                canonical_actor_id=canonical_id,
                confidence=confidence,
                evidence_source=evidence,
                metadata={
                    "huboid": r["huboid"],
                    "sg_id": r["sg_id"],
                    "sg_typecode": r["sg_typecode"],
                    "candidate_type": r["candidate_type"],
                },
            ))

        # 3a) Emit canonical actors with peak_political_tier
        for canonical_id, first_rec in canonical_first_record.items():
            peak = canonical_peak.get(canonical_id)
            history = canonical_history_entries.get(canonical_id, [])
            history_json = (
                json.dumps(history, ensure_ascii=False)
                if history else None
            )
            add_actor(IngestedActor(
                actor_id=canonical_id,
                name=first_rec["name"],
                type_="person",
                category="reference_politician",
                identity={
                    "kind": "politician",
                    "hanjaName": first_rec.get("hanja_name"),
                    "birthday": first_rec.get("birthday"),
                    "gender": first_rec.get("gender"),
                    "first_seen_election": first_rec["sg_id"],
                    "first_seen_party": first_rec.get("jd_name"),
                },
                proposal_source="nec_canonical",
                hanja_name=first_rec.get("hanja_name"),
                birthday=first_rec.get("birthday"),
                peak_political_tier=peak,
                tier_history_json=history_json,
            ))

        # 3b) Emit alias actors with per-appearance political_tier
        for alias_id, canonical_id, rec, tier in alias_records:
            sg_typecode = rec["sg_typecode"]
            add_actor(IngestedActor(
                actor_id=alias_id,
                name=rec["name"],
                type_="role_instance",
                category=f"reference_politician_appearance_{rec['candidate_type']}",
                identity={
                    "kind": "politician_election_appearance",
                    "huboid": rec["huboid"],
                    "sg_id": rec["sg_id"],
                    "sg_typecode": rec["sg_typecode"],
                    "candidate_type": rec["candidate_type"],
                    "election_party": rec.get("jd_name"),
                    "career1": rec.get("career1"),
                    "career2": rec.get("career2"),
                    "edu": rec.get("edu"),
                    "job": rec.get("job"),
                    "addr": rec.get("addr"),
                    "giho": rec.get("giho"),
                    "regdate": rec.get("regdate"),
                    "status": rec.get("status"),
                    "dugsu": rec.get("dugsu"),
                    "dugyul": rec.get("dugyul"),
                },
                proposal_source=f"nec_alias_{rec['candidate_type']}",
                hanja_name=rec.get("hanja_name"),
                birthday=rec.get("birthday"),
                external_id=rec.get("huboid"),
                external_id_type="huboid",
                political_tier=tier,
                peak_political_tier=tier,
                registered_as_candidate=1,
                current_party_name=rec.get("jd_name"),
            ))

    def _build_edges(self, result, winners, official, preliminary):
        """7 edge types: won_election, candidate_in, preliminary_candidate_in,
        member_of_party, withdrew_from, deceased_during_election, invalidated.
        """
        # winners — NEC = deterministic so strength=1.0, confidence=1.0
        for w in winners:
            person_id = _canonical_id(w)
            election_id = f"election_{w['sg_id']}_{w['sg_typecode']}"
            ts = _parse_yyyymmdd(w["sg_id"]) or _now_utc()
            result.edges.append(IngestedEdge(
                src_actor_id=person_id, dst_actor_id=election_id,
                edge_type="won_election", ts=ts,
                metadata={
                    "huboid": w["huboid"],
                    "party": w.get("jd_name"),
                    "sgg": w.get("sgg_name"),
                    "giho": w.get("giho"),
                    "dugsu": w.get("dugsu"),
                    "dugyul": w.get("dugyul"),
                    "source": "nec_winner",
                },
                # Schema v2
                election_id=election_id,
                strength=1.0, confidence=1.0,
            ))
            if w.get("jd_name"):
                party_id = f"party_{_normalize(w['jd_name'])}"
                result.edges.append(IngestedEdge(
                    src_actor_id=person_id, dst_actor_id=party_id,
                    edge_type="member_of_party", ts=ts,
                    metadata={"election_context": w["sg_id"],
                              "source": "nec_winner"},
                    election_id=election_id,
                    strength=1.0, confidence=1.0,
                ))

        # official + preliminary candidates → status-driven edge_type
        for c in official + preliminary:
            person_id = _canonical_id(c)
            election_id = f"election_{c['sg_id']}_{c['sg_typecode']}"
            ts = (_parse_yyyymmdd(c.get("regdate"))
                  or _parse_yyyymmdd(c["sg_id"])
                  or _now_utc())
            status = c.get("status") or "등록"
            ctype = c["candidate_type"]
            edge_type = _STATUS_TO_EDGE.get(status)
            if edge_type is None:
                edge_type = ("preliminary_candidate_in"
                             if ctype == "preliminary"
                             else "candidate_in")
            # Withdrawn / 사망 / 등록무효 — relationship still recorded
            # but strength reflects the abridged outcome.
            edge_strength = 0.5 if status in ("사퇴", "사망", "등록무효") else 1.0
            result.edges.append(IngestedEdge(
                src_actor_id=person_id, dst_actor_id=election_id,
                edge_type=edge_type, ts=ts,
                metadata={
                    "huboid": c["huboid"],
                    "party": c.get("jd_name"),
                    "sgg": c.get("sgg_name"),
                    "giho": c.get("giho"),
                    "regdate": c.get("regdate"),
                    "status": status,
                    "candidate_type": ctype,
                    "source": f"nec_{ctype}_candidate",
                },
                election_id=election_id,
                strength=edge_strength, confidence=1.0,
            ))
            if c.get("jd_name"):
                party_id = f"party_{_normalize(c['jd_name'])}"
                result.edges.append(IngestedEdge(
                    src_actor_id=person_id, dst_actor_id=party_id,
                    edge_type="member_of_party", ts=ts,
                    metadata={
                        "election_context": c["sg_id"],
                        "source": f"nec_{ctype}_candidate",
                    },
                    election_id=election_id,
                    strength=edge_strength, confidence=1.0,
                ))

    def _build_variables(self, result, winners, official, preliminary):
        # 1) party seats per (election)
        seats = defaultdict(lambda: defaultdict(int))
        for w in winners:
            if w.get("jd_name"):
                seats[(w["sg_id"], w["sg_typecode"])][w["jd_name"]] += 1
        for (sg_id, sg_type), bucket in seats.items():
            ts = _parse_yyyymmdd(sg_id) or _now_utc()
            total = sum(bucket.values())
            for party, count in bucket.items():
                pid = f"party_{_normalize(party)}"
                result.variables.append(IngestedVariable(
                    spec_id=f"election_{sg_id}_{sg_type}_{pid}_seats",
                    value=float(count), ts=ts,
                ))
                if total > 0:
                    result.variables.append(IngestedVariable(
                        spec_id=f"election_{sg_id}_{sg_type}_{pid}_share",
                        value=count / total, ts=ts,
                    ))

        # 2) cumulative cross-election counts per canonical politician
        c_official = defaultdict(int)
        c_preliminary = defaultdict(int)
        c_winner = defaultdict(int)
        for c in official:
            c_official[_canonical_id(c)] += 1
        for c in preliminary:
            c_preliminary[_canonical_id(c)] += 1
        for w in winners:
            c_winner[_canonical_id(w)] += 1
        ts = _now_utc()
        for pid, n in c_official.items():
            result.variables.append(IngestedVariable(
                spec_id=f"politician_official_candidate_count_{pid}",
                value=float(n), ts=ts,
            ))
        for pid, n in c_winner.items():
            result.variables.append(IngestedVariable(
                spec_id=f"politician_winner_count_{pid}",
                value=float(n), ts=ts,
            ))
        for pid, n in c_preliminary.items():
            result.variables.append(IngestedVariable(
                spec_id=f"politician_preliminary_count_{pid}",
                value=float(n), ts=ts,
            ))

        # 3) per-election totals
        sg_off = defaultdict(int)
        sg_win = defaultdict(int)
        for c in official:
            sg_off[(c["sg_id"], c["sg_typecode"])] += 1
        for w in winners:
            sg_win[(w["sg_id"], w["sg_typecode"])] += 1
        for (sg_id, sg_type), n in sg_off.items():
            result.variables.append(IngestedVariable(
                spec_id=f"election_{sg_id}_{sg_type}_official_candidate_count",
                value=float(n),
                ts=_parse_yyyymmdd(sg_id) or _now_utc(),
            ))
        for (sg_id, sg_type), n in sg_win.items():
            result.variables.append(IngestedVariable(
                spec_id=f"election_{sg_id}_{sg_type}_winner_count",
                value=float(n),
                ts=_parse_yyyymmdd(sg_id) or _now_utc(),
            ))

    def _build_events(self, result, official, preliminary):
        """Lifecycle events for candidates with regdate (예비후보자 + 진행 중).

        Schema v2: each event carries primary_actor_id (the canonical
        politician), event_subtype, and impact_magnitude. actor_targets
        spreads the event impact to the party and election (downstream
        adapters that score market reactions read these). Magnitudes
        are seed estimates — coarse but better than 0.
        """
        # impact magnitude per status (event-level intensity)
        _impact_for_status = {
            "등록": 0.3,
            "사퇴": 0.5,
            "사망": 0.8,
            "등록무효": 0.6,
        }
        for c in preliminary + official:
            if not c.get("regdate"):
                continue
            ts = _parse_yyyymmdd(c["regdate"])
            if not ts:
                continue
            status = c.get("status") or "등록"
            template_id = _STATUS_TO_TEMPLATE.get(
                status, "candidate_status_unknown")
            primary_actor_id = _canonical_id(c)
            election_id = f"election_{c['sg_id']}_{c['sg_typecode']}"
            party_id = (
                f"party_{_normalize(c['jd_name'])}"
                if c.get("jd_name") else None
            )

            targets = [
                {"actor_id": election_id, "magnitude": 0.1,
                 "interpretation": f"election_{status}"},
            ]
            if party_id:
                targets.append({
                    "actor_id": party_id, "magnitude": 0.2,
                    "interpretation": f"party_member_{status}",
                })

            result.raw_events.append(IngestedRawEvent(
                template_id=template_id,
                ts=ts,
                payload={
                    "huboid": c["huboid"],
                    "name": c["name"],
                    "party": c.get("jd_name"),
                    "sg_id": c["sg_id"],
                    "sg_typecode": c["sg_typecode"],
                    "sgg_name": c.get("sgg_name"),
                    "status": status,
                    "candidate_type": c["candidate_type"],
                    "source": "nec_candidate_lifecycle",
                },
                # Schema v2
                primary_actor_id=primary_actor_id,
                event_subtype=template_id,
                impact_magnitude=_impact_for_status.get(status, 0.3),
                actor_targets=targets,
            ))

    # ---- top-level ----

    def fetch(self, since):
        result = IngestResult()
        if not self.api_key:
            log.warning("nec: DATA_OR_KR_API_KEY not set; "
                        "returning empty result")
            return result
        if self._cursor_should_skip():
            return result

        self._t_start = time.monotonic()

        log.info("nec: fetching sg_code list...")
        try:
            sg_codes = self.fetch_sg_codes()
        except (NecApiError, requests.exceptions.RequestException) as e:
            log.warning("nec: sg_code list failed (%s); aborting fetch", e)
            return result
        log.info("nec: %d sg_code entries (parent + specific)",
                 len(sg_codes))

        # parent (sgTypecode=0) is a cumulative summary row — skip
        target_sgs = [s for s in sg_codes if s["sg_typecode"] != "0"
                      and s["sg_id"] and s["sg_typecode"]]

        # optional recent_years window filter
        if self.recent_years:
            cutoff = datetime(_now_utc().year - self.recent_years, 1, 1,
                              tzinfo=timezone.utc)
            target_sgs = [
                s for s in target_sgs
                if (_parse_yyyymmdd(s["sg_votedate"]) or
                    _parse_yyyymmdd(s["sg_id"]) or cutoff) >= cutoff
            ]
        log.info("nec: %d target (sgId, sgTypecode) combinations",
                 len(target_sgs))

        all_winners, all_official, all_preliminary = [], [], []

        for idx, sg in enumerate(target_sgs):
            sg_label = (f"{sg['sg_id']}/{sg['sg_typecode']} "
                        f"({sg['sg_name'][:30]})")
            log.info("nec: [%d/%d] fetching %s",
                     idx + 1, len(target_sgs), sg_label)

            for label, fn, dest in (
                ("winner", self.fetch_winners, all_winners),
                ("official", self.fetch_official_candidates, all_official),
                ("preliminary", self.fetch_preliminary_candidates,
                 all_preliminary),
            ):
                try:
                    items = fn(sg["sg_id"], sg["sg_typecode"])
                    dest.extend(items)
                    log.info("nec: %s — %s=%d",
                             sg_label, label, len(items))
                except NecApiError as e:
                    log.warning("nec: %s %s failed (%s) — continuing",
                                label, sg_label, e)
                except requests.exceptions.RequestException as e:
                    log.warning("nec: %s %s network error (%s) — continuing",
                                label, sg_label, e)

        log.info("nec: fetched winners=%d, official=%d, preliminary=%d",
                 len(all_winners), len(all_official), len(all_preliminary))

        all_records = all_winners + all_official + all_preliminary
        self._build_actors_and_aliases(result, sg_codes, all_records)
        self._build_edges(result, all_winners, all_official, all_preliminary)
        self._build_variables(result, all_winners, all_official,
                              all_preliminary)
        self._build_events(result, all_official, all_preliminary)

        log.info("nec: done — actors=%d, vars=%d, events=%d, edges=%d, "
                 "aliases=%d, calls=%d, elapsed=%ds",
                 len(result.actors), len(result.variables),
                 len(result.raw_events), len(result.edges),
                 len(result.aliases),
                 self._calls_made,
                 int(time.monotonic() - self._t_start))
        return result
