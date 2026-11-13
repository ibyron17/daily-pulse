"""repo 탭 추출 로직 테스트."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.models import RepoActivity, RepoRef
from pulse.renderer.assemble import _extract_repo_tabs, build_dashboard_model

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


@pytest.fixture
def now_fixture() -> datetime:
    """테스트용 현재 시각."""
    return datetime(2026, 7, 16, 10, 0, 0, tzinfo=KST)


class TestExtractRepoTabs:
    """_extract_repo_tabs 함수 테스트."""

    def test_extract_repo_tabs_single_repo(self) -> None:
        """단일 레포 추출."""
        # Arrange
        activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="org",
                name="repo",
                web_url="http://test.local/org/repo",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
            stale_branches=(),
        )

        # Act
        repos = _extract_repo_tabs((activity,), ())

        # Assert
        assert repos == ("org/repo",)

    def test_extract_repo_tabs_multiple_repos_sorted(self) -> None:
        """다중 레포 정렬 추출."""
        # Arrange
        activity1 = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="backend",
                name="api",
                web_url="http://test.local/backend/api",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
            stale_branches=(),
        )
        activity2 = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="backend",
                name="shared",
                web_url="http://test.local/backend/shared",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
            stale_branches=(),
        )

        # Act
        repos = _extract_repo_tabs((activity2, activity1), ())

        # Assert
        assert repos == ("backend/api", "backend/shared")

    def test_extract_repo_tabs_empty(self) -> None:
        """활동이 없으면 빈 튜플."""
        # Act
        repos = _extract_repo_tabs((), ())

        # Assert
        assert repos == ()

    def test_extract_repo_tabs_includes_failed_repos(self) -> None:
        """수집 실패 레포도 포함."""
        # Arrange
        activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="org",
                name="repo",
                web_url="http://test.local/org/repo",
            ),
            status="failed",
            failure_reason="Network error",
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
            stale_branches=(),
        )

        # Act
        repos = _extract_repo_tabs((activity,), ())

        # Assert
        assert repos == ("org/repo",)

    def test_build_dashboard_model_includes_repos(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """DashboardModel에 repos가 포함되는지 검증."""
        # Arrange
        activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="org",
                name="repo",
                web_url="http://test.local/org/repo",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now_fixture,
            stale_branches=(),
        )

        # Act
        model = build_dashboard_model(
            groups=(),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(activity,),
            config=mock_config,
            report_date=date(2026, 7, 16),
            now=now_fixture,
        )

        # Assert
        assert model.repos == ("org/repo",)

    def test_build_dashboard_model_repos_multiple_repos(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """DashboardModel에 다중 레포가 정렬되어 포함되는지 검증."""
        # Arrange
        activity1 = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="frontend",
                name="web",
                web_url="http://test.local/frontend/web",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now_fixture,
            stale_branches=(),
        )
        activity2 = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="backend",
                name="api",
                web_url="http://test.local/backend/api",
            ),
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now_fixture,
            stale_branches=(),
        )

        # Act
        model = build_dashboard_model(
            groups=(),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(activity1, activity2),
            config=mock_config,
            report_date=date(2026, 7, 16),
            now=now_fixture,
        )

        # Assert
        assert model.repos == ("backend/api", "frontend/web")
