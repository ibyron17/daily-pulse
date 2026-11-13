"""publish.py의 extract_summary_input_by_repo window 필드 테스트."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.models import DashboardModel
from pulse.publish import extract_summary_input_by_repo

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def mock_config() -> Config:
    """테스트용 Config."""
    return Config(
        team_name="테스트팀",
        repos=(),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=Path("reports"),
        data_dir=Path("data"),
        stagnation=StagnationThresholds(
            review_waiting_days=3,
            no_push_days=7,
        ),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


def test_extract_summary_includes_window_fields(mock_config: Config) -> None:
    """extract_summary_input_by_repo가 window_start/end를 포함한다."""
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=KST)
    window_start = datetime(2026, 7, 22, 12, 0, 0, tzinfo=KST)
    window_end = now

    model = DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 23),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        window_start=window_start,
        window_end=window_end,
    )

    result = extract_summary_input_by_repo(model)

    # window 필드가 ISO 형식 문자열로 포함되어야 함
    assert "window_start" in result
    assert "window_end" in result
    assert result["window_start"] == window_start.isoformat()
    assert result["window_end"] == window_end.isoformat()


def test_extract_summary_window_none() -> None:
    """window가 None이면 필드가 None이다."""
    model = DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 23),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        window_start=None,
        window_end=None,
    )

    result = extract_summary_input_by_repo(model)

    assert "window_start" in result
    assert "window_end" in result
    assert result["window_start"] is None
    assert result["window_end"] is None
