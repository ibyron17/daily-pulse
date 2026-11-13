"""모델 조립 로직 테스트 (Phase 4 — assemble.py)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.models import (
    CommitInfo,
    FeatureGroup,
    MergeRequestInfo,
    RepoActivity,
    RepoRef,
)
from pulse.renderer.assemble import (
    build_dashboard_model,
)

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def mock_config() -> Config:
    """테스트용 Config."""
    from pathlib import Path

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


class TestBuildDashboardModelBasics:
    """기본 조립 테스트."""

    def test_build_dashboard_model_with_now_injection(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """now 주입이 정상 작동하는지 검증."""
        # Arrange
        commit_created = now_fixture - timedelta(days=5)
        commit = CommitInfo(
            sha="abc123",
            author_name="test-user",
            authored_at=commit_created,
            message="test commit",
            branch="develop",
            changed_files=("src/test.ts",),
            web_url="http://test.local/test/repo/-/commit/abc123",
        )
        mr = MergeRequestInfo(
            iid=1,
            title="test MR",
            state="open",
            is_draft=False,
            labels=(),
            source_branch="feature/test",
            target_branch="develop",
            author_name="test-user",
            created_at=now_fixture - timedelta(days=7),
            updated_at=now_fixture - timedelta(days=1),
            merged_at=None,
            reviews=(),
            is_external=False,
            web_url="http://test.local/test/repo/-/merge_requests/1",
        )
        group = FeatureGroup(
            name="테스트 기능",
            source_rule="hints",
            evidence="hint matched",
            stage="developing",
            repo_full_path="test/repo",
            commits=(commit,),
            merge_requests=(mr,),
            branch_names=("feature/test",),
            participants=("test-user",),
            branches=(),
        )

        # Act
        model = build_dashboard_model(
            groups=(group,),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=mock_config,
            report_date=date(2026, 7, 16),
            now=now_fixture,
        )

        # Assert
        assert model.team_name == "테스트팀"
        assert model.report_date == date(2026, 7, 16)
        assert model.lookback_hours == 24
        assert len(model.groups) == 1


class TestAssembleFailureWarnings:
    """수집 실패 경고 조립 테스트."""

    def test_collect_failure_warnings_converts_failed_activity(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """실패한 activity를 WarningSignal로 변환하는지 검증."""
        # Arrange
        activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="test",
                name="repo",
                web_url="http://test.local/test/repo",
            ),
            status="failed",
            failure_reason="401 Unauthorized",
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
        assert any(w.kind == "collection_failure" for w in model.warnings)
        failure_warning = next(w for w in model.warnings if w.kind == "collection_failure")
        assert "test/repo" in failure_warning.title
        assert "401 Unauthorized" in failure_warning.description

    def test_collect_failure_warnings_empty_when_all_ok(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """모든 activity가 성공이면 failure warning이 없는지 검증."""
        # Arrange
        activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="test",
                name="repo",
                web_url="http://test.local/test/repo",
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
        assert not any(w.kind == "collection_failure" for w in model.warnings)


class TestAssembleSummaryLine:
    """요약 라인 조립 테스트."""

    def test_assemble_summary_line_includes_group_count(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """요약이 그룹 수를 포함하는지 검증."""
        # Arrange
        group1 = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            branches=(),
        )
        group2 = FeatureGroup(
            name="기능2",
            source_rule="hints",
            evidence="test",
            stage="merged",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            branches=(),
        )
        group3 = FeatureGroup(
            name="기능3",
            source_rule="hints",
            evidence="test",
            stage="reviewing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            branches=(),
        )

        # Act
        model = build_dashboard_model(
            groups=(group1, group2, group3),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=mock_config,
            report_date=date(2026, 7, 16),
            now=now_fixture,
        )

        # Assert
        assert "3개 프로젝트" in model.summary_line


class TestBuildDashboardModelWithFailures:
    """실패 처리 포함 통합 테스트."""

    def test_build_dashboard_model_includes_failure_warnings(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """build_dashboard_model이 수집 실패 경고를 자동으로 추가하는지 검증."""
        # Arrange
        group = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="good/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            branches=(),
        )
        good_activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="good",
                name="repo",
                web_url="http://test.local/good/repo",
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
        bad_activity = RepoActivity(
            repo=RepoRef(
                provider="gitlab",
                base_url="http://test.local",
                namespace="bad",
                name="repo",
                web_url="http://test.local/bad/repo",
            ),
            status="failed",
            failure_reason="403 Forbidden",
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
            groups=(group,),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(good_activity, bad_activity),
            config=mock_config,
            report_date=date(2026, 7, 16),
            now=now_fixture,
        )

        # Assert
        assert any(w.kind == "collection_failure" for w in model.warnings)
        failure_warning = next(w for w in model.warnings if w.kind == "collection_failure")
        assert "bad/repo" in failure_warning.title

    def test_build_dashboard_model_report_date_from_input(
        self, mock_config: Config, now_fixture: datetime
    ) -> None:
        """report_date가 입력값으로부터 정확히 반영되는지 검증."""
        # Arrange
        report_date = date(2026, 7, 20)

        # Act
        model = build_dashboard_model(
            groups=(),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=mock_config,
            report_date=report_date,
            now=now_fixture,
        )

        # Assert
        assert model.report_date == report_date
