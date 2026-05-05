"""Dynamic catalog (agenda) extraction — Layer 1 Stage 2.

이 패키지는 ingest된 1차자료로부터 *catalog 자체*를 업데이트한다 — 새
EventTemplate, VariableSpec, actor, causal edge 후보를 LLM으로 발견해
*_dyn 테이블에 'proposed' 상태로 적재. trust score gate를 통과하면
'active' 승격되어 시뮬에 합류한다.

이 모듈이 없으면 모델은 hardcoded catalog에 영원히 갇혀 있다 — 진행 중인
regime change(예: 2025-2026 거버넌스 reform)를 사람이 매주 코드 수정해야
잡을 수 있다. 여기서 그 catalog evolution loop를 자동화한다.
"""

from .agenda import (
    extract_one,
    extract_batch,
    compute_trust_score,
    promote_eligible,
    PROMOTE_AUTO_THRESHOLD,
    PROMOTE_REVIEW_THRESHOLD,
)

__all__ = [
    "extract_one",
    "extract_batch",
    "compute_trust_score",
    "promote_eligible",
    "PROMOTE_AUTO_THRESHOLD",
    "PROMOTE_REVIEW_THRESHOLD",
]
