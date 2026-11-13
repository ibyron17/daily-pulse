"""window 기간 포맷 로직 테스트."""

from datetime import datetime
from zoneinfo import ZoneInfo

from pulse.renderer.sections import _format_window_text


def test_format_window_midnight_both_ends_daily() -> None:
    """양끝이 00:00이고 같은 날이면 단일 날짜 표시."""
    window_start = datetime(2026, 7, 22, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    result = _format_window_text(window_start, window_end)

    # 기대값: "2026-07-22 (수)"
    assert result == "2026-07-22 (수)"


def test_format_window_midnight_both_ends_weekly() -> None:
    """양끝이 00:00이고 여러 날이면 날짜 범위 표시."""
    # 월요일 2026-07-20부터 일요일 2026-07-26 자정까지 (다음 월요일 00:00)
    # 실제로 표시할 기간: 월 ~ 일 (하루 전인 2026-07-26)
    window_start = datetime(2026, 7, 20, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 27, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    result = _format_window_text(window_start, window_end)

    # 기대값: "2026-07-20 (월) ~ 2026-07-26 (일)"
    assert result == "2026-07-20 (월) ~ 2026-07-26 (일)"


def test_format_window_with_time() -> None:
    """시각이 있으면 시각 포함."""
    window_start = datetime(2026, 7, 22, 15, 30, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 15, 30, 0, tzinfo=ZoneInfo("UTC"))

    result = _format_window_text(window_start, window_end)

    # 기대값: "2026-07-22 (수) 15:30 ~ 2026-07-23 (목) 15:30"
    assert result == "2026-07-22 (수) 15:30 ~ 2026-07-23 (목) 15:30"


def test_format_window_none_windows() -> None:
    """window가 None이면 빈 문자열 반환."""
    result = _format_window_text(None, None)
    assert result == ""

    result = _format_window_text(None, datetime.now())
    assert result == ""

    result = _format_window_text(datetime.now(), None)
    assert result == ""


def test_format_window_72h_daily() -> None:
    """72시간 일간 윈도우는 범위 표시 (금~일)."""
    # 금 00:00 ~ 월 00:00 (실제 표시: 금~일)
    window_start = datetime(2026, 7, 24, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 27, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    result = _format_window_text(window_start, window_end)

    # 기대값: "2026-07-24 (금) ~ 2026-07-26 (일)"
    assert result == "2026-07-24 (금) ~ 2026-07-26 (일)"
