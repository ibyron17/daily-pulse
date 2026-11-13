"""레포별 요약 라인 테스트 (신규 테스트 - test c)."""

from pulse.renderer.assemble import _assemble_summary_line_for_repo
from tests.conftest import (
    make_feature_group,
    make_warning_signal,
)


class TestAssembleSummaryLinePerRepo:
    """_assemble_summary_line_for_repo 레포별 필터링 테스트."""

    def test_assemble_summary_line_for_repo_filters(self) -> None:
        """다른 레포의 그룹과 경고를 필터링해야 함."""
        # Arrange
        repo1_path = "sample-group/sample-ui"
        repo2_path = "backend/api"

        # 레포 1의 그룹
        group1 = make_feature_group(
            name="feature1",
            repo_full_path=repo1_path,
            stage="merged",
        )

        # 레포 2의 그룹
        group2 = make_feature_group(
            name="feature2",
            repo_full_path=repo2_path,
            stage="developing",
        )

        # 레포 1의 경고
        warning1 = make_warning_signal(
            kind="stale_mr",
            title="Stale MR in repo1",
            repo_full_path=repo1_path,
        )

        # 레포 2의 경고
        warning2 = make_warning_signal(
            kind="stale_branch",
            title="Stale branch in repo2",
            repo_full_path=repo2_path,
        )

        groups = (group1, group2)
        warnings = (warning1, warning2)

        # Act
        repo1_summary = _assemble_summary_line_for_repo(groups, warnings, repo_full_path=repo1_path)
        repo2_summary = _assemble_summary_line_for_repo(groups, warnings, repo_full_path=repo2_path)

        # Assert
        # repo1 요약: 1개 프로젝트 (merged), MR 1건 머지, 주의 1건
        assert "1개 프로젝트" in repo1_summary
        assert "MR 1건 머지" in repo1_summary  # merged stage

        # repo2 요약: 1개 프로젝트 (developing), 주의 1건
        assert "1개 프로젝트" in repo2_summary
        assert "주의 1건" in repo2_summary

        # repo1과 repo2 요약이 달라야 함
        assert repo1_summary != repo2_summary, "Different repos should produce different summaries"

    def test_assemble_summary_line_global_summary(self) -> None:
        """repo_full_path=None일 때 전체 요약을 생성해야 함."""
        # Arrange
        repo1_path = "sample-group/sample-ui"
        repo2_path = "backend/api"

        group1 = make_feature_group(
            name="feature1",
            repo_full_path=repo1_path,
            stage="merged",
        )

        group2 = make_feature_group(
            name="feature2",
            repo_full_path=repo2_path,
            stage="developing",
        )

        warning1 = make_warning_signal(repo_full_path=repo1_path)
        warning2 = make_warning_signal(repo_full_path=repo2_path)

        groups = (group1, group2)
        warnings = (warning1, warning2)

        # Act
        global_summary = _assemble_summary_line_for_repo(groups, warnings, repo_full_path=None)

        # Assert
        # 전체 요약: 2개 프로젝트, MR 1건 머지, 주의 2건
        assert "2개 프로젝트" in global_summary
        assert "MR 1건 머지" in global_summary
        assert "주의 2건" in global_summary
