"""ASSEMBLY ALLNAMEMBER ingest — 의원 base trajectory.

Endpoint: https://open.assembly.go.kr/portal/openapi/ALLNAMEMBER
- 3,286 의원 (제9대 ~ 제22대 — 모든 시대 포함)
- 한자 (NAAS_CH_NM)·생일 (BIRDY_DT) 둘 다 박혀있음 → NEC ↔ ASSEMBLY
  Tier A (hanja + dob) pair 가능 (PR4-CANONICAL C3 directive 검증).

Per row response 핵심 fields:
  NAAS_CD: 의원 고유 ID
  NAAS_NM: 한글 이름
  NAAS_CH_NM: ★ 한자 이름 (Tier A key)
  BIRDY_DT: ★ 생일 YYYY-MM-DD (Tier A key)
  PLPT_NM: 정당 (slash-separated trajectory)
  ELECD_NM: 선거구 (slash-separated trajectory)
  BLNG_CMIT_NM: 소속 위원회 (slash-separated trajectory)
  GTELT_ERACO: 대수 list (e.g. "제9대, 제10대")
  RLCT_DIV_NM: 재선/초선

ASSEMBLY trajectory pattern: 한 사람이 여러 대 출마하면 GTELT_ERACO에
콤마로 묶여 박힘. assembly_member_state.PRIMARY KEY (actor_id,
assembly_term) → 대수마다 row 하나씩 expand.

actor_id namespace: person_assembly_{NAAS_CD}. C5 fuzzy match가
NEC ↔ ASSEMBLY canonical 매칭 박을 때 actor_canonical_links에 박힘.

CLI:
  python -m ingest.assembly_members [--page-size 1000] [--max-pages 5]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import time

import requests
from dotenv import load_dotenv

from persistence.core_io import nfkc

load_dotenv()
log = logging.getLogger(__name__)

API_URL = "https://open.assembly.go.kr/portal/openapi/ALLNAMEMBER"

# 제22대 → 22 (re.findall로 multi-term parse)
_TERM_PATTERN = re.compile(r"제\s*(\d+)\s*대")


def _parse_terms(gtelt_eraco: str | None) -> list[int]:
    """GTELT_ERACO 문자열에서 대수 list 추출.

    "제9대, 제10대" → [9, 10]
    "제22대"        → [22]
    None / empty   → []
    """
    if not gtelt_eraco:
        return []
    return [int(m) for m in _TERM_PATTERN.findall(gtelt_eraco)]


def _make_assembly_actor_id(naas_cd: str) -> str:
    return f"person_assembly_{nfkc(naas_cd)}"


def _last_segment(slash_separated: str | None) -> str | None:
    """ASSEMBLY API trajectory fields은 slash-separated. 마지막 segment =
    가장 최근 (current). 다른 대수는 raw_record_json에 박혀있음."""
    if not slash_separated:
        return None
    parts = [p.strip() for p in slash_separated.split("/") if p.strip()]
    return parts[-1] if parts else None


def fetch_page(api_key: str, p_index: int, p_size: int) -> tuple[list[dict], int]:
    """One page of ALLNAMEMBER. Returns (rows, total_count).
    rows = [] / total_count = 0 on any error."""
    params = {
        "KEY": api_key, "Type": "json",
        "pIndex": p_index, "pSize": p_size,
    }
    try:
        r = requests.get(API_URL, params=params, timeout=30)
    except Exception as e:
        log.warning("ALLNAMEMBER transport error pIndex=%d: %s", p_index, e)
        return [], 0
    if r.status_code != 200:
        log.warning("ALLNAMEMBER HTTP %d pIndex=%d", r.status_code, p_index)
        return [], 0
    try:
        data = r.json()
    except Exception:
        return [], 0
    envelope = data.get("ALLNAMEMBER")
    if not isinstance(envelope, list) or len(envelope) < 2:
        return [], 0
    head = envelope[0].get("head", []) if isinstance(envelope[0], dict) else []
    total = 0
    for h in head:
        if isinstance(h, dict) and "list_total_count" in h:
            total = int(h["list_total_count"])
            break
    rows = envelope[1].get("row", []) if isinstance(envelope[1], dict) else []
    return rows, total


def ingest_allnamember(
    con: sqlite3.Connection,
    page_size: int = 1000,
    max_pages: int | None = None,
    sleep_between: float = 0.3,
) -> dict[str, int]:
    """전체 ALLNAMEMBER fetch → assembly_member_state 박기.

    Per row → 한 사람의 대수마다 row expand. PRIMARY KEY (actor_id,
    assembly_term)으로 idempotent (re-run 안전).

    Returns counts: {pages, members_seen, rows_inserted, errors}.
    """
    api_key = os.environ.get("ASSEMBLY_API_KEY")
    if not api_key:
        log.warning("ASSEMBLY_API_KEY not set — skipping ALLNAMEMBER ingest")
        return {"pages": 0, "members_seen": 0, "rows_inserted": 0,
                "errors": 0, "skipped": 1}

    stats = {"pages": 0, "members_seen": 0, "rows_inserted": 0, "errors": 0,
             "skipped": 0}

    # Page 1 to get total count, then loop
    p_index = 1
    total_count: int | None = None
    while True:
        rows, total = fetch_page(api_key, p_index, page_size)
        stats["pages"] += 1
        if total_count is None and total > 0:
            total_count = total
            log.info("ALLNAMEMBER total members: %d", total_count)

        if not rows:
            break

        for row in rows:
            naas_cd = (row.get("NAAS_CD") or "").strip()
            if not naas_cd:
                continue
            actor_id = _make_assembly_actor_id(naas_cd)
            terms = _parse_terms(row.get("GTELT_ERACO"))
            if not terms:
                # 대수 정보 X — fallback: 단일 row at term=0 sentinel
                terms = [0]
            stats["members_seen"] += 1

            # Per-term row (PRIMARY KEY allows multiple terms per actor)
            for term in terms:
                try:
                    cur = con.execute(
                        "INSERT OR IGNORE INTO assembly_member_state "
                        "(actor_id, assembly_term, naas_cd, nm, party_name, "
                        " elect_district, committee, role, raw_record_json, "
                        " canonical_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                        (
                            actor_id, term, naas_cd,
                            nfkc((row.get("NAAS_NM") or "").strip()),
                            _last_segment(row.get("PLPT_NM")),
                            _last_segment(row.get("ELECD_NM")),
                            _last_segment(row.get("BLNG_CMIT_NM")),
                            (row.get("DTY_NM") or "").strip() or None,
                            json.dumps(row, ensure_ascii=False),
                        ),
                    )
                    if cur.rowcount > 0:
                        stats["rows_inserted"] += 1
                except sqlite3.IntegrityError as e:
                    log.warning("ALLNAMEMBER insert error %s: %s",
                                actor_id, e)
                    stats["errors"] += 1

        con.commit()
        p_index += 1
        if max_pages is not None and stats["pages"] >= max_pages:
            break
        # Pagination guard: stop when we've seen total_count members
        if total_count is not None and stats["members_seen"] >= total_count:
            break
        if sleep_between > 0:
            time.sleep(sleep_between)

    return stats


def _cli_main() -> int:
    from persistence import init as db_init
    from persistence.core_io import DB_PATH

    p = argparse.ArgumentParser(
        description="ASSEMBLY ALLNAMEMBER ingest (C3 — 의원 base trajectory)",
    )
    p.add_argument("--page-size", type=int, default=1000)
    p.add_argument("--max-pages", type=int, default=None,
                   help="cap pages for smoke runs")
    p.add_argument("--db-path", default=str(DB_PATH))
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    con = db_init(path=args.db_path, fresh=False)
    try:
        stats = ingest_allnamember(
            con, page_size=args.page_size, max_pages=args.max_pages,
        )
        print("ALLNAMEMBER ingest results:")
        for k, v in stats.items():
            print(f"  {k:18s} {v:>6}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
