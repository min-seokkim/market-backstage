"""국회 의안정보시스템 어댑터 (stub).

likms.assembly.go.kr 의 검색 엔드포인트는 공식 API가 없고 페이지 구조도
자주 바뀜. MVP는 stub: 빈 결과 반환 + 환경변수
`ASSEMBLY_BILLS_URL` 가 있으면 그 RSS/XML을 fetch.

향후 보강:
- OpenAPI 형식의 데이터셋이 data.go.kr에 있음 ("국회 의안정보시스템")
- 그 OpenAPI를 wire하려면 ASSEMBLY_API_KEY 추가
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import Document, IngestResult, run_adapter

load_dotenv()
log = logging.getLogger(__name__)


class AssemblyAdapter:
    name = "assembly"

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        url = os.environ.get("ASSEMBLY_BILLS_URL", "")
        if not url:
            log.info("assembly: no ASSEMBLY_BILLS_URL set — stub returning empty")
            return result

        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return result

        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.warning("assembly fetch failed: %s", e)
            return result

        soup = BeautifulSoup(r.text, "xml")
        for it in soup.find_all("item"):
            title = (it.find("title").get_text(strip=True) if it.find("title") else "")
            link = (it.find("link").get_text(strip=True) if it.find("link") else "")
            desc = (it.find("description").get_text(" ", strip=True)
                    if it.find("description") else "")
            pub_s = (it.find("pubDate").get_text(strip=True) if it.find("pubDate") else "")
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_s) if pub_s else datetime.now(timezone.utc)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)
            if pub_dt < since:
                continue
            result.documents.append(Document(
                source="assembly", url=link, title=title, body=desc,
                published_at=pub_dt, fetched_at=datetime.now(timezone.utc),
            ))
        return result


def main():
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=14))
    con = _db.init()
    res = run_adapter(con, AssemblyAdapter(), since)
    print(f"assembly: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
