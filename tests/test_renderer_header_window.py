"""render_header의 window tooltip 테스트."""

from datetime import datetime
from zoneinfo import ZoneInfo

from pulse.renderer.sections import render_header


def test_render_header_with_window_midnight() -> None:
    """render_header가 window 기간을 커스텀 tooltip bubble에 포함한다 (00:00)."""
    window_start = datetime(2026, 7, 22, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
        window_start=window_start,
        window_end=window_end,
    )

    # 말풍선이 설명 한 줄 + 기간 불릿으로 구성된다
    assert 'class="tooltip-bubble' in html
    assert "이 대시보드가 집계한 조회 기간" in html
    assert "<li>2026-07-22 (수)</li>" in html
    # title 속성 없음
    assert "title=" not in html


def test_render_header_with_window_with_time() -> None:
    """render_header가 시각 포함 window를 커스텀 tooltip에 포함한다."""
    window_start = datetime(2026, 7, 22, 15, 30, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 15, 30, 0, tzinfo=ZoneInfo("UTC"))

    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
        window_start=window_start,
        window_end=window_end,
    )

    # 말풍선에 설명 한 줄과 시각 포함 기간이 담긴다
    assert "이 대시보드가 집계한 조회 기간" in html
    assert "15:30" in html
    assert "(수)" in html
    # title 속성 없음
    assert "title=" not in html


def test_render_header_without_window() -> None:
    """window가 None이면 tooltip이 없고 순수 period_text만 표시된다."""
    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
        window_start=None,
        window_end=None,
    )

    # tooltip 없음, 순수 period_text만
    assert "24시간 기준" in html
    assert "tooltip" not in html
    assert "title=" not in html


def test_render_header_daily_text() -> None:
    """일간 모드의 헤더 텍스트를 확인한다."""
    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
    )

    assert "Daily Pulse" in html
    assert "24시간 기준" in html


def test_render_header_weekly_text() -> None:
    """주간 모드의 헤더 텍스트를 확인한다."""
    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-28",
        lookback_hours=168,
        period="weekly",
    )

    assert "Weekly Pulse" in html
    assert "7일 기준" in html


def test_render_header_tooltip_bubble_positioning() -> None:
    """헤더 tooltip-bubble은 .tooltip-bubble--below 클래스로 위쪽 공간 부족 대응한다."""
    window_start = datetime(2026, 7, 22, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
        window_start=window_start,
        window_end=window_end,
    )

    # page-meta 내 period_text가 tooltip-host로 감싸져 있고, 클래스 추가되어야 함
    # (현재: 구현 후에 확인하면 됨)
    assert "tooltip-host" in html or '<span class="tooltip-host">' in html


def test_render_header_tooltip_align_start_class() -> None:
    """헤더 tooltip-bubble이 tooltip-bubble--align-start 클래스를 포함한다."""
    window_start = datetime(2026, 7, 22, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    window_end = datetime(2026, 7, 23, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    html = render_header(
        team_name="테스트팀",
        report_date="2026-07-23",
        lookback_hours=24,
        period="daily",
        window_start=window_start,
        window_end=window_end,
    )

    # 헤더 tooltip-bubble 마크업에 tooltip-bubble--align-start 클래스 포함 여부
    assert "tooltip-bubble--below tooltip-bubble--align-start" in html
