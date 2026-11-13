"""--now 옵션 파싱 및 배선 테스트."""

import pytest

from pulse.publish import _parse_now_override


class TestParseNowOverride:
    """_parse_now_override 함수 테스트."""

    def test_valid_iso_timestamp_with_timezone(self) -> None:
        """유효한 ISO 타임스탐프 (+09:00)."""
        result = _parse_now_override("2026-07-22T09:00:00+09:00")
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 22
        assert result.hour == 9
        assert result.tzinfo is not None

    def test_valid_iso_timestamp_utc(self) -> None:
        """유효한 ISO 타임스탐프 (Z)."""
        result = _parse_now_override("2026-07-22T00:00:00Z")
        assert result.year == 2026
        assert result.tzinfo is not None

    def test_invalid_no_timezone(self) -> None:
        """타임존 없는 타임스탐프 → 에러."""
        with pytest.raises(ValueError, match="타임존을 포함해야 합니다"):
            _parse_now_override("2026-07-22T09:00:00")

    def test_invalid_format(self) -> None:
        """파싱 불가능한 형식 → 에러."""
        with pytest.raises(ValueError, match="파싱 실패"):
            _parse_now_override("invalid-date")

    def test_weekday_detection(self) -> None:
        """월요일 파싱 검증 (2026-07-27은 월요일)."""
        dt = _parse_now_override("2026-07-27T09:00:00+09:00")
        assert dt.weekday() == 0  # 월요일 = 0

    def test_non_monday(self) -> None:
        """수요일 파싱 (2026-07-22)."""
        dt = _parse_now_override("2026-07-22T09:00:00+09:00")
        assert dt.weekday() == 2  # 수요일 = 2


class TestForceWeeklyHelp:
    """--force-weekly 도움말이 실제 동작(주간 전용·월요일 기준 창·실행일 이름표)을 알린다."""

    def test_help_states_weekly_only_and_monday_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from pulse.publish import main

        monkeypatch.setenv("COLUMNS", "300")  # argparse 가 문구 중간에서 줄을 바꾸지 않게 한다
        monkeypatch.setattr("sys.argv", ["pulse.publish", "collect", "--help"])

        with pytest.raises(SystemExit) as exit_info:
            main()  # --help 는 도움말만 출력하고 종료한다 (수집은 실행되지 않는다)

        assert exit_info.value.code == 0
        help_text = capsys.readouterr().out
        assert "--period weekly 전용" in help_text
        assert "그 외 period 와 쓰면 거부" in help_text
        assert "그 주 월요일 00:00" in help_text
        assert "이름표는 실행일" in help_text
