"""KRX 일별 매매 동향 어댑터 (stub).

KRX 정보데이터시스템 (data.krx.co.kr) 은 공개되어 있지만 백엔드가 OTP 토큰
방식이라 단순 GET으로 안 됨. 다음 iteration에서 본격 구현 예정.

MVP는 stub: 빈 결과 + 경고. 일별 투자자별 매매·신용잔고·공매도잔고·종목별
지표 모두 동일하게 stub.

`KRX_DATA_PATH` 환경변수에 로컬 CSV 디렉토리를 지정하면 그곳의 CSV를
읽어 옴 (수동 다운로드 fallback).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

from . import IngestResult

load_dotenv()
log = logging.getLogger(__name__)


class KrxAdapter:
    name = "krx"

    def fetch(self, since: datetime) -> IngestResult:
        result = IngestResult()
        path = os.environ.get("KRX_DATA_PATH", "")
        if not path:
            log.info("krx: stub — no KRX_DATA_PATH set, returning empty")
            return result
        # TODO: scan path for CSVs and parse
        log.info("krx: KRX_DATA_PATH=%s — local-CSV ingest not yet implemented", path)
        return result
