"""renderer/assemble.py의 build_dashboard_model window_start/end 계산 테스트."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.renderer.assemble import build_dashboard_model

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


def test_build_dashboard_model_calculates_window_start_end(mock_config: Config) -> None:
    """build_dashboard_model이 window_start/end를 계산해서 저장한다."""
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=KST)
    report_date = date(2026, 7, 23)

    model = build_dashboard_model(
        groups=(),
        warnings=(),
        new_work=(),
        unclassified_ratio=0.0,
        activities=(),
        config=mock_config,
        report_date=report_date,
        now=now,
        diff=None,
        period="daily",
    )

    # window_start = now - 24h (config.lookback_hours)
    expected_start = now - timedelta(hours=24)
    assert model.window_start == expected_start
    assert model.window_end == now


def test_build_dashboard_model_window_hours_168(mock_config: Config) -> None:
    """주간 뷰(168h)의 window_start/end를 확인한다."""
    from dataclasses import replace

    now = datetime(2026, 7, 28, 0, 0, 0, tzinfo=KST)
    report_date = date(2026, 7, 28)

    # config를 주간 모드로 업데이트
    config = replace(mock_config, lookback_hours=168)

    model = build_dashboard_model(
        groups=(),
        warnings=(),
        new_work=(),
        unclassified_ratio=0.0,
        activities=(),
        config=config,
        report_date=report_date,
        now=now,
        diff=None,
        period="weekly",
    )

    # window_start = now - 168h (7일)
    expected_start = now - timedelta(hours=168)
    assert model.window_start == expected_start
    assert model.window_end == now


def test_weekly_histogram_ends_at_window_end_not_at_report_date(mock_config: Config) -> None:
    """주간 막대는 창 끝(now) 날짜까지 7일이다 — 이름표가 창 뒤 날짜여도 벗어나지 않는다."""
    from dataclasses import replace

    from tests.conftest import make_commit, make_feature_group

    window_end = datetime(2026, 10, 5, 0, 0, 0, tzinfo=KST)  # 지난주 창의 끝(월요일 00:00)
    commits = (
        make_commit(sha="sha-0930", authored_at=datetime(2026, 9, 30, 10, 0, tzinfo=KST)),
        make_commit(sha="sha-1005", authored_at=datetime(2026, 10, 5, 10, 0, tzinfo=KST)),
        make_commit(sha="sha-1006", authored_at=datetime(2026, 10, 6, 10, 0, tzinfo=KST)),
    )
    group = make_feature_group(name="weekly-feature", commits=commits)

    model = build_dashboard_model(
        groups=(group,),
        warnings=(),
        new_work=(),
        unclassified_ratio=0.0,
        activities=(),
        config=replace(mock_config, lookback_hours=168),
        report_date=date(2026, 10, 6),  # 발행일(화요일) — 창 끝보다 하루 뒤
        now=window_end,
        diff=None,
        period="weekly",
        weekly_histogram_map=None,
    )

    histogram = dict(model.groups[0].daily_commit_counts)
    assert list(histogram)[0] == "2026-09-29"
    assert list(histogram)[-1] == "2026-10-05"
    assert histogram["2026-09-30"] == 1
    assert histogram["2026-10-05"] == 1
    assert "2026-10-06" not in histogram  # 10/6 커밋은 세지 않는다
