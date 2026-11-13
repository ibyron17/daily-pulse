"""섹션 렌더링 필터링 로직 테스트."""

from zoneinfo import ZoneInfo

from pulse.models import (
    FeatureGroup,
    NewWorkSignal,
)
from pulse.renderer.sections import (
    render_feature_cards,
    render_new_work,
)

KST = ZoneInfo("Asia/Seoul")


class TestRenderFeatureCardsFilter:
    """render_feature_cards 필터링 테스트."""

    def test_render_feature_cards_with_repo_filter_includes_matching(self) -> None:
        """repo_filter가 있으면 일치하는 그룹만 포함."""
        # Arrange
        group1 = FeatureGroup(
            name="API 기능",
            source_rule="hints",
            evidence="feature/api",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("feature/api",),
            participants=("alice",),
            branches=(),
        )
        group2 = FeatureGroup(
            name="UI 기능",
            source_rule="hints",
            evidence="feature/ui",
            stage="reviewing",
            repo_full_path="frontend/web",
            commits=(),
            merge_requests=(),
            branch_names=("feature/ui",),
            participants=("bob",),
            branches=(),
        )

        # Act
        html = render_feature_cards((group1, group2), repo_filter="backend/api")

        # Assert (필터링은 그룹 이름으로 검증; 분류 근거는 카드에 표시하지 않음)
        assert "API 기능" in html
        assert "UI 기능" not in html

    def test_render_feature_cards_with_repo_filter_none_returns_all(self) -> None:
        """repo_filter=None이면 모든 그룹 포함."""
        # Arrange
        group1 = FeatureGroup(
            name="API 기능",
            source_rule="hints",
            evidence="feature/api",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("feature/api",),
            participants=("alice",),
            branches=(),
        )
        group2 = FeatureGroup(
            name="UI 기능",
            source_rule="hints",
            evidence="feature/ui",
            stage="reviewing",
            repo_full_path="frontend/web",
            commits=(),
            merge_requests=(),
            branch_names=("feature/ui",),
            participants=("bob",),
            branches=(),
        )

        # Act
        html = render_feature_cards((group1, group2), repo_filter=None)

        # Assert
        assert "API 기능" in html
        assert "UI 기능" in html

    def test_render_feature_cards_multi_repo_group_included_in_both_tabs(self) -> None:
        """각 그룹은 자신의 repo 탭에만 표시."""
        # Arrange
        group_api = FeatureGroup(
            name="API 기능",
            source_rule="hints",
            evidence="api",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("feat/api",),
            participants=("alice",),
            branches=(),
        )
        group_worker = FeatureGroup(
            name="백그라운드 잡",
            source_rule="hints",
            evidence="worker",
            stage="developing",
            repo_full_path="backend/worker",
            commits=(),
            merge_requests=(),
            branch_names=("feat/job",),
            participants=("bob",),
            branches=(),
        )

        # Act - backend/api 탭
        html_api = render_feature_cards((group_api, group_worker), repo_filter="backend/api")
        # Act - backend/worker 탭
        html_worker = render_feature_cards((group_api, group_worker), repo_filter="backend/worker")
        # Act - frontend 탭 (포함 안 됨)
        html_frontend = render_feature_cards((group_api, group_worker), repo_filter="frontend/web")

        # Assert
        assert "API 기능" in html_api
        assert "백그라운드 잡" not in html_api
        assert "백그라운드 잡" in html_worker
        assert "API 기능" not in html_worker
        assert html_frontend == ""

    def test_render_feature_cards_includes_section_description(self) -> None:
        """섹션 설명이 포함되는지 검증."""
        # Arrange
        group = FeatureGroup(
            name="API 기능",
            source_rule="hints",
            evidence="feature/api",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("feature/api",),
            participants=("alice",),
            branches=(),
        )

        # Act
        html = render_feature_cards((group,))

        # Assert
        assert "현재 진행 중인 프로젝트/기능" in html
        assert "section-description" in html

    def test_render_feature_cards_unclassified_hint_included(self) -> None:
        """unclassified 그룹에 힌트가 포함되는지 검증."""
        # Arrange
        group = FeatureGroup(
            name="분류되지 않은 작업",
            source_rule="unclassified",
            evidence="manual",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("random-branch",),
            participants=("alice",),
            branches=(),
        )

        # Act
        html = render_feature_cards((group,))

        # Assert
        assert "이 기능은 규칙으로 분류되지 않았습니다" in html
        assert "grouping_hints" in html
        assert "unclassified-hint" in html


class TestRenderNewWorkFilter:
    """render_new_work 필터링 테스트."""

    def test_render_new_work_with_repo_filter_includes_matching(self) -> None:
        """repo_filter가 있으면 일치하는 작업만 포함."""
        # Arrange
        signal1 = NewWorkSignal(
            title="API 작업 시작",
            repo_full_path="backend/api",
            branch_or_mr="feature/api",
            web_url="http://test.local/backend/api/-/branches/feature/api",
        )
        signal2 = NewWorkSignal(
            title="UI 작업 시작",
            repo_full_path="frontend/web",
            branch_or_mr="feature/ui",
            web_url="http://test.local/frontend/web/-/branches/feature/ui",
        )

        # Act
        html = render_new_work((signal1, signal2), repo_filter="backend/api")

        # Assert
        assert "API 작업 시작" in html
        assert "UI 작업 시작" not in html

    def test_render_new_work_with_repo_filter_none_returns_all(self) -> None:
        """repo_filter=None이면 모든 작업 포함."""
        # Arrange
        signal1 = NewWorkSignal(
            title="API 작업 시작",
            repo_full_path="backend/api",
            branch_or_mr="feature/api",
            web_url="http://test.local/backend/api/-/branches/feature/api",
        )
        signal2 = NewWorkSignal(
            title="UI 작업 시작",
            repo_full_path="frontend/web",
            branch_or_mr="feature/ui",
            web_url="http://test.local/frontend/web/-/branches/feature/ui",
        )

        # Act
        html = render_new_work((signal1, signal2), repo_filter=None)

        # Assert
        assert "API 작업 시작" in html
        assert "UI 작업 시작" in html

    def test_render_new_work_includes_section_description(self) -> None:
        """섹션 설명이 포함되는지 검증."""
        # Arrange
        signal = NewWorkSignal(
            title="새 작업 시작",
            repo_full_path="backend/api",
            branch_or_mr="feature/new",
            web_url="http://test.local/backend/api/-/branches/feature/new",
        )

        # Act
        html = render_new_work((signal,))

        # Assert
        assert "직전 수집 이후 새로 생긴 브랜치와, 조회 기간 내 생성된 MR입니다." in html
        assert "section-description" in html
