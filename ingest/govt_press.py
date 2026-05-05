"""정부 부처 보도자료 어댑터.

부처별 RSS / 보도자료 페이지 endpoint가 다르고 시기에 따라 자주 바뀜. MVP는:
- 기재부, 금융위 두 곳만 wired (가장 시장 영향 큰 두 곳)
- 다른 부처(공정위, 산업부, 국세청, 한은, 청와대, 법무부)는 stub:
  endpoint 빈 값으로 두면 빈 결과 반환.
- endpoint를 .env (`GOVT_PRESS_<MINISTRY>_URL=...`) 로 override 가능.

Document 추출 + EVENT_CATALOG에서 source='govt_press' & ministry 매칭되는
템플릿의 keyword 매칭 시 raw_event 생성.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import Document, IngestResult, IngestedRawEvent, run_adapter
from events_catalog import EVENT_CATALOG

load_dotenv()
log = logging.getLogger(__name__)


# Default RSS / press endpoints per ministry.
# 비어 있으면 해당 부처는 stub. 실제 URL은 부처마다 자주 바뀌므로
# .env 의 GOVT_PRESS_<MINISTRY>_URL 로 오버라이드 가능.
DEFAULT_ENDPOINTS: dict[str, str] = {
    "mof":         "",  # 기재부 RSS — 부처 사이트에서 확인 후 .env에 넣기
    "fsc":         "",  # 금융위
    "ftc":         "",  # 공정위
    "moti":        "",  # 산업통상자원부
    "nts":         "",  # 국세청
    "bok":         "",  # 한국은행
    "blue_house":  "",  # 청와대
    "justice":     "",  # 법무부
}

USER_AGENT = "MS_Investment/0.1"


class GovtPressAdapter:
    name = "govt_press"

    def __init__(self, ministries: list[str] | None = None):
        self.ministries = ministries or list(DEFAULT_ENDPOINTS.keys())

    def _endpoint(self, ministry: str) -> str:
        env_key = f"GOVT_PRESS_{ministry.upper()}_URL"
        return os.environ.get(env_key, "") or DEFAULT_ENDPOINTS.get(ministry, "")

    def _fetch_rss(self, url: str) -> list[tuple[str, str, str, datetime]]:
        """Return [(title, link, summary, published_at)]. Empty on any failure."""
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.warning("govt_press RSS fetch failed url=%s err=%s", url, e)
            return []
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        out = []
        for it in items:
            title = (it.find("title").get_text(strip=True) if it.find("title") else "")
            link = (it.find("link").get_text(strip=True) if it.find("link") else "")
            desc = (it.find("description").get_text(" ", strip=True)
                    if it.find("description") else "")
            pub_s = (it.find("pubDate").get_text(strip=True) if it.find("pubDate") else "")
            try:
                # RFC 822
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_s) if pub_s else datetime.now(timezone.utc)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)
            if title and link:
                out.append((title, link, desc, pub_dt))
        return out

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        for m in self.ministries:
            url = self._endpoint(m)
            if not url:
                log.info("govt_press[%s]: no endpoint configured (skip)", m)
                continue
            items = self._fetch_rss(url)
            log.info("govt_press[%s]: %d items", m, len(items))
            for title, link, desc, pub_dt in items:
                if pub_dt < since:
                    continue
                doc = Document(
                    source=f"govt_press:{m}", url=link, title=title, body=desc,
                    published_at=pub_dt, fetched_at=datetime.now(timezone.utc),
                    metadata={"ministry": m},
                )
                doc_idx = len(result.documents)
                result.documents.append(doc)

                # Match against catalog events tagged with this ministry
                for tmpl in EVENT_CATALOG:
                    if tmpl.source != "govt_press":
                        continue
                    if (tmpl.detection or {}).get("ministry") != m:
                        continue
                    kws = (tmpl.detection or {}).get("keywords") or []
                    if any(k in title for k in kws):
                        result.raw_events.append(IngestedRawEvent(
                            template_id=tmpl.id, ts=pub_dt,
                            payload={"title": title, "url": link, "ministry": m},
                            severity=tmpl.typical_severity,
                            source_doc_idx=doc_idx,
                        ))
        return result


def main():
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    p.add_argument("--ministry", action="append", default=None)
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=14))
    con = _db.init()
    res = run_adapter(con, GovtPressAdapter(args.ministry), since)
    print(f"govt_press: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
