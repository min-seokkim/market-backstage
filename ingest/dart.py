"""DART OpenAPI 어댑터.

OpenDART (https://opendart.fss.or.kr) 의 무료 API 사용. 환경변수 `DART_API_KEY`
가 있으면 최신 공시 목록 + 사업보고서·주요사항보고서·지분공시를 fetch.
없으면 stub: 경고 로그 + 빈 IngestResult 반환.

MVP에서는:
- `list.json` 으로 최근 N일 공시 목록
- 공시 제목 + 보고서 요약(있다면)을 Document 로 저장
- 카탈로그 EVENT_TEMPLATE 의 detection.filing_keywords 매칭 시 raw_event 생성
- 카탈로그 VARIABLE_SPEC 중 `source=='dart'` 인 변수의 source_params['group']
  과 회사명이 매핑되면 IngestedVariable 생성 (경량 — 정확한 추출은
  calibration·signals 단계에서 LLM이 보강)

CLI: `python -m ingest.dart --since 2026-04-28`
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import Adapter, Document, IngestResult, IngestedRawEvent, run_adapter
from catalog.events import EVENT_CATALOG

load_dotenv()
log = logging.getLogger(__name__)

API_BASE = "https://opendart.fss.or.kr/api/list.json"

# 5대 + 한진·CJ·신세계 그룹 핵심 회사명(부분 매칭) — DART는 회사 단위, 그룹
# 단위로 묶기엔 corp_code 가 더 정확하지만 MVP는 이름 매칭으로 충분.
GROUP_NAME_MAP: dict[str, list[str]] = {
    "samsung": ["삼성전자", "삼성SDI", "삼성바이오로직스", "삼성생명", "삼성물산", "호텔신라"],
    "sk":      ["SK하이닉스", "SK이노베이션", "SK텔레콤", "SK스퀘어", "SK"],
    "hyundai": ["현대차", "기아", "현대모비스", "현대제철", "현대글로비스"],
    "lg":      ["LG에너지솔루션", "LG화학", "LG전자", "LG디스플레이", "LG"],
    "lotte":   ["롯데지주", "롯데케미칼", "롯데쇼핑", "롯데웰푸드"],
    "hanjin":  ["한진칼", "대한항공"],
    "cj":      ["CJ제일제당", "CJ ENM", "CJ"],
    "shinsegae": ["신세계", "이마트"],
}


class DartAdapter:
    name = "dart"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DART_API_KEY")

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        if not self.api_key:
            log.warning("DART_API_KEY not set; returning empty result")
            return result

        try:
            import requests
        except ImportError:
            log.warning("requests not installed; returning empty result")
            return result

        bgn = since.strftime("%Y%m%d")
        end = datetime.now(timezone.utc).strftime("%Y%m%d")

        params = {
            "crtfc_key": self.api_key,
            "bgn_de": bgn,
            "end_de": end,
            "page_count": 100,
        }
        try:
            r = requests.get(API_BASE, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("DART fetch failed: %s", e)
            return result

        if data.get("status") not in ("000", "013"):  # 013 = no data
            log.warning("DART status=%s message=%s",
                        data.get("status"), data.get("message"))
            return result

        items = data.get("list") or []
        for it in items:
            corp_name = it.get("corp_name", "")
            report_nm = it.get("report_nm", "")
            rcept_dt = it.get("rcept_dt", "")
            rcept_no = it.get("rcept_no", "")
            try:
                pub_dt = datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            doc = Document(
                source="dart", url=url, title=f"{corp_name} — {report_nm}",
                body=report_nm,  # 본문은 별도 페이지 — MVP에서는 제목만
                published_at=pub_dt,
                fetched_at=datetime.now(timezone.utc),
                metadata={"corp_name": corp_name, "rcept_no": rcept_no,
                          "stock_code": it.get("stock_code", "")},
            )
            doc_idx = len(result.documents)
            result.documents.append(doc)

            # Detect raw events by keyword in report name
            for tmpl in EVENT_CATALOG:
                if tmpl.source != "dart":
                    continue
                kws = (tmpl.detection or {}).get("filing_keywords") or []
                if any(kw in report_nm for kw in kws):
                    # Identify group
                    group = None
                    for g, names in GROUP_NAME_MAP.items():
                        if any(n in corp_name for n in names):
                            group = g
                            break
                    result.raw_events.append(IngestedRawEvent(
                        template_id=tmpl.id, ts=pub_dt,
                        payload={"corp_name": corp_name, "report": report_nm,
                                 "group": group, "rcept_no": rcept_no},
                        severity=tmpl.typical_severity,
                        source_doc_idx=doc_idx,
                    ))

        return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None,
                   help="ISO date (default: 7 days ago)")
    p.add_argument("--db", default=None)
    args = p.parse_args()

    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    import persistence as _db
    con = _db.init()
    res = run_adapter(con, DartAdapter(), since)
    print(f"DART: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
