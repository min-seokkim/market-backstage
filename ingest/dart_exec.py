"""DART 임원 ingest — exctvSttus.json endpoint.

For each corp · 보고서 시점:
  - 임원 list (이름·한자 X·birth_ym (YYYYMM)·직책·등록임원여부·근무
    형태·담당업무·main_career·최대주주관계·재직기간·임기만료)
  - dart_executive_state PRIMARY KEY (actor_id, rcept_no) → 시간별
    snapshot (매 보고서마다 row 추가; trajectory 보존).

Tier B matching key: nm + birth_ym (YYYYMM). main_career → cross-domain
transition raw. mxmm_shrholdr_relate → power_share prior signal.

actor_id namespace: person_dart_{nm}_{corp_code}_{birth_ym}.
canonical_org_id = resolve_org_canonical(corp_name) — chaebol_aliases_state
경유. NULL이면 actors_dyn.canonical_org_id도 NULL로 박힘 (C5에서 LLM
disambiguate 가능).

C3에서는 framework + 5대 chaebol 대표 corp_code 5개에 smoke. Full
backfill (전체 chaebol·multi-year)은 C4의 ingest 리팩터에서 박힘.

CLI:
  python -m ingest.dart_exec --corp-codes 00126380 --years 2024
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Iterable

import requests
from dotenv import load_dotenv

from persistence.canonical import resolve_org_canonical
from persistence.core_io import nfkc

load_dotenv()
log = logging.getLogger(__name__)

API_URL = "https://opendart.fss.or.kr/api/exctvSttus.json"

# 5대 chaebol 대표 corp_code (DART corpCode.xml에서 검증된 값).
# C4 retrofit이 chaebol_canonical.yaml의 representative_companies +
# DART corpCode.xml로 확장. C3은 smoke 용.
CORP_CODES_C3 = [
    ("00126380", "삼성전자",       "org_chaebol_samsung"),
    ("00164779", "SK하이닉스",     "org_chaebol_sk"),
    ("00164742", "현대자동차",     "org_chaebol_hyundai_motor"),
    ("00373220", "LG에너지솔루션", "org_chaebol_lg"),
    ("00293886", "롯데지주",       "org_chaebol_lotte"),
]

REPRT_CODES_DEFAULT = ("11013", "11014")  # 1분기 사업보고서·반기보고서


_BIRTH_YM_RE = re.compile(r"(\d{4})\D*0*(\d{1,2})")


def normalize_birth_ym(raw: str | None) -> str | None:
    """DART API returns birth_ym as "1962년 03월" (Korean) instead of
    YYYYMM. Tier B matching against NEC.birthday[:6] needs YYYYMM form,
    so normalize at ingest boundary. Returns None if raw is unparseable.

    "1962년 03월" → "196203"
    "1962-03"     → "196203"
    "196203"      → "196203" (passthrough)
    "" / None     → None
    """
    if not raw:
        return None
    m = _BIRTH_YM_RE.search(raw)
    if not m:
        return None
    y, mm = m.group(1), m.group(2).zfill(2)
    return f"{y}{mm}"


def _make_dart_actor_id(nm: str, corp_code: str,
                         birth_ym_normalized: str | None = None) -> str:
    """DART executive actor_id pattern.

    person_dart_{nm}_{corp_code}_{YYYYMM} — NEC와 다른 namespace.
    C5 fuzzy_match가 (nm, birth_ym) 기준 cross-source canonical을
    actor_canonical_links에 박는다.
    """
    suffix = birth_ym_normalized or "unknown"
    return f"person_dart_{nfkc(nm)}_{corp_code}_{suffix}"


def fetch_executive_list(corp_code: str, bsns_year: int, reprt_code: str,
                          api_key: str) -> list[dict]:
    """DART exctvSttus.json 호출. 빈 list / error → []."""
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }
    try:
        r = requests.get(API_URL, params=params, timeout=30)
    except Exception as e:
        log.warning("dart_exec transport error corp=%s yr=%d: %s",
                    corp_code, bsns_year, e)
        return []
    if r.status_code != 200:
        log.warning("dart_exec HTTP %d corp=%s yr=%d",
                    r.status_code, corp_code, bsns_year)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    status = data.get("status")
    if status == "013":  # 조회된 데이터 없음
        return []
    if status != "000":
        log.info("dart_exec status=%s corp=%s yr=%d msg=%s",
                 status, corp_code, bsns_year, data.get("message", ""))
        return []
    return data.get("list", []) or []


def ingest_dart_executives(
    con: sqlite3.Connection,
    corp_specs: Iterable[tuple[str, str, str]] = CORP_CODES_C3,
    years: list[int] | None = None,
    reprt_codes: tuple[str, ...] = REPRT_CODES_DEFAULT,
    daily_cap: int = 5000,
    sleep_between: float = 0.2,
) -> dict[str, int]:
    """For each (corp_code, corp_name, canonical_org_id) × year × reprt_code:
    fetch executive list → dart_executive_state row.

    Idempotent via PRIMARY KEY (actor_id, rcept_no): re-running on the
    same boundary is a no-op via INSERT OR IGNORE.

    Returns counts dict: {calls, executives_seen, rows_inserted, errors}.
    """
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        log.warning("DART_API_KEY not set — skipping dart_exec ingest")
        return {"calls": 0, "executives_seen": 0, "rows_inserted": 0,
                "errors": 0, "skipped": 1}

    if years is None:
        current_year = datetime.now(timezone.utc).year
        years = [current_year, current_year - 1]

    stats = {"calls": 0, "executives_seen": 0, "rows_inserted": 0,
             "errors": 0, "skipped": 0}

    for corp_code, corp_name_seed, canonical_org_id in corp_specs:
        for year in years:
            for reprt_code in reprt_codes:
                if stats["calls"] >= daily_cap:
                    log.info("dart_exec daily cap %d reached — stopping",
                             daily_cap)
                    return stats

                executives = fetch_executive_list(
                    corp_code, year, reprt_code, api_key,
                )
                stats["calls"] += 1
                stats["executives_seen"] += len(executives)

                for exec_info in executives:
                    rcept_no = (exec_info.get("rcept_no") or "").strip()
                    nm = nfkc((exec_info.get("nm") or "").strip())
                    if not nm or not rcept_no:
                        continue
                    birth_ym_raw = nfkc((exec_info.get("birth_ym") or "").strip())
                    birth_ym = normalize_birth_ym(birth_ym_raw)
                    actor_id = _make_dart_actor_id(nm, corp_code, birth_ym)
                    corp_name_actual = nfkc(
                        (exec_info.get("corp_name") or corp_name_seed).strip()
                    )
                    # Resolve canonical_org_id: prefer seed (well-known
                    # representative chaebol mapping); fall back to dynamic
                    # alias resolution for any subsidiary that drifted from
                    # the seed corp_name (chaebol_aliases_state catches it).
                    resolved = (
                        canonical_org_id
                        or resolve_org_canonical(con, corp_name_actual)
                    )

                    try:
                        cur = con.execute(
                            "INSERT OR IGNORE INTO dart_executive_state "
                            "(actor_id, rcept_no, bsns_year, reprt_code, "
                            " corp_code, corp_name, nm, sexdstn, birth_ym, "
                            " ofcps, rgist_exctv_at, fte_at, chrg_job, "
                            " main_career, mxmm_shrholdr_relate, hffc_pd, "
                            " tenure_end_on, stlm_dt, canonical_id) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                            "        ?, ?, ?, ?, ?, NULL)",
                            (
                                actor_id, rcept_no, year, reprt_code,
                                corp_code, corp_name_actual,
                                nm, exec_info.get("sexdstn"),
                                birth_ym,
                                nfkc((exec_info.get("ofcps") or "")),
                                exec_info.get("rgist_exctv_at"),
                                exec_info.get("fte_at"),
                                nfkc((exec_info.get("chrg_job") or "")),
                                nfkc((exec_info.get("main_career") or "")),
                                nfkc((exec_info.get("mxmm_shrholdr_relate") or "")),
                                exec_info.get("hffc_pd"),
                                exec_info.get("tenure_end_on"),
                                exec_info.get("stlm_dt"),
                            ),
                        )
                        if cur.rowcount > 0:
                            stats["rows_inserted"] += 1
                            # actors_dyn upsert is C4's job (full retrofit).
                            # C3 just populates the trajectory table.
                            _ = resolved  # canonical_org_id reserved for C4
                    except sqlite3.IntegrityError as e:
                        log.warning("dart_exec insert error: %s", e)
                        stats["errors"] += 1

                con.commit()
                if sleep_between > 0:
                    time.sleep(sleep_between)

    return stats


def _cli_main() -> int:
    from persistence import init as db_init
    from persistence.core_io import DB_PATH

    p = argparse.ArgumentParser(description="DART 임원 ingest (C3 smoke)")
    p.add_argument("--corp-codes", nargs="*", default=None,
                   help="explicit corp_code(s) — default: 5대 chaebol seed")
    p.add_argument("--years", type=int, nargs="*", default=None,
                   help="report years (default: current and prior year)")
    p.add_argument("--db-path", default=str(DB_PATH))
    p.add_argument("--daily-cap", type=int, default=5000)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.corp_codes:
        # CLI overrides — corp_name seed unknown, canonical_org_id unknown
        corp_specs = [(c, "", None) for c in args.corp_codes]
    else:
        corp_specs = CORP_CODES_C3

    con = db_init(path=args.db_path, fresh=False)
    try:
        stats = ingest_dart_executives(
            con, corp_specs=corp_specs, years=args.years,
            daily_cap=args.daily_cap,
        )
        print("dart_exec ingest results:")
        for k, v in stats.items():
            print(f"  {k:18s} {v:>5}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
