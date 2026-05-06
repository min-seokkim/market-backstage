"""FRED 매크로 데이터 어댑터.

FRED (https://fred.stlouisfed.org) 의 CSV 다운로드를 사용 — API 키 불요.
URL 패턴: https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID

variables.py 에서 source='macro' 인 모든 spec 의 source_params['series'] 를 fetch.
일자별 numeric 값을 IngestedVariable로.

요청 빈도 너무 잦으면 FRED가 throttle. MVP는 series 사이 1초 sleep.
실패해도 graceful: 빈 결과.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import IngestResult, IngestedVariable, run_adapter
from catalog.variables import VARIABLE_CATALOG

load_dotenv()
log = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


class MacroAdapter:
    name = "macro"

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        try:
            import requests
        except ImportError:
            log.warning("requests not installed; macro fetch skipped")
            return result

        macro_specs = [v for v in VARIABLE_CATALOG if v.source == "macro"
                       and v.source_params.get("provider") == "fred"]
        log.info("macro adapter: %d FRED series", len(macro_specs))

        for spec in macro_specs:
            series_id = spec.source_params.get("series")
            if not series_id:
                continue
            try:
                r = requests.get(FRED_CSV.format(sid=series_id),
                                 timeout=20,
                                 headers={"User-Agent": "MS_Investment/0.1"})
                r.raise_for_status()
            except Exception as e:
                log.warning("FRED fetch failed series=%s err=%s", series_id, e)
                time.sleep(1.0)
                continue

            reader = csv.reader(io.StringIO(r.text))
            try:
                header = next(reader)
            except StopIteration:
                continue
            # FRED CSV: ["DATE", series_id]
            date_idx = 0
            value_idx = 1
            for row in reader:
                if len(row) < 2:
                    continue
                date_s, val_s = row[date_idx].strip(), row[value_idx].strip()
                if val_s in ("", "."):
                    continue
                try:
                    ts = datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    val = float(val_s)
                except Exception:
                    continue
                if ts < since:
                    continue
                result.variables.append(IngestedVariable(
                    spec_id=spec.id, value=val, ts=ts, confidence=0.99,
                ))
            time.sleep(1.0)

        return result


def main():
    import persistence as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=30))
    con = _db.init()
    res = run_adapter(con, MacroAdapter(), since)
    print(f"macro: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
