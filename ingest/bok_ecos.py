"""한국은행 ECOS API 어댑터.

ECOS_API_KEY 가 환경변수에 있으면 작동, 없으면 stub (빈 결과 + 경고).
ECOS는 stat_code + item_code1 등으로 시계열 조회.
URL: https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/100/{stat_code}/D/{start}/{end}/{item_code1}

variables.py 에서 source='bok_ecos' 인 spec 의 source_params 사용.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import IngestResult, IngestedVariable, run_adapter
from variables import VARIABLE_CATALOG

load_dotenv()
log = logging.getLogger(__name__)

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

FREQ_CODE = {"daily": "D", "weekly": "D", "monthly": "M", "quarterly": "Q"}
DATE_FMT = {"D": "%Y%m%d", "M": "%Y%m", "Q": "%Y", "Y": "%Y"}


class BokEcosAdapter:
    name = "bok_ecos"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ECOS_API_KEY")

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        if not self.api_key:
            log.warning("ECOS_API_KEY not set; returning empty result")
            return result
        try:
            import requests
        except ImportError:
            log.warning("requests not installed; ecos fetch skipped")
            return result

        specs = [v for v in VARIABLE_CATALOG if v.source == "bok_ecos"]
        end = datetime.now(timezone.utc)
        for spec in specs:
            stat_code = spec.source_params.get("stat_code")
            item_code = spec.source_params.get("item_code1", "")
            freq_code = FREQ_CODE.get(spec.frequency, "M")
            fmt = DATE_FMT[freq_code]
            url = (f"{ECOS_BASE}/{self.api_key}/json/kr/1/500/"
                   f"{stat_code}/{freq_code}/{since.strftime(fmt)}/"
                   f"{end.strftime(fmt)}/{item_code}")
            try:
                r = requests.get(url, timeout=20)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("ECOS fetch failed spec=%s err=%s", spec.id, e)
                continue
            rows = (data.get("StatisticSearch") or {}).get("row") or []
            for row in rows:
                try:
                    val = float(row.get("DATA_VALUE", "nan"))
                    time_s = row.get("TIME", "")
                    if freq_code == "D":
                        ts = datetime.strptime(time_s, "%Y%m%d").replace(tzinfo=timezone.utc)
                    elif freq_code == "M":
                        ts = datetime.strptime(time_s, "%Y%m").replace(tzinfo=timezone.utc)
                    elif freq_code == "Q":
                        # ECOS 분기 표기: '2024Q1' 등 → 첫 달 1일로 정규화
                        y, q = time_s.split("Q")
                        ts = datetime(int(y), (int(q) - 1) * 3 + 1, 1, tzinfo=timezone.utc)
                    else:
                        ts = datetime.strptime(time_s, "%Y").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                result.variables.append(IngestedVariable(
                    spec_id=spec.id, value=val, ts=ts, confidence=0.99,
                ))
        return result


def main():
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=60))
    con = _db.init()
    res = run_adapter(con, BokEcosAdapter(), since)
    print(f"bok_ecos: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
