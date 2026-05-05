"""뉴스 검색 어댑터.

Google News RSS 사용 — API 키 불요, 안정적, 한국어 검색 지원
(https://news.google.com/rss/search?q=K&hl=ko&gl=KR&ceid=KR:ko).

원래 네이버 검색을 시도했는데 SPA 전환으로 정적 HTML에 결과가 없어
스크래핑 실패. Google News RSS는 표준 RSS XML로 결과를 줘서 BS4의
xml 파서로 안정적으로 파싱 가능.

variables.py / events_catalog.py 의 source='news' 항목의 keyword 합집합을
순회하며 fetch. rate limit: 키워드 사이 0.5초 sleep.

`since` 파라미터에 대하여:
  Google News RSS는 date-range query를 지원하지 *않는다*. 즉 *historical
  backfill*은 본질적으로 불가능 — RSS feed는 항상 "최근 results"만 반환한다.
  fetch(since)는 결과를 published_at >= since 로 *post-filter* 한다.
  이는 since를 부분적으로 honor하는 것이지 historical fetch를 수행하는 것이
  아니다. 진짜 historical news가 필요하면 빅카인즈(kinds.or.kr) 같은 archive
  API 어댑터를 별도로 추가해야 한다 (ingest_gap_report.md PR3 참조).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from dotenv import load_dotenv

from . import Document, IngestResult, IngestedRawEvent, run_adapter
from catalog.events import EVENT_CATALOG
from catalog.variables import VARIABLE_CATALOG
from .seeds import (
    gather_news_seeds, gather_news_active_seeds,
    _BROAD_SEEDS_STATIC_MINIMAL,
)

load_dotenv()
log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class NewsAdapter:
    name = "news"

    def __init__(self, max_per_keyword: int = 10, *,
                 mode: str = "catalog",
                 con: sqlite3.Connection | None = None):
        """
        mode:
          - "catalog": precision — keywords from the *static* in-process
            VARIABLE_CATALOG / EVENT_CATALOG (legacy default).
          - "broad":   recall — dynamic 4-layer seed (target_events.yaml +
            event_templates_dyn + variable_specs_dyn + cold-start fallback).
            Best paired with the LLM agenda extractor.
          - "hybrid":  union of catalog (static) and broad (dynamic) seeds.

        con:
          Used by `broad` and `hybrid` to read *_dyn tables. Without it,
          dynamic layers fall back to cold-start static minimal seeds.
        """
        self.max_per_keyword = max_per_keyword
        if mode not in ("catalog", "broad", "hybrid"):
            raise ValueError(f"unknown mode={mode!r}")
        self.mode = mode
        self.con = con

    # ---- helpers ---------------------------------------------------------

    def _catalog_keywords(self) -> list[str]:
        """Catalog mode: keywords from active *_dyn rows.

        With `self.con` available, delegates to
        `seeds.gather_news_active_seeds`:
          · all active event_templates_dyn (no source filter)
          · active variable_specs_dyn[source='news']

        Without `self.con` (cold-start safety: NewsAdapter() instantiated
        without DB context) falls back to the legacy static catalog read
        in `_catalog_keywords_static_fallback`. The static .py files
        catalog/events.py and catalog/variables.py are *cold-start seeds
        only* — PR1's seed_dynamic_catalog_from_static already replicated
        their content into *_dyn, so steady state should always go
        through gather_news_active_seeds.
        """
        if self.con is not None:
            bundle = gather_news_active_seeds(self.con)
            by = bundle["by_source"]
            log.info(
                "news adapter: catalog keywords by source: "
                "events_active_all=%d, vars_active_news=%d, "
                "total unique=%d",
                by["event_templates_dyn_active_all"],
                by["variable_specs_dyn_active_news"],
                by["total_unique"],
            )
            return bundle["keywords"]
        return self._catalog_keywords_static_fallback()

    def _catalog_keywords_static_fallback(self) -> list[str]:
        """Legacy path — used only when self.con is None. Reads the
        static VARIABLE_CATALOG / EVENT_CATALOG tuples directly. These
        files are kept as cold-start seed source for fresh installs."""
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

    def _broad_keywords(self) -> list[str]:
        """Broad mode: active+proposed *_dyn ∪ target_events.yaml ∪
        cold-start fallback. Delegates to seeds.gather_news_seeds.
        Emits per-layer breakdown log so operators can see which source
        is contributing what."""
        if self.con is None:
            log.info("news adapter: no con — broad falls back to "
                     "cold-start minimal seeds (%d kw)",
                     len(_BROAD_SEEDS_STATIC_MINIMAL))
            return list(_BROAD_SEEDS_STATIC_MINIMAL)
        bundle = gather_news_seeds(self.con)
        by = bundle["by_source"]
        log.info(
            "news adapter: broad keywords by source: cold-start=%d, "
            "target_events=%d, event_templates_dyn=%d (active+proposed), "
            "variable_specs_dyn=%d (active+proposed, source=news), "
            "total unique=%d",
            by["cold_start"], by["target_events"],
            by["event_templates_dyn"], by["variable_specs_dyn"],
            by["total_unique"],
        )
        return bundle["keywords"]

    def _keywords(self) -> list[str]:
        # Always compute both sides for diagnostics. Architectural
        # invariant: catalog ⊆ broad (active ⊆ active+proposed). If
        # catalog has anything broad doesn't, that's a drift bug.
        catalog_kws = self._catalog_keywords()
        broad_kws = self._broad_keywords()

        catalog_set = set(catalog_kws)
        broad_set = set(broad_kws)
        overlap = catalog_set & broad_set
        catalog_only = catalog_set - broad_set
        broad_only = broad_set - catalog_set
        log.info(
            "news adapter: keyword sets — catalog (active _dyn)=%d, "
            "broad (active+proposed+target+cold)=%d, overlap=%d, "
            "catalog_only=%d, broad_only=%d",
            len(catalog_kws), len(broad_kws), len(overlap),
            len(catalog_only), len(broad_only),
        )
        if catalog_only:
            log.warning(
                "news adapter: catalog has %d keywords NOT in broad — "
                "architectural drift (catalog ⊆ broad invariant broken).",
                len(catalog_only),
            )

        if self.mode == "catalog":
            return catalog_kws
        if self.mode == "broad":
            return broad_kws
        # hybrid: catalog ∪ broad (= broad when catalog ⊆ broad holds)
        seen = set(catalog_kws)
        out = list(catalog_kws)
        for kw in broad_kws:
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
        """Fetch latest articles for each keyword, post-filter to `since`.

        Google News RSS does not accept a date-range query, so we cannot
        request historical articles directly. The RSS feed returns whatever
        Google considers "recent" for the keyword (usually the last few
        weeks, occasionally older republished pieces). Documents whose
        `published_at` is earlier than `since` are dropped after fetch.

        This means:
          - bumping `since` to e.g. 365 days does NOT increase the corpus
            depth — it only widens the keep-window for whatever the RSS
            already returns
          - shrinking `since` will drop the incidental old aggregations the
            RSS sometimes includes
        """
        result = IngestResult()
        keywords = self._keywords()
        log.warning("news.py: since=%s -- RSS-only source, best-effort "
                    "post-filter only (no historical fetch)",
                    since.date().isoformat())
        log.info("news adapter: %d keywords", len(keywords))

        seen_hashes: set[str] = set()
        n_total = 0
        n_dropped_pre_since = 0
        for kw in keywords:
            docs = self._fetch_one(kw)
            time.sleep(0.5)  # courtesy delay
            for d in docs:
                n_total += 1
                if d.published_at < since:
                    n_dropped_pre_since += 1
                    continue
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
        log.info("news adapter: %d items returned by RSS, %d dropped as "
                 "older than since, %d unique kept",
                 n_total, n_dropped_pre_since, len(result.documents))
        return result


def main():
    import db as _db
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None)
    p.add_argument("--max", type=int, default=5)
    p.add_argument("--mode", choices=("catalog", "broad", "hybrid"),
                   default="catalog",
                   help="catalog=precision, broad=recall (LLM extractor "
                        "친화), hybrid=union")
    args = p.parse_args()
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=7))
    con = _db.init()
    res = run_adapter(con, NewsAdapter(max_per_keyword=args.max,
                                       mode=args.mode), since)
    print(f"news[{args.mode}]: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
