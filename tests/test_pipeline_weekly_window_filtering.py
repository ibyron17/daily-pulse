"""파이프라인 주간 경로의 window 필터링 테스트."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.grouper.core import filter_activities_to_window, group_activities
from pulse.models import CommitInfo, RepoActivity, RepoRef
from pulse.pipeline import run_pipeline
from pulse.renderer.assemble import build_dashboard_model

KST = ZoneInfo("Asia/Seoul")


def _make_test_config(tmp_path: Path) -> Config:
    """최소 테스트 Config."""
    return Config(
        team_name="테스트팀",
        repos=(
            RepoRef(
                provider="github",
                base_url="https://github.com",
                namespace="test",
                name="repo",
                web_url="https://github.com/test/repo",
            ),
        ),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


def test_weekly_grouping_filters_with_upper_bound() -> None:
    """(a) 상한보다 큰 커밋은 주간 그룹핑 결과에서 제외된다."""
    # Arrange
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=KST)
    repo_ref = RepoRef(
        provider="github",
        base_url="https://github.com",
        namespace="test",
        name="repo",
        web_url="https://github.com/test/repo",
    )

    # now 이전: 포함 가능
    commit_before = CommitInfo(
        sha="abc1",
        author_name="Alice",
        authored_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=KST),
        message="커밋 1",
        branch="feature",
        changed_files=("file.py",),
        web_url="https://github.com/test/repo/commit/abc1",
    )
    # now 이후: 상한 초과, 제외됨
    commit_after = CommitInfo(
        sha="abc2",
        author_name="Bob",
        authored_at=datetime(2026, 7, 24, 12, 0, 0, tzinfo=KST),
        message="커밋 2 (상한 초과)",
        branch="feature",
        changed_files=("file.py",),
        web_url="https://github.com/test/repo/commit/abc2",
    )

    activity = RepoActivity(
        repo=repo_ref,
        status="ok",
        failure_reason=None,
        commits=(commit_before, commit_after),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    config = Config(
        team_name="test",
        repos=(repo_ref,),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=Path("/tmp"),
        data_dir=Path("/tmp"),
        stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )

    # Act: 주간 필터링 (168h)
    weekly_activities = filter_activities_to_window((activity,), 168, now)
    weekly_groups, _, _, _ = group_activities(weekly_activities, config, now)

    # Assert: commit_before만 그룹에 포함되어야 함
    assert len(weekly_groups) == 1
    assert len(weekly_groups[0].commits) == 1
    assert weekly_groups[0].commits[0].sha == "abc1"  # 상한 이내


def test_weekly_dashboard_window_fields(tmp_path: Path) -> None:
    """(b) weekly_dashboard의 window_start와 window_end가 올바르게 계산된다."""
    # Arrange
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=KST)
    report_date = now.date()
    config = _make_test_config(tmp_path)
    config = config.__class__(
        team_name=config.team_name,
        repos=config.repos,
        lookback_hours=168,  # 주간용
        weekend_catchup=config.weekend_catchup,
        timezone_name=config.timezone_name,
        output_dir=config.output_dir,
        data_dir=config.data_dir,
        stagnation=config.stagnation,
        exclude_bot_authors=config.exclude_bot_authors,
        retention_days=config.retention_days,
        grouping_hints=config.grouping_hints,
    )

    # Act: 주간 대시보드 모델 생성
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

    # Assert: window_start = now - 168h, window_end = now
    expected_start = now - timedelta(hours=168)
    assert model.window_start == expected_start
    assert model.window_end == now


def test_pipeline_weekly_path_calls_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """배선 검증: pipeline이 주간 경로에서 filter_activities_to_window를 호출한다."""
    # Arrange
    from tests.conftest import make_repo_activity

    config = _make_test_config(tmp_path)
    monday_morning = datetime(2026, 7, 21, 8, 0, tzinfo=KST)  # 월요일
    filter_called = []

    # filter_activities_to_window 호출을 감시하기 위한 래퍼
    original_filter = filter_activities_to_window

    def spy_filter(
        activities: tuple[Any, ...], window_hours: int, now: datetime
    ) -> tuple[Any, ...]:
        filter_called.append(("weekly" if window_hours == 168 else "daily", window_hours))
        return original_filter(activities, window_hours, now)

    monkeypatch.setattr("pulse.pipeline.filter_activities_to_window", spy_filter)
    monkeypatch.setattr("pulse.pipeline.get_effective_now", lambda config: monday_morning)

    # 최소한의 수집 데이터
    def fake_collect(
        config: Config, now: datetime | None = None, save_snapshots: bool = True
    ) -> list[Any]:
        return [make_repo_activity()]

    monkeypatch.setattr("pulse.pipeline.collect_repos", fake_collect)

    # Act
    daily_dashboard, weekly_dashboard = run_pipeline(config)

    # Assert: filter_activities_to_window가 주간(168h)과 일간(24h 또는 72h) 모두 호출됨
    assert len(filter_called) >= 2
    # daily와 weekly 모두 필터링이 호출되어야 함
    hours_called = [hours for _, hours in filter_called]
    assert 24 in hours_called or 72 in hours_called  # 일간 (평일=24, 월요일=72)
    assert 168 in hours_called  # 주간
