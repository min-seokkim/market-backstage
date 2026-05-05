"""국회 의안정보시스템 어댑터 (data.go.kr OpenAPI 우선).

data.go.kr 의 *국회 의안정보시스템* OpenAPI(`open.assembly.go.kr/portal/openapi/...`)
가 공식 채널. `ASSEMBLY_API_KEY` 가 있으면 OpenAPI 사용 (broad sweep:
keyword 필터 X — 모든 의안 fetch). LLM agenda extractor가 의안 본문을 읽고
새 EventTemplate / VariableSpec / actor 후보를 *_dyn 테이블에 적재.

Body 본문은 두 단계로 채운다:
  1. 발의의안 목록(`nzmimeepazxkubdpn`) — 메타데이터만 (제안이유 필드는 빈 값)
  2. 의안 SUMMARY(`BPMBILLSUMMARY`) — bill_no 기준 per-bill 호출로 *진짜* 본문 확보

Cursor: documents 테이블의 metadata_json.summary_fetched_at 가 있는 bill_no는
이미 SUMMARY가 들어간 row 이므로 SUMMARY 재호출과 신규 insert 모두 skip.

Rate limit: ASSEMBLY_DAILY_CALL_BUDGET (default 8,000) 누적 호출 한도.
metadata 페이지 + per-bill SUMMARY 합산. 한도 도달 시 break — 다음 cron 호출이
이어서 진행.

Fallback: `ASSEMBLY_BILLS_URL` 가 있으면 RSS/XML 파싱 (이전 stub 동작).
둘 다 없으면 빈 결과.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import Document, IngestResult, run_adapter

load_dotenv()
log = logging.getLogger(__name__)


# OpenAPI endpoints
ASSEMBLY_OPENAPI = (
    "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn"
)
BPMBILLSUMMARY_URL = (
    "https://open.assembly.go.kr/portal/openapi/BPMBILLSUMMARY"
)
DEFAULT_AGE = 22  # 22대 국회 (2024-05-30 ~ 2028-05-29)
DEFAULT_DAILY_CALL_BUDGET = 8000


class AssemblyAdapter:
    name = "assembly"

    def __init__(self, *, age: int = DEFAULT_AGE, page_size: int = 100,
                 max_pages: int | None = None,
                 con: sqlite3.Connection | None = None,
                 daily_call_budget: int | None = None,
                 summary_sleep_s: float = 0.1):
        self.age = age
        self.page_size = page_size
        env_max = os.environ.get("ASSEMBLY_MAX_PAGES")
        if max_pages is not None:
            self.max_pages = max_pages
        elif env_max:
            try:
                self.max_pages = int(env_max)
            except ValueError:
                self.max_pages = 60
        else:
            self.max_pages = 60
        self.con = con
        self.daily_call_budget = (
            daily_call_budget
            if daily_call_budget is not None
            else int(os.environ.get(
                "ASSEMBLY_DAILY_CALL_BUDGET",
                str(DEFAULT_DAILY_CALL_BUDGET),
            ))
        )
        self.summary_sleep_s = summary_sleep_s
        self._calls_made = 0

    # ---- budget + cursor ------------------------------------------------

    def _budget_ok(self) -> bool:
        if self._calls_made >= self.daily_call_budget:
            return False
        return True

    def _load_summary_cursor(self) -> set[str]:
        """Return bill_no set whose documents row already has SUMMARY merged.
        Rows are recognized by metadata_json.summary_fetched_at presence."""
        if self.con is None:
            return set()
        try:
            rows = self.con.execute(
                "SELECT metadata_json FROM documents WHERE source='assembly'"
            ).fetchall()
        except Exception:
            return set()
        seen: set[str] = set()
        for (meta_json,) in rows:
            if not meta_json:
                continue
            try:
                meta = json.loads(meta_json)
            except Exception:
                continue
            if meta.get("summary_fetched_at") and meta.get("bill_no"):
                seen.add(str(meta["bill_no"]))
        return seen

    # ---- BPMBILLSUMMARY -------------------------------------------------

    def _fetch_bill_summary(self, bill_no: str, api_key: str) -> str:
        """Per-bill SUMMARY fetch. Returns '' on any failure (logged)."""
        try:
            import requests
        except ImportError:
            return ""
        params = {
            "KEY": api_key,
            "Type": "json",
            "pIndex": 1,
            "pSize": 10,
            "BILL_NO": str(bill_no),
        }
        try:
            r = requests.get(BPMBILLSUMMARY_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("assembly BPMBILLSUMMARY failed bill_no=%s err=%s",
                        bill_no, e)
            return ""
        envelope = data.get("BPMBILLSUMMARY") or []
        rows: list[dict] = []
        for chunk in envelope:
            if isinstance(chunk, dict) and "row" in chunk:
                rows = chunk["row"] or []
                break
        if not rows:
            return ""
        return (rows[0].get("SUMMARY") or "").strip()

    @staticmethod
    def _build_body(*, proposer: str, propose_dt: str, committee: str,
                    summary: str) -> str:
        return (
            f"발의자: {proposer}\n"
            f"발의일: {propose_dt}\n"
            f"위원회: {committee}\n"
            f"제안이유 및 주요내용:\n{summary}"
        )

    # ---- OpenAPI path ---------------------------------------------------

    def _fetch_openapi(self, since: datetime, api_key: str) -> list[Document]:
        try:
            import requests
        except ImportError:
            log.warning("requests not installed; assembly OpenAPI skipped")
            return []

        cursor_seen = self._load_summary_cursor()
        log.info("assembly: cursor has %d bills with SUMMARY already",
                 len(cursor_seen))

        out: list[Document] = []
        skipped_cursor = 0
        skipped_old = 0

        for page in range(1, self.max_pages + 1):
            if not self._budget_ok():
                log.warning("assembly: budget %d reached at page %d — break",
                            self.daily_call_budget, page)
                break
            params = {
                "Key": api_key,
                "Type": "json",
                "pIndex": page,
                "pSize": self.page_size,
                "AGE": self.age,
            }
            try:
                r = requests.get(ASSEMBLY_OPENAPI, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                self._calls_made += 1
            except Exception as e:
                log.warning("assembly OpenAPI fetch failed page=%d err=%s",
                            page, e)
                break

            envelope = data.get("nzmimeepazxkubdpn") or []
            rows: list[dict] = []
            for chunk in envelope:
                if isinstance(chunk, dict) and "row" in chunk:
                    rows = chunk["row"] or []
                    break
            if not rows:
                break

            seen_old = 0
            for it in rows:
                propose_dt = self._parse_dt(it.get("PROPOSE_DT"))
                if propose_dt < since:
                    seen_old += 1
                    continue
                bill_no = it.get("BILL_NO")
                if bill_no and str(bill_no) in cursor_seen:
                    skipped_cursor += 1
                    continue
                if not self._budget_ok():
                    log.warning(
                        "assembly: budget %d reached at bill — break",
                        self.daily_call_budget,
                    )
                    break

                title = (it.get("BILL_NAME") or "").strip()
                link = it.get("LINK_URL") or ""
                proposer = (it.get("PROPOSER") or "").strip()
                committee = (it.get("COMMITTEE") or "").strip()
                propose_dt_s = it.get("PROPOSE_DT", "") or ""

                summary = self._fetch_bill_summary(bill_no, api_key) if bill_no else ""
                self._calls_made += 1
                if self.summary_sleep_s:
                    time.sleep(self.summary_sleep_s)

                body = self._build_body(
                    proposer=proposer,
                    propose_dt=propose_dt_s,
                    committee=committee,
                    summary=summary,
                )
                out.append(Document(
                    source="assembly", url=link, title=title, body=body,
                    published_at=propose_dt,
                    fetched_at=datetime.now(timezone.utc),
                    metadata={
                        "bill_id": it.get("BILL_ID"),
                        "bill_no": bill_no,
                        "proposer": proposer,
                        "committee": committee,
                        "propose_dt": propose_dt_s,
                        "age": self.age,
                        "summary_fetched_at": (
                            datetime.now(timezone.utc).isoformat()
                            if summary else None
                        ),
                    },
                ))
            else:
                # else-of-for: only runs when inner for completed without break
                if seen_old == len(rows):
                    skipped_old += seen_old
                    break
                continue
            # inner break path — outer break too
            break

        log.info(
            "assembly OpenAPI: fetched %d bills (cursor_skip=%d, "
            "old_skip=%d, total_calls=%d)",
            len(out), skipped_cursor, skipped_old, self._calls_made,
        )
        return out

    @staticmethod
    def _parse_dt(s: str | None) -> datetime:
        if not s:
            return datetime.min.replace(tzinfo=timezone.utc)
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    # ---- RSS/XML fallback path -----------------------------------------

    def _fetch_rss(self, since: datetime, url: str) -> list[Document]:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.warning("assembly RSS fetch failed: %s", e)
            return []

        out: list[Document] = []
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
            out.append(Document(
                source="assembly", url=link, title=title, body=desc,
                published_at=pub_dt, fetched_at=datetime.now(timezone.utc),
            ))
        return out

    # ---- protocol -------------------------------------------------------

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        api_key = os.environ.get("ASSEMBLY_API_KEY")
        if api_key:
            result.documents.extend(self._fetch_openapi(since, api_key))
            return result

        rss_url = os.environ.get("ASSEMBLY_BILLS_URL", "")
        if rss_url:
            result.documents.extend(self._fetch_rss(since, rss_url))
            return result

        log.info("assembly: neither ASSEMBLY_API_KEY nor ASSEMBLY_BILLS_URL set "
                 "— stub returning empty. Catalog evolution requires this.")
        return result


# -----------------------------------------------------------------------------
# rebuild_summaries — one-off backfill for existing metadata-only docs
# -----------------------------------------------------------------------------


def _hash_doc(url: str, title: str, body: str) -> str:
    h = hashlib.sha1()
    h.update((url or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((title or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((body or "")[:4096].encode("utf-8"))
    return h.hexdigest()


def rebuild_summaries(con: sqlite3.Connection,
                      api_key: str,
                      *,
                      daily_call_budget: int | None = None,
                      progress_every: int = 100,
                      ) -> dict[str, int]:
    """Backfill SUMMARY into existing assembly docs whose metadata_json
    lacks summary_fetched_at. Updates body + metadata_json + raw_hash in
    place. Respects daily_call_budget — if exceeded, partial result is
    committed and the next invocation resumes via the same cursor.
    """
    rows = con.execute(
        "SELECT id, url, title, published_at, metadata_json "
        "FROM documents WHERE source='assembly'"
    ).fetchall()

    adapter = AssemblyAdapter(con=con, daily_call_budget=daily_call_budget)
    todo: list[tuple] = []
    for doc_id, url, title, published_at, meta_json in rows:
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:
            meta = {}
        if meta.get("summary_fetched_at"):
            continue
        bill_no = meta.get("bill_no")
        if not bill_no:
            continue
        todo.append((doc_id, url, title, published_at, meta, bill_no))

    counts = {"considered": len(rows), "todo": len(todo),
              "updated": 0, "summary_empty": 0,
              "calls": 0, "budget_break": 0}
    log.info("assembly rebuild: %d docs need SUMMARY (of %d total)",
             counts["todo"], counts["considered"])

    for i, (doc_id, url, title, published_at, meta, bill_no) in enumerate(todo):
        if not adapter._budget_ok():
            log.warning("rebuild: budget %d reached at %d/%d — committing partial",
                        adapter.daily_call_budget, i, counts["todo"])
            counts["budget_break"] = 1
            break
        summary = adapter._fetch_bill_summary(bill_no, api_key)
        adapter._calls_made += 1
        if adapter.summary_sleep_s:
            time.sleep(adapter.summary_sleep_s)
        if not summary:
            counts["summary_empty"] += 1
            continue

        new_body = adapter._build_body(
            proposer=meta.get("proposer", ""),
            propose_dt=meta.get("propose_dt") or (published_at[:10] if published_at else ""),
            committee=meta.get("committee", ""),
            summary=summary,
        )
        meta["summary_fetched_at"] = datetime.now(timezone.utc).isoformat()
        new_hash = _hash_doc(url or "", title or "", new_body)
        try:
            con.execute(
                "UPDATE documents SET body=?, metadata_json=?, raw_hash=? "
                "WHERE id=?",
                (new_body, json.dumps(meta, ensure_ascii=False), new_hash, doc_id),
            )
        except sqlite3.IntegrityError as e:
            # raw_hash UNIQUE collision (extremely unlikely — different bill,
            # same body). Skip this row and log.
            log.warning("rebuild: integrity error doc_id=%d bill_no=%s err=%s",
                        doc_id, bill_no, e)
            continue
        counts["updated"] += 1

        if (i + 1) % progress_every == 0:
            log.info("rebuild: %d/%d (%.1f%%) updated=%d empty=%d calls=%d",
                     i + 1, counts["todo"],
                     100 * (i + 1) / max(1, counts["todo"]),
                     counts["updated"], counts["summary_empty"],
                     adapter._calls_made)
            con.commit()

    counts["calls"] = adapter._calls_made
    con.commit()
    log.info("rebuild: done. updated=%d empty=%d calls=%d budget_break=%d",
             counts["updated"], counts["summary_empty"], counts["calls"],
             counts["budget_break"])
    return counts


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None,
                   help="ISO date — only used by normal fetch path")
    p.add_argument("--age", type=int, default=DEFAULT_AGE)
    p.add_argument("--max-pages", type=int, default=60)
    p.add_argument("--rebuild-summaries", action="store_true",
                   help="One-off: backfill SUMMARY into existing assembly "
                        "docs (in-place body + metadata_json update). "
                        "Respects ASSEMBLY_DAILY_CALL_BUDGET.")
    p.add_argument("--budget", type=int, default=None,
                   help="Override ASSEMBLY_DAILY_CALL_BUDGET for this run")
    args = p.parse_args()

    if args.rebuild_summaries:
        # Use modern persistence path (avoid legacy `import db as _db`
        # that's stubbed across multiple CLIs — separate cleanup PR).
        import persistence as db
        api_key = os.environ.get("ASSEMBLY_API_KEY")
        if not api_key:
            print("ASSEMBLY_API_KEY is not set — abort")
            return
        con = db.init()
        counts = rebuild_summaries(con, api_key,
                                   daily_call_budget=args.budget)
        print(f"rebuild: {counts}")
        con.close()
        return

    # Legacy normal-fetch path. The `import db as _db` below is broken
    # across many CLI mains — fix tracked in a separate PR. We keep it
    # untouched here to honor PR boundary.
    import db as _db
    since = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
             if args.since
             else datetime.now(timezone.utc) - timedelta(days=14))
    con = _db.init()
    res = run_adapter(con, AssemblyAdapter(age=args.age,
                                           max_pages=args.max_pages,
                                           con=con,
                                           daily_call_budget=args.budget),
                      since)
    print(f"assembly: {res}")
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
