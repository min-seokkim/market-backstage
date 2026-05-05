"""뉴스 검색 어댑터.

Google News RSS 사용 — API 키 불요, 안정적, 한국어 검색 지원
(https://news.google.com/rss/search?q=K&hl=ko&gl=KR&ceid=KR:ko).

원래 네이버 검색을 시도했는데 SPA 전환으로 정적 HTML에 결과가 없어
스크래핑 실패. Google News RSS는 표준 RSS XML로 결과를 줘서 BS4의
xml 파서로 안정적으로 파싱 가능.

variables.py / events_catalog.py 의 source='news' 항목의 keyword 합집합을
순회하며 fetch. rate limit: 키워드 사이 0.5초 sleep.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from dotenv import load_dotenv

from . import Document, IngestResult, IngestedRawEvent, run_adapter
from events_catalog import EVENT_CATALOG
from variables import VARIABLE_CATALOG

load_dotenv()
log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class NewsAdapter:
    name = "news"

    def __init__(self, max_per_keyword: int = 10):
        self.max_per_keyword = max_per_keyword

    # ---- helpers ---------------------------------------------------------

    def _keywords(self) -> list[str]:
        """모든 source='news' 변수·이벤트의 keyword 합집합."""
        seen: set[str] = set()
        out: list[str] = []
        for v in VARIABLE_CATALOG:
            if v.source != "news":
                continue
            for kw in v.source_params.get("keywords", []):
                if kw not in seen:
                    seen.add(kw); out.append(kw)
        for ev in EVENT_CATALOG:
            if ev.source != "news":
                continue
            for kw in (ev.detection or {}).get("keywords") or []:
                if kw not in seen:
                    seen.add(kw); out.append(kw)
        return out

    def _fetch_one(self, keyword: str) -> list[Document]:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            log.warning("requests / bs4 not installed; news fetch skipped")
            return []
        url = GOOGLE_NEWS_RSS.format(q=quote_plus(keyword))
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            r.raise_for_status()
        except Exception as e:
            log.warning("google news fetch failed kw=%s err=%s", keyword, e)
            return []

        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        out: list[Document] = []
        for it in items[: self.max_per_keyword]:
            title_el = it.find("title")
            link_el = it.find("link")
            desc_el = it.find("description")
            pub_el = it.find("pubDate")
            if not title_el or not link_el:
                continue
            title = title_el.get_text(strip=True)
            href = link_el.get_text(strip=True)
            desc = desc_el.get_text(" ", strip=True) if desc_el else ""
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = (parsedate_to_datetime(pub_el.get_text(strip=True))
                          if pub_el else datetime.now(timezone.utc))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)
            if not title or not href:
                continue
            doc = Document(
                source="news", url=href, title=title, body=desc,
                published_at=pub_dt, fetched_at=datetime.now(timezone.utc),
                metadata={"keyword": keyword},
            )
            out.append(doc)
        return out

    # ---- protocol ---------------------------------------------------------

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        keywords = self._keywords()
        log.info("news adapter: %d keywords", len(keywords))

        seen_hashes: set[str] = set()
        for kw in keywords:
            docs = self._fetch_one(kw)
            time.sleep(0.5)  # courtesy delay
            for d in docs:
                if d.raw_hash in seen_hashes:
                    continue
                seen_hashes.add(d.raw_hash)
                doc_idx = len(result.documents)
                result.documents.append(d)

                # Light-touch event detection by keyword in title
                for tmpl in EVENT_CATALOG:
                    if tmpl.source != "news":
                        continue
                    tkws = (tmpl.detection or {}).get("keywords") or []
                    if any(k in d.title for k in tkws):
                        result.raw_events.append(IngestedRawEvent(
                            template_id=tmpl.id, ts=d.published_at,
                            payload={"title": d.title, "url": d.url,
                                     "matched_keyword": kw},
                            severity=tmpl.typical_severity,
                            source_doc_idx=doc_idx,
                        ))
        return result


def main():
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    p.add_argument("--max", type=int, default=5)
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=7))
    con = _db.init()
    res = run_adapter(con, NewsAdapter(max_per_keyword=args.max), since)
    print(f"news: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
