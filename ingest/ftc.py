"""FTC OpenAPI adapter — Korean chaebol governance archive (PR4-FTC).

9 endpoints from data.go.kr/1130000, configurable backfill window
(default: most recent N=5 fiscal years).

  Tier-1 (presentnYear=YYYY):
    publicYmList                    — period catalog (currently unused;
                                       kept for future cursor refinement)
    appnGroupSttusList              — chaebol groups (~92/yr)
    affiliationCompSttusList        — subsidiary companies (~3,300/yr)
    executiveCompSttusList          — executives (~14,000/yr)
    stockholderCompSttusList        — shareholders (~8,000/yr)
    tyAssetsRentDelngDtlsList       — group-membership change events (~4,400/yr)
    financeCompSttusList            — financial statements (~3,300/yr)

  Tier-1.5 (presentnYm=YYYYMM, May only):
    sllInnerQotaList                — group internal-ownership snapshot
    grupRotatInvstmntList           — circular-ownership loops

  Tier-3 (broken backends — NOT called):
    holdingProgCompSttusList / innerQotaEqltrmCmprList /
    holdingGenFinCompSttusList

Cursor: skip if a prior successful (`error IS NULL`) ingestion_runs
row finished within the last 30 days. `--fresh` recreates the DB so
no row exists, and the full backfill runs.

This adapter writes ONLY to actors_dyn, edges_dyn, variables, and
raw_events — never to documents. Tier C seed person_ids
(`person_<name>_<group>`) are deterministic so cross-year re-fetches
collapse via INSERT OR REPLACE. Identity resolution against NEC/DART
is delegated to PR4-PERSON via persistence.upsert_alias.
"""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from . import (IngestedActor, IngestedEdge, IngestedRawEvent,
               IngestedVariable, IngestResult)
from persistence.tier import compute_economic_tier

load_dotenv()
log = logging.getLogger(__name__)


class FtcApiError(RuntimeError):
    """resultCode != '00' or HTTP >= 400. Caller decides whether to
    retry, fail-loud, or downgrade to empty for that endpoint."""


# ---- parsing helpers ------------------------------------------------------

def _parse_yyyymmdd(s):
    if not s or not isinstance(s, str) or len(s) < 8:
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]),
                        tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_int_or_none(s):
    if s is None or s == "":
        return None
    try:
        return int(float(str(s).replace(",", "")))
    except (ValueError, TypeError):
        return None


def _parse_float_or_none(s):
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _normalize(name):
    if not name:
        return ""
    return (name.replace(" ", "")
                .replace("(주)", "")
                .replace("(", "")
                .replace(")", "")
                .strip())


_ORG_MARKERS = ("(주)", "주식회사", "(재)", "재단", "법인", "협회", "조합",
                "유한회사", "공사", "공단", "센터", "연구원", "그룹",
                "홀딩스", "은행", "보험", "증권", "캐피탈", "중앙회")


def _is_likely_organization(name):
    if not name:
        return False
    return any(m in name for m in _ORG_MARKERS)


def _make_person_seed_id(name, group_name):
    return f"person_{_normalize(name)}_{_normalize(group_name)}"


_OWNERSHIP_CATEGORIES = ("self", "other", "family", "executive", "foundation")


def _classify_shareholder(se):
    if not se:
        return None
    if se == "자기주식":
        return "self"
    if se == "기타":
        return "other"
    if se == "친족":
        return "family"
    if "임원" in se:
        return "executive"
    if "비영리법인" in se or "재단" in se:
        return "foundation"
    return None


def _compute_ownership_summary(shareholders):
    summary = {c: 0.0 for c in _OWNERSHIP_CATEGORIES}
    for s in shareholders:
        rate = _parse_float_or_none(s.get("all_qota_rate")) or 0.0
        cat = _classify_shareholder(s.get("shrholdr_se", ""))
        if cat:
            summary[cat] += rate
    return summary


def _xml_to_dict(elem):
    out = {}
    for child in elem:
        text = (child.text or "").strip() if child.text else ""
        out[child.tag] = text
    return out


def _norm_keys(raw, mapping):
    return {snake: raw.get(camel, "") for camel, snake in mapping.items()}


# ---- per-endpoint XML field maps ------------------------------------------

GROUP_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "unityGrupCode": "unity_grup_code",
    "smerNm": "smer_nm",
    "repreCmpny": "repre_cmpny",
    "sumCmpnyCo": "sum_cmpny_co",
    "invstmntLmtt": "invstmnt_lmtt",
    "entrprsCl": "entrprs_cl",
}

COMPANY_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "entrprsNm": "entrprs_nm",
    "jurirno": "jurirno",
    "bizrno": "bizrno",
    "rprsntvNm": "rprsntv_nm",
    "fondDe": "fond_de",
    "grinil": "grinil",
    "indutyNm": "induty_nm",
    "indutyCode": "induty_code",
    "ordtmEmplyCo": "ordtm_emply_co",
}

EXECUTIVE_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "entrprsNm": "entrprs_nm",
    "jurirno": "jurirno",
    "bizrno": "bizrno",
    "rprsntvNm": "rprsntv_nm",
    "exctvNm": "exctv_nm",
    "ofcpsNm": "ofcps_nm",
    "smerRelateNm": "smer_relate_nm",
}

SHAREHOLDER_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "entrprsNm": "entrprs_nm",
    "jurirno": "jurirno",
    "bizrno": "bizrno",
    "rprsntvNm": "rprsntv_nm",
    "shrholdrNm": "shrholdr_nm",
    "shrholdrSe": "shrholdr_se",
    "posesnStockCo": "posesn_stock_co",
    "allQotaRate": "all_qota_rate",
    "onskCo": "onsk_co",
    "nrmltyQotaRate": "nrmlty_qota_rate",
    "prstkCo": "prstk_co",
    "priorQotaRate": "prior_qota_rate",
}

CHANGE_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "entrprsNm": "entrprs_nm",
    "jurirno": "jurirno",
    "psitnCmpnyChangeSeCode": "change_code",
    "exclDe": "excl_de",
    "exclPrvonshCode": "excl_prvonsh_code",
    "exclTrgetJobCode": "excl_trget_job_code",
    "postpneConfmDe": "postpne_confm_de",
    "postpneBeginDe": "postpne_begin_de",
    "postpneEndDe": "postpne_end_de",
    "postpneEndPrearngeDe": "postpne_end_prearnge_de",
    "postpnePrvonshTyCode": "postpne_prvonsh_ty_code",
}

FINANCE_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "entrprsNm": "entrprs_nm",
    "jurirno": "jurirno",
    "bizrno": "bizrno",
    "rprsntvNm": "rprsntv_nm",
    "beforeBsnsStacntDe": "before_bsns_stacnt_de",
    "stacntDudt": "stacnt_dudt",
    "assetsTotamt": "assets_totamt",
    "caplAmount": "capl_amount",
    "caplTotamt": "capl_totamt",
    "debtTotamt": "debt_totamt",
    "selngAmount": "selng_amount",
    "thstrmNtpfAmount": "thstrm_ntpf_amount",
    "entrprsOthbcDe": "entrprs_othbc_de",
}

INNER_QUOTA_FIELDS = {
    "appnGrupSeCode": "appn_grup_se_code",
    "unityGrupNm": "unity_grup_nm",
    "smerNm": "smer_nm",
    "prvYearCaplAmount": "prv_year_capl_amount",
    "curYearCaplAmount": "cur_year_capl_amount",
    "prvYearReltivCaplAmount": "prv_year_reltiv_capl",
    "curYearReltivCaplAmount": "cur_year_reltiv_capl",
    "prvYearExctvCaplAmount": "prv_year_exctv_capl",
    "curYearExctvCaplAmount": "cur_year_exctv_capl",
    "prvYearNfcrCaplAmount": "prv_year_nfcr_capl",
    "curYearNfcrCaplAmount": "cur_year_nfcr_capl",
}

CIRCULAR_FIELDS = {
    "unityGrupNm": "unity_grup_nm",
    "rotatInvstmntLoopCo": "rotat_loops",
}


CHANGE_CODE_TO_EVENT = {
    "0001": "subsidiary_addition",
    "0002": "subsidiary_removal",
    "0003": "subsidiary_postpone",
}


class FtcAdapter:
    name = "ftc"
    BASE_URL = "https://apis.data.go.kr/1130000"
    CURSOR_DAYS = 30

    def __init__(self, api_key=None, con=None, recent_years=5,
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
        delta_days = (datetime.now(timezone.utc) - last).days
        if delta_days < self.CURSOR_DAYS:
            log.info("ftc: skipping — last successful run %d일 전 "
                     "(< %d-day cursor; pass force_refresh=True or "
                     "--fresh to override)",
                     delta_days, self.CURSOR_DAYS)
            return True
        return False

    # ---- HTTP ----

    def _fetch_xml(self, endpoint, params):
        url = f"{self.BASE_URL}/{endpoint}/{endpoint}Api"
        full = {**params, "serviceKey": self.api_key}
        try:
            r = requests.get(url, params=full, timeout=30)
        except requests.exceptions.Timeout:
            log.warning("ftc %s: timeout (timeout=30s)", endpoint)
            raise
        self._calls_made += 1
        if r.status_code >= 400:
            log.warning("ftc %s: HTTP %d body[:200]=%s",
                        endpoint, r.status_code, r.text[:200])
            raise FtcApiError(f"{endpoint} HTTP {r.status_code}")
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            log.warning("ftc %s: xml parse failed body[:200]=%s",
                        endpoint, r.text[:200])
            raise
        rc = root.findtext(".//resultCode")
        if rc and rc != "00":
            log.warning("ftc %s: resultCode=%s msg=%s",
                        endpoint, rc, root.findtext(".//resultMsg"))
            raise FtcApiError(f"{endpoint} resultCode={rc}")
        return root

    def _fetch_paginated(self, endpoint, item_tag, base_params, field_map):
        all_items = []
        page = 1
        page_size = 100
        log.info("ftc %s: starting fetch — params=%s",
                 endpoint, {k: v for k, v in base_params.items()})
        while True:
            params = {**base_params, "pageNo": str(page),
                      "numOfRows": str(page_size)}
            root = self._fetch_xml(endpoint, params)
            total = int(root.findtext(".//totalCount") or "0")
            items = root.findall(f".//{item_tag}")
            for elem in items:
                raw = _xml_to_dict(elem)
                all_items.append(_norm_keys(raw, field_map))
            elapsed = int(time.monotonic() - self._t_start)
            log.info("ftc %s: page %d — got %d items "
                     "(cumulative=%d/%d, calls=%d, elapsed=%ds)",
                     endpoint, page, len(items), len(all_items), total,
                     self._calls_made, elapsed)
            if len(all_items) >= total or len(items) == 0:
                break
            prev_milestone = (len(all_items) - len(items)) // 1000
            cur_milestone = len(all_items) // 1000
            if cur_milestone > prev_milestone:
                log.info("ftc %s: milestone %d items, calls=%d, "
                         "elapsed=%ds",
                         endpoint, len(all_items), self._calls_made,
                         elapsed)
            page += 1
            time.sleep(0.1)
        log.info("ftc %s: done — %d items in %d pages, calls=%d, "
                 "elapsed=%ds",
                 endpoint, len(all_items), page, self._calls_made,
                 int(time.monotonic() - self._t_start))
        return all_items

    # ---- 9 endpoint methods ----

    def fetch_groups(self, year):
        items = self._fetch_paginated(
            "appnGroupSttusList", "appnGroupSttus",
            {"presentnYear": str(year)}, GROUP_FIELDS)
        for it in items:
            it["year"] = year
        return items

    def fetch_companies(self, year):
        items = self._fetch_paginated(
            "affiliationCompSttusList", "affiliationCompSttus",
            {"presentnYear": str(year)}, COMPANY_FIELDS)
        for it in items:
            it["year"] = year
        return items

    def fetch_executives(self, year):
        items = self._fetch_paginated(
            "executiveCompSttusList", "executiveCompSttus",
            {"presentnYear": str(year)}, EXECUTIVE_FIELDS)
        for it in items:
            it["year"] = year
        return items

    def fetch_shareholders(self, year):
        items = self._fetch_paginated(
            "stockholderCompSttusList", "stockholderCompSttus",
            {"presentnYear": str(year)}, SHAREHOLDER_FIELDS)
        for it in items:
            it["year"] = year
        return items

    def fetch_change_events(self, year):
        items = self._fetch_paginated(
            "tyAssetsRentDelngDtlsList", "tyAssetsRentDelngDtls",
            {"presentnYear": str(year)}, CHANGE_FIELDS)
        for it in items:
            it["year"] = year
            code = it.get("change_code") or ""
            it["event_type"] = CHANGE_CODE_TO_EVENT.get(
                code, "subsidiary_other")
            if code == "0002":
                it["event_date"] = it.get("excl_de")
                it["reason_code"] = it.get("excl_prvonsh_code")
            elif code == "0003":
                it["event_date"] = (it.get("postpne_begin_de")
                                    or it.get("postpne_confm_de"))
                it["reason_code"] = it.get("postpne_prvonsh_ty_code")
            else:
                # 0001 addition — FTC doesn't expose effective date,
                # use mid-May snapshot as proxy
                it["event_date"] = f"{year}0501"
                it["reason_code"] = None
        return items

    def fetch_finances(self, year):
        items = self._fetch_paginated(
            "financeCompSttusList", "financeCompSttus",
            {"presentnYear": str(year)}, FINANCE_FIELDS)
        numeric_keys = ("assets_totamt", "capl_amount", "capl_totamt",
                        "debt_totamt", "selng_amount",
                        "thstrm_ntpf_amount", "ordtm_emply_co")
        for it in items:
            it["year"] = year
            for k in numeric_keys:
                if k in it:
                    it[k] = _parse_int_or_none(it[k])
        return items

    def fetch_inner_quota(self, presentn_ym):
        items = self._fetch_paginated(
            "sllInnerQotaList", "sllInnerQota",
            {"presentnYm": str(presentn_ym)}, INNER_QUOTA_FIELDS)
        numeric_keys = ("prv_year_capl_amount", "cur_year_capl_amount",
                        "prv_year_reltiv_capl", "cur_year_reltiv_capl",
                        "prv_year_exctv_capl", "cur_year_exctv_capl",
                        "prv_year_nfcr_capl", "cur_year_nfcr_capl")
        for it in items:
            it["presentn_ym"] = presentn_ym
            for k in numeric_keys:
                if k in it:
                    it[k] = _parse_int_or_none(it[k])
        return items

    def fetch_circular_ownership(self, presentn_ym):
        items = self._fetch_paginated(
            "grupRotatInvstmntList", "grupRotatInvstmnt",
            {"presentnYm": str(presentn_ym)}, CIRCULAR_FIELDS)
        for it in items:
            it["presentn_ym"] = presentn_ym
            it["rotat_loops"] = _parse_int_or_none(it.get("rotat_loops"))
        return items

    # ---- builders ----

    def _build_actors(self, result, groups, companies, executives,
                      shareholders):
        # Cross-builder dedup. PR-Z's upsert_actor_dyn is INSERT OR REPLACE
        # so duplicates are tolerated, but we filter at the IngestResult
        # level to keep run_adapter's actor count meaningful and avoid
        # log spam.
        seen: set[str] = set()

        def add(a):
            if a.actor_id in seen:
                return
            seen.add(a.actor_id)
            result.actors.append(a)

        # 1) groups → organization
        for g in groups:
            if not g.get("unity_grup_code"):
                continue
            add(IngestedActor(
                actor_id=f"org_chaebol_group_{g['unity_grup_code']}",
                name=g.get("unity_grup_nm") or g["unity_grup_code"],
                type_="organization",
                category="reference_chaebol",
                identity={
                    "kind": "chaebol_group",
                    "owner_name": g.get("smer_nm"),
                    "represent_company": g.get("repre_cmpny"),
                    "subsidiary_count": _parse_int_or_none(
                        g.get("sum_cmpny_co")),
                    "investment_limit_class": g.get("invstmnt_lmtt"),
                    "year": g["year"],
                },
                proposal_source="ftc_appnGroup",
            ))

        # 2) owners — economic_tier from compute_economic_tier (5대 = 1)
        for g in groups:
            owner = g.get("smer_nm")
            if not owner or not g.get("unity_grup_code"):
                continue
            group_name = g["unity_grup_nm"]
            owner_econ_tier = compute_economic_tier(
                corp_position="owner",
                corp_group=group_name,
                year=g.get("year"),
            )
            if _is_likely_organization(owner):
                add(IngestedActor(
                    actor_id=f"org_owner_{_normalize(owner)}",
                    name=owner,
                    type_="organization",
                    category="reference_chaebol_owner_org",
                    identity={"kind": "chaebol_owner_org",
                              "group_name": group_name,
                              "group_code": g["unity_grup_code"],
                              "year": g["year"]},
                    proposal_source="ftc_appnGroup",
                    # Schema v2
                    economic_tier=owner_econ_tier,
                    peak_economic_tier=owner_econ_tier,
                    current_corp_position="owner",
                    current_corp_group=group_name,
                ))
            else:
                pid = _make_person_seed_id(owner, group_name)
                add(IngestedActor(
                    actor_id=pid, name=owner,
                    type_="person",
                    category="reference_chaebol_owner",
                    identity={"kind": "chaebol_owner",
                              "group_name": group_name,
                              "group_code": g["unity_grup_code"],
                              "year": g["year"]},
                    proposal_source="ftc_appnGroup",
                    # Schema v2
                    economic_tier=owner_econ_tier,
                    peak_economic_tier=owner_econ_tier,
                    current_corp_position="owner",
                    current_corp_group=group_name,
                ))

        # ownership lookup for company metadata
        sh_by_company_year = defaultdict(list)
        for s in shareholders:
            sh_by_company_year[(s.get("jurirno"), s.get("year"))].append(s)

        # 3) companies → organization (with ownership_summary)
        for c in companies:
            jurirno = c.get("jurirno")
            if not jurirno:
                continue
            ownership = _compute_ownership_summary(
                sh_by_company_year.get((jurirno, c["year"]), []))
            add(IngestedActor(
                actor_id=f"org_chaebol_company_{jurirno}",
                name=c.get("entrprs_nm") or jurirno,
                type_="organization",
                category="reference_chaebol_company",
                identity={
                    "kind": "chaebol_company",
                    "group_name": c.get("unity_grup_nm"),
                    "representative": c.get("rprsntv_nm"),
                    "founded_date": c.get("fond_de"),
                    "joined_group_date": c.get("grinil"),
                    "industry": c.get("induty_nm"),
                    "industry_code": c.get("induty_code"),
                    "employees": _parse_int_or_none(c.get("ordtm_emply_co")),
                    "ownership_summary": ownership,
                    "year": c["year"],
                },
                proposal_source="ftc_affiliation",
                # Schema v2
                external_id=jurirno,
                external_id_type="jurirno",
                current_corp_group=c.get("unity_grup_nm"),
            ))

        # 4) executives → role_instance + underlying person.
        # Map FTC ofcps_nm (e.g. "회장", "대표이사", "사외이사(해당없음)")
        # → tier compute key. Tier compute returns None for unmapped roles
        # (e.g. 사외이사, 감사) — we leave their tier blank by design.
        _OFCPS_TO_TIER_KEY = {
            "회장": "회장", "부회장": "부회장",
            "대표이사": "대표이사", "사장": "사장",
            "부사장": "부사장",
            "전무": "전무", "상무": "상무",
            "이사": "이사",
        }
        def _ofcps_tier_key(ofcps_nm: str | None) -> str | None:
            if not ofcps_nm:
                return None
            for key in _OFCPS_TO_TIER_KEY:
                if key in ofcps_nm:
                    return _OFCPS_TO_TIER_KEY[key]
            return None

        for e in executives:
            name = e.get("exctv_nm")
            jurirno = e.get("jurirno")
            if not name or not jurirno:
                continue
            pid = _make_person_seed_id(name, e.get("unity_grup_nm", ""))
            role_id = (f"role_executive_{jurirno}_"
                       f"{_normalize(name)}_"
                       f"{_normalize(e.get('ofcps_nm') or 'unknown')}_"
                       f"{e['year']}")
            tier_key = _ofcps_tier_key(e.get("ofcps_nm"))
            exec_econ_tier = (
                compute_economic_tier(
                    corp_position=tier_key,
                    corp_group=e.get("unity_grup_nm"),
                    year=e.get("year"),
                ) if tier_key else None
            )
            add(IngestedActor(
                actor_id=role_id,
                name=(f"{name} ({e.get('ofcps_nm') or '직위미상'} of "
                      f"{e.get('entrprs_nm') or '소속미상'})"),
                type_="role_instance",
                category="reference_chaebol_executive_role",
                identity={
                    "kind": "executive_role",
                    "person_seed": pid,
                    "company_name": e.get("entrprs_nm"),
                    "company_jurirno": jurirno,
                    "group_name": e.get("unity_grup_nm"),
                    "position": e.get("ofcps_nm"),
                    "relation_to_owner": e.get("smer_relate_nm"),
                    "year": e["year"],
                },
                proposal_source="ftc_executive",
                # Schema v2
                economic_tier=exec_econ_tier,
                peak_economic_tier=exec_econ_tier,
                current_corp_position=tier_key,
                current_corp_group=e.get("unity_grup_nm"),
            ))
            add(IngestedActor(
                actor_id=pid, name=name,
                type_="person",
                category="reference_chaebol_executive_person",
                identity={
                    "kind": "chaebol_executive_person",
                    "group_name": e.get("unity_grup_nm"),
                    "first_seen_role": e.get("ofcps_nm"),
                    "first_seen_company": e.get("entrprs_nm"),
                    "year": e["year"],
                },
                proposal_source="ftc_executive",
                # Schema v2 — underlying person carries best-seen tier as
                # peak. dedup at upsert layer means later (higher-tier)
                # appearances overwrite earlier rows.
                economic_tier=exec_econ_tier,
                peak_economic_tier=exec_econ_tier,
                current_corp_position=tier_key,
                current_corp_group=e.get("unity_grup_nm"),
            ))

        # 5) shareholders (skip 자기주식 / 기타 — those become company metadata only)
        for s in shareholders:
            name = s.get("shrholdr_nm")
            jurirno = s.get("jurirno")
            if not name or not jurirno:
                continue
            cat = _classify_shareholder(s.get("shrholdr_se", ""))
            if cat in (None, "self", "other"):
                continue
            is_org = (s.get("shrholdr_se") in ("비영리법인",)
                      or _is_likely_organization(name))
            if is_org:
                actor_id = f"org_shareholder_{_normalize(name)}"
                type_ = "organization"
            else:
                actor_id = _make_person_seed_id(
                    name, s.get("unity_grup_nm", ""))
                type_ = "person"
            add(IngestedActor(
                actor_id=actor_id, name=name, type_=type_,
                category=f"reference_shareholder_{cat}",
                identity={
                    "kind": f"shareholder_{s.get('shrholdr_se') or ''}",
                    "first_seen_company": s.get("entrprs_nm"),
                    "group_name": s.get("unity_grup_nm"),
                    "year": s["year"],
                },
                proposal_source="ftc_stockholder",
            ))

    def _build_edges(self, result, companies, executives, shareholders,
                     groups):
        # (group_name, year) → group_code
        group_lookup = {}
        for g in groups:
            if g.get("unity_grup_nm") and g.get("unity_grup_code"):
                group_lookup[(g["unity_grup_nm"], g["year"])] = (
                    g["unity_grup_code"])
        # (group_name, year) → owner name
        owner_lookup = {}
        for g in groups:
            if g.get("smer_nm") and g.get("unity_grup_nm"):
                owner_lookup[(g["unity_grup_nm"], g["year"])] = g["smer_nm"]

        # 1) company → group (subsidiary_of) — deterministic = 1.0/1.0
        for c in companies:
            jurirno = c.get("jurirno")
            if not jurirno:
                continue
            gcode = group_lookup.get((c.get("unity_grup_nm"), c["year"]))
            if not gcode:
                continue
            result.edges.append(IngestedEdge(
                src_actor_id=f"org_chaebol_company_{jurirno}",
                dst_actor_id=f"org_chaebol_group_{gcode}",
                edge_type="subsidiary_of",
                ts=datetime(c["year"], 5, 1, tzinfo=timezone.utc),
                metadata={"joined_date": c.get("grinil"),
                          "source": "ftc_affiliation"},
                strength=1.0, confidence=1.0,
            ))

        # 2) owner → group (owns) — deterministic
        for g in groups:
            owner = g.get("smer_nm")
            if not owner or not g.get("unity_grup_code"):
                continue
            if _is_likely_organization(owner):
                src = f"org_owner_{_normalize(owner)}"
            else:
                src = _make_person_seed_id(owner, g["unity_grup_nm"])
            result.edges.append(IngestedEdge(
                src_actor_id=src,
                dst_actor_id=f"org_chaebol_group_{g['unity_grup_code']}",
                edge_type="owns",
                ts=datetime(g["year"], 5, 1, tzinfo=timezone.utc),
                metadata={"role": "총수", "source": "ftc_appnGroup"},
                strength=1.0, confidence=1.0,
            ))

        # 3) executive → company (executive_of) — official appointment
        for e in executives:
            name = e.get("exctv_nm")
            jurirno = e.get("jurirno")
            if not name or not jurirno:
                continue
            pid = _make_person_seed_id(name, e.get("unity_grup_nm", ""))
            result.edges.append(IngestedEdge(
                src_actor_id=pid,
                dst_actor_id=f"org_chaebol_company_{jurirno}",
                edge_type="executive_of",
                ts=datetime(e["year"], 5, 1, tzinfo=timezone.utc),
                metadata={"position": e.get("ofcps_nm"),
                          "relation_to_owner": e.get("smer_relate_nm"),
                          "source": "ftc_executive"},
                strength=1.0, confidence=1.0,
            ))

        # 4 + 5) shareholder_of (strength = ownership_pct/100), family_relation
        for s in shareholders:
            name = s.get("shrholdr_nm")
            jurirno = s.get("jurirno")
            if not name or not jurirno:
                continue
            cat = _classify_shareholder(s.get("shrholdr_se", ""))
            if cat in (None, "self", "other"):
                continue
            is_org = (s.get("shrholdr_se") in ("비영리법인",)
                      or _is_likely_organization(name))
            if is_org:
                src = f"org_shareholder_{_normalize(name)}"
            else:
                src = _make_person_seed_id(
                    name, s.get("unity_grup_nm", ""))

            ownership_pct = _parse_float_or_none(s.get("all_qota_rate"))
            # ★ ownership stake naturally maps to relationship strength
            strength = (
                max(0.0, min(1.0, ownership_pct / 100.0))
                if ownership_pct is not None else None
            )
            result.edges.append(IngestedEdge(
                src_actor_id=src,
                dst_actor_id=f"org_chaebol_company_{jurirno}",
                edge_type="shareholder_of",
                ts=datetime(s["year"], 5, 1, tzinfo=timezone.utc),
                metadata={
                    "shareholder_class": s.get("shrholdr_se"),
                    "ownership_pct": ownership_pct,
                    "source": "ftc_stockholder",
                },
                strength=strength, confidence=1.0,
            ))

            if cat == "family":
                owner = owner_lookup.get(
                    (s.get("unity_grup_nm"), s["year"]))
                if owner and not _is_likely_organization(owner):
                    owner_id = _make_person_seed_id(
                        owner, s["unity_grup_nm"])
                    if owner_id != src:
                        result.edges.append(IngestedEdge(
                            src_actor_id=src,
                            dst_actor_id=owner_id,
                            edge_type="family_relation",
                            ts=datetime(s["year"], 5, 1,
                                        tzinfo=timezone.utc),
                            metadata={
                                "source": "ftc_stockholder_family"},
                            strength=1.0, confidence=1.0,
                        ))

    def _build_variables(self, result, groups, finances, executives,
                         shareholders, inner_quotas, circular):
        # group subsidiary count
        for g in groups:
            if not g.get("unity_grup_code"):
                continue
            sub = _parse_int_or_none(g.get("sum_cmpny_co"))
            if sub is None:
                continue
            result.variables.append(IngestedVariable(
                spec_id=f"chaebol_subsidiary_count_{g['unity_grup_code']}",
                value=float(sub),
                ts=datetime(g["year"], 5, 1, tzinfo=timezone.utc),
            ))

        # company financials + derived
        for f in finances:
            jurirno = f.get("jurirno")
            if not jurirno:
                continue
            ts = (_parse_yyyymmdd(f.get("stacnt_dudt"))
                  or datetime(f["year"], 5, 1, tzinfo=timezone.utc))
            for amt_field, suffix in (
                ("assets_totamt", "assets"),
                ("capl_totamt", "capital"),
                ("debt_totamt", "debt"),
                ("selng_amount", "revenue"),
                ("thstrm_ntpf_amount", "net_income"),
                ("ordtm_emply_co", "employee_count"),
            ):
                v = f.get(amt_field)
                if v is None:
                    continue
                result.variables.append(IngestedVariable(
                    spec_id=f"chaebol_company_{suffix}_{jurirno}",
                    value=float(v), ts=ts,
                ))
            capl = f.get("capl_totamt")
            assets = f.get("assets_totamt")
            ni = f.get("thstrm_ntpf_amount")
            debt = f.get("debt_totamt")
            if capl and debt is not None and capl != 0:
                result.variables.append(IngestedVariable(
                    spec_id=f"chaebol_company_debt_ratio_{jurirno}",
                    value=debt / capl, ts=ts,
                ))
            if assets and ni is not None and assets != 0:
                result.variables.append(IngestedVariable(
                    spec_id=f"chaebol_company_roa_{jurirno}",
                    value=ni / assets, ts=ts,
                ))
            if capl and ni is not None and capl != 0:
                result.variables.append(IngestedVariable(
                    spec_id=f"chaebol_company_roe_{jurirno}",
                    value=ni / capl, ts=ts,
                ))

        # executive ratios per (company, year)
        exec_by = defaultdict(list)
        for e in executives:
            exec_by[(e.get("jurirno"), e.get("year"))].append(e)
        for (jurirno, year), lst in exec_by.items():
            if not jurirno or not lst:
                continue
            ts = datetime(year, 5, 1, tzinfo=timezone.utc)
            total = len(lst)
            outside = sum(1 for x in lst
                          if "사외이사" in (x.get("ofcps_nm") or ""))
            family = sum(1 for x in lst
                         if x.get("smer_relate_nm") == "친족")
            result.variables.append(IngestedVariable(
                spec_id=f"chaebol_outside_director_ratio_{jurirno}",
                value=outside / total, ts=ts,
            ))
            result.variables.append(IngestedVariable(
                spec_id=f"chaebol_family_executive_ratio_{jurirno}",
                value=family / total, ts=ts,
            ))

        # ownership categories per (company, year)
        sh_by = defaultdict(list)
        for s in shareholders:
            sh_by[(s.get("jurirno"), s.get("year"))].append(s)
        for (jurirno, year), lst in sh_by.items():
            if not jurirno or not lst:
                continue
            ts = datetime(year, 5, 1, tzinfo=timezone.utc)
            summary = _compute_ownership_summary(lst)
            for cat, val in summary.items():
                if val > 0:
                    result.variables.append(IngestedVariable(
                        spec_id=f"chaebol_{cat}_ownership_{jurirno}",
                        value=val, ts=ts,
                    ))

        # inner quota — unit unknown until cross-ref task
        for q in inner_quotas:
            grp = q.get("unity_grup_nm")
            if not grp:
                continue
            try:
                year = int(str(q["presentn_ym"])[:4])
            except (KeyError, ValueError, TypeError):
                continue
            ts = datetime(year, 5, 1, tzinfo=timezone.utc)
            grp_seed = _normalize(grp)
            for amt, suffix in (
                ("cur_year_capl_amount", "capital_total"),
                ("cur_year_reltiv_capl", "family_capital"),
                ("cur_year_exctv_capl", "executive_capital"),
                ("cur_year_nfcr_capl", "foundation_capital"),
            ):
                v = q.get(amt)
                if v is None:
                    continue
                result.variables.append(IngestedVariable(
                    spec_id=f"chaebol_group_{suffix}_{grp_seed}",
                    value=float(v), ts=ts,
                ))

        # circular ownership loops
        for c in circular:
            grp = c.get("unity_grup_nm")
            if not grp:
                continue
            try:
                year = int(str(c["presentn_ym"])[:4])
            except (KeyError, ValueError, TypeError):
                continue
            loops = c.get("rotat_loops") or 0
            result.variables.append(IngestedVariable(
                spec_id=f"chaebol_circular_ownership_{_normalize(grp)}",
                value=float(loops),
                ts=datetime(year, 5, 1, tzinfo=timezone.utc),
            ))

    def _build_events(self, result, change_events, group_lookup):
        """Schema v2: primary_actor_id (the company being added/removed),
        actor_targets spreads to the parent group.

        Magnitudes are coarse seed values:
          subsidiary_addition / removal — 0.4 (structural change but not crisis)
          subsidiary_postpone           — 0.2 (administrative)
        """
        _impact_for_event = {
            "subsidiary_addition": 0.4,
            "subsidiary_removal": 0.4,
            "subsidiary_postpone": 0.2,
        }
        for evt in change_events:
            ts = _parse_yyyymmdd(evt.get("event_date"))
            if not ts:
                continue
            event_type = evt.get("event_type", "subsidiary_other")
            jurirno = evt.get("jurirno")
            company_actor = (
                f"org_chaebol_company_{jurirno}" if jurirno else None
            )
            gcode = group_lookup.get(
                (evt.get("unity_grup_nm"), evt.get("year"))
            )
            group_actor = (
                f"org_chaebol_group_{gcode}" if gcode else None
            )
            targets = []
            if group_actor:
                targets.append({
                    "actor_id": group_actor, "magnitude": 0.3,
                    "interpretation": event_type,
                })
            result.raw_events.append(IngestedRawEvent(
                template_id=event_type,
                ts=ts,
                payload={
                    "group_name": evt.get("unity_grup_nm"),
                    "company_name": evt.get("entrprs_nm"),
                    "jurirno": jurirno,
                    "change_code": evt.get("change_code"),
                    "reason_code": evt.get("reason_code"),
                    "year": evt.get("year"),
                    "source": "ftc_tyAssets",
                },
                # Schema v2
                primary_actor_id=company_actor,
                event_subtype=event_type,
                impact_magnitude=_impact_for_event.get(event_type, 0.3),
                actor_targets=targets if targets else None,
            ))

    # ---- top-level ----

    def fetch(self, since):
        result = IngestResult()
        if not self.api_key:
            log.warning("ftc: DATA_OR_KR_API_KEY not set; "
                        "returning empty result")
            return result
        if self._cursor_should_skip():
            return result

        self._t_start = time.monotonic()
        current_year = datetime.now(timezone.utc).year
        target_years = list(range(current_year - self.recent_years,
                                  current_year))
        target_yms = [f"{y}05" for y in target_years]
        log.info("ftc: starting backfill — years=%s, yms=%s",
                 target_years, target_yms)

        all_groups, all_companies = [], []
        all_executives, all_shareholders = [], []
        all_finances, all_change_events = [], []
        all_inner_quotas, all_circular = [], []

        for year in target_years:
            for label, fn, dest in (
                ("appnGroup", self.fetch_groups, all_groups),
                ("affiliation", self.fetch_companies, all_companies),
                ("executive", self.fetch_executives, all_executives),
                ("stockholder", self.fetch_shareholders, all_shareholders),
                ("tyAssets", self.fetch_change_events, all_change_events),
                ("finance", self.fetch_finances, all_finances),
            ):
                try:
                    dest.extend(fn(year))
                except FtcApiError as e:
                    log.warning("ftc: %s %d failed (%s)", label, year, e)
                except requests.exceptions.RequestException as e:
                    log.warning("ftc: %s %d network error (%s)",
                                label, year, e)

        for ym in target_yms:
            for label, fn, dest in (
                ("sllInnerQota", self.fetch_inner_quota, all_inner_quotas),
                ("grupRotat", self.fetch_circular_ownership, all_circular),
            ):
                try:
                    dest.extend(fn(ym))
                except FtcApiError as e:
                    log.warning("ftc: %s %s failed (%s)", label, ym, e)
                except requests.exceptions.RequestException as e:
                    log.warning("ftc: %s %s network error (%s)",
                                label, ym, e)

        # Build group lookup once — events also need it for primary_actor_id
        # resolution (avoid duplicating the table-walk in _build_events).
        group_lookup = {
            (g["unity_grup_nm"], g["year"]): g["unity_grup_code"]
            for g in all_groups
            if g.get("unity_grup_nm") and g.get("unity_grup_code")
        }

        self._build_actors(result, all_groups, all_companies,
                           all_executives, all_shareholders)
        self._build_edges(result, all_companies, all_executives,
                          all_shareholders, all_groups)
        self._build_variables(result, all_groups, all_finances,
                              all_executives, all_shareholders,
                              all_inner_quotas, all_circular)
        self._build_events(result, all_change_events, group_lookup)

        log.info("ftc: done — actors=%d, vars=%d, events=%d, edges=%d, "
                 "calls=%d, elapsed=%ds",
                 len(result.actors), len(result.variables),
                 len(result.raw_events), len(result.edges),
                 self._calls_made,
                 int(time.monotonic() - self._t_start))
        return result
