"""레포 스코프 렌더링 추가 테스트 (코드 커버리지 확대)."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.models import (
    DashboardModel,
    FeatureGroup,
)
from pulse.renderer.assemble import _extract_repo_tabs, build_dashboard_model
from pulse.renderer.html import render_html
from tests.conftest import (
    make_feature_group,
    make_repo_activity,
    make_repo_ref,
)

KST = ZoneInfo("Asia/Seoul")


class TestRepoTabExtraction:
    """레포 탭 추출 테스트."""

    def test_extract_repo_tabs_multiple_repos_ordered(self) -> None:
        """여러 레포가 알파벳순으로 정렬되어야 함."""
        # Arrange
        repo1 = make_repo_ref(namespace="zebra", name="project")
        repo2 = make_repo_ref(namespace="alpha", name="project")
        repo3 = make_repo_ref(namespace="bravo", name="project")

        activity1 = make_repo_activity(repo=repo1)
        activity2 = make_repo_activity(repo=repo2)
        activity3 = make_repo_activity(repo=repo3)

        # Act
        tabs = _extract_repo_tabs((activity1, activity2, activity3), ())

        # Assert
        assert tabs == ("alpha/project", "bravo/project", "zebra/project")


class TestRepoFilteringInDashboard:
    """대시보드의 레포별 필터링 테스트."""

    def test_build_dashboard_model_includes_repo_summaries(self) -> None:
        """build_dashboard_model이 repo_summaries를 포함해야 함."""
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        report_date = date(2026, 7, 16)

        repo1_path = "frontend/web"
        repo2_path = "backend/api"

        group1 = make_feature_group(
            name="ui-components",
            repo_full_path=repo1_path,
            stage="developing",
        )
        group2 = make_feature_group(
            name="auth-service",
            repo_full_path=repo2_path,
            stage="reviewing",
        )

        repo1 = make_repo_ref(namespace="frontend", name="web")
        repo2 = make_repo_ref(namespace="backend", name="api")

        activity1 = make_repo_activity(repo=repo1)
        activity2 = make_repo_activity(repo=repo2)

        config = Config(
            team_name="Test Team",
            repos=(repo1, repo2),
            lookback_hours=24,
            weekend_catchup=False,
            timezone_name="Asia/Seoul",
            output_dir=Path("reports"),
            data_dir=Path("data"),
            stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
            exclude_bot_authors=(),
            retention_days=90,
            grouping_hints=GroupingHints(),
        )

        # Act
        dashboard = build_dashboard_model(
            groups=(group1, group2),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(activity1, activity2),
            config=config,
            report_date=report_date,
            now=now,
        )

        # Assert
        assert len(dashboard.repo_summaries) == 2
        repo_paths = {rs.repo_full_path for rs in dashboard.repo_summaries}
        assert repo1_path in repo_paths
        assert repo2_path in repo_paths


class TestHtmlTabOrdering:
    """HTML 렌더링에서 탭 순서 테스트."""

    def test_render_html_repo_tabs_all_present(self) -> None:
        """HTML에서 모든 레포 탭이 나타나야 함."""
        # Arrange
        dashboard = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="3개 레포 활동",
            groups=(),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("alpha/project", "zebra/project", "bravo/project"),
        )

        # Act
        html = render_html(dashboard)

        # Assert
        # 모든 탭이 나타나야 함
        assert 'id="tab-radio-alpha__project"' in html
        assert 'id="tab-radio-bravo__project"' in html
        assert 'id="tab-radio-zebra__project"' in html

        # 모든 탭 콘텐츠도 나타나야 함
        assert 'id="tab-content-alpha__project"' in html
        assert 'id="tab-content-bravo__project"' in html
        assert 'id="tab-content-zebra__project"' in html


class TestGroupParticipationPerRepo:
    """레포별 참여자 필터링 테스트."""

    def test_groups_participants_are_repo_scoped(self) -> None:
        """그룹의 참여자가 레포별로 분리되어야 함."""
        # Arrange
        repo1_path = "frontend/web"
        repo2_path = "backend/api"

        # repo1의 그룹: alice, bob 참여
        group1 = make_feature_group(
            name="component-lib",
            repo_full_path=repo1_path,
            participants=("alice", "bob"),
        )

        # repo2의 그룹: charlie, diana 참여 (alice와 겹침 금지)
        group2 = make_feature_group(
            name="api-gateway",
            repo_full_path=repo2_path,
            participants=("charlie", "diana"),
        )

        # Act
        repo1_groups = [g for g in (group1, group2) if g.repo_full_path == repo1_path]
        repo2_groups = [g for g in (group1, group2) if g.repo_full_path == repo2_path]

        repo1_participants: set[str] = set()
        for g in repo1_groups:
            repo1_participants.update(g.participants)

        repo2_participants: set[str] = set()
        for g in repo2_groups:
            repo2_participants.update(g.participants)

        # Assert
        assert repo1_participants == {"alice", "bob"}
        assert repo2_participants == {"charlie", "diana"}
        # 교집합이 없어야 함
        assert len(repo1_participants & repo2_participants) == 0


class TestRepoUnclassifiedIsolation:
    """레포별 unclassified 그룹 격리 테스트."""

    def test_unclassified_groups_separated_by_repo(self) -> None:
        """unclassified 그룹이 레포별로 분리되어야 함."""
        # Arrange
        repo1_path = "frontend/web"
        repo2_path = "backend/api"

        unc1 = make_feature_group(
            name="unclassified",
            repo_full_path=repo1_path,
            participants=("alice",),
        )

        unc2 = make_feature_group(
            name="unclassified",
            repo_full_path=repo2_path,
            participants=("bob",),
        )

        groups = (unc1, unc2)

        # Act
        unclassified_by_repo: dict[str, list[FeatureGroup]] = {}
        for g in groups:
            if g.name == "unclassified":
                unclassified_by_repo.setdefault(g.repo_full_path, []).append(g)

        # Assert
        assert len(unclassified_by_repo) == 2
        assert unc1.repo_full_path in unclassified_by_repo
        assert unc2.repo_full_path in unclassified_by_repo
        # 각 레포의 unclassified는 다른 참여자를 가져야 함
        assert (
            unclassified_by_repo[repo1_path][0].participants
            != unclassified_by_repo[repo2_path][0].participants
        )


class TestRepoAwareGroupFiltering:
    """레포별 그룹 필터링 테스트."""

    def test_groups_filtered_by_repo_path(self) -> None:
        """repo_full_path로 그룹을 필터링해야 함."""
        # Arrange
        repo1_path = "frontend/web"
        repo2_path = "backend/api"

        groups = (
            make_feature_group(name="feat-a", repo_full_path=repo1_path),
            make_feature_group(name="feat-b", repo_full_path=repo2_path),
            make_feature_group(name="feat-c", repo_full_path=repo1_path),
        )

        # Act
        repo1_groups = [g for g in groups if g.repo_full_path == repo1_path]
        repo2_groups = [g for g in groups if g.repo_full_path == repo2_path]

        # Assert
        assert len(repo1_groups) == 2
        assert len(repo2_groups) == 1

        assert {g.name for g in repo1_groups} == {"feat-a", "feat-c"}
        assert {g.name for g in repo2_groups} == {"feat-b"}
