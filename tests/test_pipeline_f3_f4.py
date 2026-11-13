"""파이프라인 F3, F4 통합 테스트 (주간 뷰, diff 필터링)."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from pulse.collector.snapshot import BranchSnapshot
from pulse.config import Config, GroupingHints, StagnationThresholds
from pulse.models import (
    CommitInfo,
    MergeRequestInfo,
    RepoActivity,
    RepoRef,
)
from pulse.pipeline import (
    _group_previous_activities,
    run_pipeline,
)
from pulse.weekly_branches import find_weekly_baseline_snapshots


@pytest.fixture
def base_config(tmp_path: Path) -> Config:
    """기본 설정."""
    return Config(
        team_name="테스트팀",
        repos=(
            RepoRef(
                provider="gitlab",
                base_url="http://test",
                namespace="test",
                name="repo",
                web_url="http://test/test/repo",
            ),
        ),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        stagnation=StagnationThresholds(
            review_waiting_days=3,
            no_push_days=7,
        ),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


def test_find_weekly_baseline_snapshots_found(base_config: Config) -> None:
    """주간 뷰의 기준 스냅샷들을 찾는다 (G3)."""
    # Arrange
    snapshot_dir = base_config.data_dir / "snapshots"
    current_date = date(2026, 7, 20)
    target_date = "2026-07-13"  # 7일 전

    # 7일 전 스냅샷 생성
    date_dir = snapshot_dir / target_date
    date_dir.mkdir(parents=True)
    repo_slug = base_config.repos[0].slug
    snapshot = BranchSnapshot(repo_slug, {"main", "develop"}, target_date)
    snapshot.save(snapshot_dir)

    # Act
    baseline_map, display_baseline = find_weekly_baseline_snapshots(base_config, current_date)

    # Assert
    assert repo_slug in baseline_map
    assert baseline_map[repo_slug] == date.fromisoformat(target_date)
    assert display_baseline == date.fromisoformat(target_date)


def test_find_weekly_baseline_snapshots_none_when_missing(
    base_config: Config,
) -> None:
    """스냅샷이 없을 때 None 반환 (G3)."""
    # Arrange
    current_date = date(2026, 7, 20)

    # Act
    baseline_map, display_baseline = find_weekly_baseline_snapshots(base_config, current_date)

    # Assert
    assert baseline_map == {}
    assert display_baseline is None


def test_group_previous_activities_applies_filter(tmp_path: Path) -> None:
    """이전 activities를 필터 범위로 재그룹핑 (F4)."""
    # Arrange
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)

    # 24시간 필터 범위 내/외 커밋 생성
    twelve_hours_ago = now - timedelta(hours=12)  # 24시간 창에 포함
    thirty_six_hours_ago = now - timedelta(hours=36)  # 24시간 창에 제외

    previous_activities = (
        RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test",
                namespace="test",
                name="repo",
                web_url="http://test/test/repo",
            ),
            status="ok",
            failure_reason=None,
            commits=(
                # 12시간 전 커밋 (24h 창에 포함)
                CommitInfo(
                    sha="commit1",
                    author_name="alice",
                    authored_at=twelve_hours_ago,
                    message="recent commit",
                    branch="feature/a",
                    changed_files=("a.py",),
                    web_url="http://test/commits/1",
                ),
                # 36시간 전 커밋 (24h 창에 제외)
                CommitInfo(
                    sha="commit2",
                    author_name="bob",
                    authored_at=thirty_six_hours_ago,
                    message="old commit",
                    branch="feature/b",
                    changed_files=("b.py",),
                    web_url="http://test/commits/2",
                ),
            ),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now,
            stale_branches=(),
        ),
    )

    config = Config(
        team_name="test",
        repos=(previous_activities[0].repo,),
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

    # Act: _group_previous_activities는 내부에서 collected_at 기준 lookback 계산
    # config의 lookback_hours가 사용됨 (현재 24)
    groups = _group_previous_activities(config, previous_activities)

    # Assert: 24시간 내 커밋만 그룹핑되었는지 확인
    all_commits: list[CommitInfo] = []
    for group in groups:
        all_commits.extend(group.commits)

    # 3일 전 커밋만 포함되어야 함 (10일 전은 제외)
    assert len(all_commits) == 1
    assert all_commits[0].sha == "commit1"


def test_run_pipeline_returns_both_dashboards_with_different_periods(
    base_config: Config,
) -> None:
    """파이프라인이 일간/주간 대시보드를 모두 반환하고, period 필드가 올바르다 (F3)."""
    # Arrange
    # base_config는 이미 tmp_path를 사용하도록 설정됨 (fixture에서)

    # Mock 설정: run_pipeline의 수집 부분을 mocking
    mock_activity = RepoActivity(
        repo=base_config.repos[0],
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(
            MergeRequestInfo(
                iid=1,
                title="Test MR",
                state="open",
                is_draft=False,
                labels=(),
                source_branch="feature/test",
                target_branch="main",
                author_name="alice",
                created_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
                merged_at=None,
                reviews=(),
                is_external=False,
                web_url="http://test/mr/1",
            ),
        ),
        collected_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        stale_branches=(),
    )

    with patch("pulse.pipeline._collect_activities", return_value=(mock_activity,)):
        # Act
        daily_dashboard, weekly_dashboard = run_pipeline(base_config)

    # Assert
    assert daily_dashboard.period == "daily"
    assert weekly_dashboard.period == "weekly"

    # 주간 대시보드가 자체 warnings를 가져야 함
    assert isinstance(weekly_dashboard.warnings, tuple)

    # 주간 신규 작업
    assert isinstance(weekly_dashboard.new_work, tuple)

    # baseline_date (주간 뷰에서는 설정될 수 있음, 없을 수도 있음)
    assert hasattr(weekly_dashboard, "new_work_baseline_date")
