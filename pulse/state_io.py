"""부수 상태 저장의 실패를 발행 실패로 번지지 않게 격리한다.

배경: `_cmd_collect`는 `run_pipeline`을 try로 감싸고 어떤 예외든 exit 1로 마감한다.
그래서 분석 캐시나 스냅샷 저장이 한 번 실패하면 대시보드가 이미 만들어졌더라도
그날 발행 전체가 실패로 보고된다. 부수 상태는 다음 실행에서 복구되므로
그 대가를 치를 이유가 없다.

이 헬퍼는 **부수 상태에만** 쓴다. 대시보드 HTML처럼 그것 자체가 산출물인 저장에는
쓰지 않는다 — 실패를 숨기면 낡은 산출물이 남은 채 발행 성공으로 보고된다.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def save_optional_state(label: str, save: Callable[[], object]) -> None:
    """부수 상태를 저장하고, 실패하면 경고만 남기고 계속한다.

    OSError만 흡수한다. 직렬화 버그(TypeError 등)는 전파해야 한다 —
    삼키면 상태가 조용히 비어가는 것을 아무도 모르게 된다.

    Args:
        label: 경고 메시지에 쓸 대상 이름 (예: "수명주기 등록부")
        save: 실제 저장을 수행하는 무인자 호출체
    """
    try:
        save()
    except OSError as error:
        logger.warning("%s 저장 실패 — 다음 실행에서 갱신됩니다: %s", label, error)
