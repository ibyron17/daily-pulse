"""부수 상태 저장 격리 테스트.

배경: `_cmd_collect`는 `run_pipeline`을 try로 감싸고 어떤 예외든 exit 1로 마감한다.
그래서 분석 캐시 저장이 한 번 실패하면 대시보드가 이미 만들어졌더라도 그날 발행
전체가 실패로 보고된다. 부수 상태는 다음 실행에서 복구되므로 그 대가를 치를 이유가 없다.
"""

import logging

import pytest

from pulse.state_io import save_optional_state


class TestSaveOptionalState:
    def test_successful_save_runs_the_callable(self) -> None:
        calls: list[str] = []
        save_optional_state("테스트 상태", lambda: calls.append("saved"))
        assert calls == ["saved"]

    def test_os_error_is_absorbed(self) -> None:
        def failing() -> None:
            raise OSError("Read-only file system")

        # 예외가 새어 나가면 발행 전체가 exit 1이 된다
        save_optional_state("테스트 상태", failing)

    def test_permission_error_is_absorbed(self) -> None:
        def failing() -> None:
            raise PermissionError("permission denied")

        save_optional_state("테스트 상태", failing)

    def test_os_error_is_logged_with_the_label(self, caplog: pytest.LogCaptureFixture) -> None:
        def failing() -> None:
            raise OSError("disk full")

        with caplog.at_level(logging.WARNING):
            save_optional_state("수명주기 등록부", failing)

        assert "수명주기 등록부" in caplog.text
        assert "disk full" in caplog.text

    def test_failure_is_not_silent(self, caplog: pytest.LogCaptureFixture) -> None:
        """조용히 넘기면 상태가 비어가는 것을 아무도 모른다 — 최소한 경고는 남아야 한다."""

        def failing() -> None:
            raise OSError("nope")

        with caplog.at_level(logging.WARNING):
            save_optional_state("무언가", failing)

        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_serialization_bugs_are_not_absorbed(self) -> None:
        """TypeError 를 삼키면 직렬화 버그로 상태가 조용히 비어간다."""

        def failing() -> None:
            raise TypeError("Object of type set is not JSON serializable")

        with pytest.raises(TypeError):
            save_optional_state("테스트 상태", failing)

    def test_programming_errors_are_not_absorbed(self) -> None:
        def failing() -> None:
            raise ValueError("bad value")

        with pytest.raises(ValueError):
            save_optional_state("테스트 상태", failing)
