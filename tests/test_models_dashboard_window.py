"""DashboardModel의 window_start/end 필드 테스트."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pulse.models import DashboardModel


def test_dashboard_model_window_fields_default_none() -> None:
    """window_start/end는 기본값이 None이다."""
    model = DashboardModel(
        team_name="test-team",
        report_date=date(2026, 7, 22),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
    )
    assert model.window_start is None
    assert model.window_end is None


def test_dashboard_model_with_window_fields() -> None:
    """window_start/end를 명시적으로 설정할 수 있다."""
    tz = ZoneInfo("Asia/Seoul")
    window_start = datetime(2026, 7, 22, 0, 0, 0, tzinfo=tz)
    window_end = datetime(2026, 7, 23, 0, 0, 0, tzinfo=tz)

    model = DashboardModel(
        team_name="test-team",
        report_date=date(2026, 7, 22),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        window_start=window_start,
        window_end=window_end,
    )
    assert model.window_start == window_start
    assert model.window_end == window_end


def test_dashboard_model_frozen() -> None:
    """DashboardModel은 frozen dataclass이다."""
    model = DashboardModel(
        team_name="test-team",
        report_date=date(2026, 7, 22),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
    )

    # frozen이므로 수정 불가능
    try:
        model.team_name = "modified"  # type: ignore
        raise AssertionError("frozen dataclass는 수정할 수 없어야 함")
    except AttributeError:
        pass
