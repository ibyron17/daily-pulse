"""render_diff 단위 테스트 (3개 케이스)."""

from datetime import date

from pulse.models import DiffSummary, GroupStageChange
from pulse.renderer.sections import render_diff


def test_render_diff_with_changes() -> None:
    """신규 그룹 + 단계 변화 렌더링."""
    diff = DiffSummary(
        compared_to=date(2026, 7, 15),
        new_groups=(("test/repo", "에디터"),),
        stage_changes=(
            GroupStageChange(
                group_name="캐시",
                previous_stage="developing",
                current_stage="reviewing",
                repo_full_path="test/repo",
            ),
        ),
    )

    html = render_diff(diff)

    # 비교 기준 날짜 표기
    assert "2026-07-15" in html or "2026-07-15" in html.replace("-", "")
    # 신규 그룹
    assert "에디터" in html
    # 단계 변화
    assert "캐시" in html
    # 빈 문자열 아님
    assert html


def test_render_diff_none_returns_empty() -> None:
    """diff=None 시 빈 문자열."""
    html = render_diff(None)
    assert html == ""


def test_render_diff_no_changes_returns_empty() -> None:
    """신규/변화 없음 시 빈 문자열."""
    diff = DiffSummary(
        compared_to=date(2026, 7, 15),
        new_groups=(),
        stage_changes=(),
    )

    html = render_diff(diff)

    assert html == ""


def test_render_diff_repo_filtered() -> None:
    """render_diff가 repo_filter로 레포별 변화만 표시해야 함."""
    # Arrange
    diff = DiffSummary(
        compared_to=date(2026, 7, 15),
        new_groups=(
            ("sample-group/sample-ui", "에디터"),
            ("backend/api", "인증"),
        ),
        stage_changes=(
            GroupStageChange(
                group_name="캐시",
                previous_stage="developing",
                current_stage="reviewing",
                repo_full_path="sample-group/sample-ui",
            ),
            GroupStageChange(
                group_name="결제",
                previous_stage="reviewing",
                current_stage="merged",
                repo_full_path="backend/api",
            ),
        ),
    )

    # Act
    # sample-group/sample-ui 레포만 필터링
    html_repo1 = render_diff(diff, repo_filter="sample-group/sample-ui")
    # backend/api 레포만 필터링
    html_repo2 = render_diff(diff, repo_filter="backend/api")
    # 전체 (필터 없음)
    html_all = render_diff(diff, repo_filter=None)

    # Assert
    # repo1 (sample-group/sample-ui): "에디터", "캐시" 포함
    assert "에디터" in html_repo1, "Repo1 should contain '에디터' group"
    assert "캐시" in html_repo1, "Repo1 should contain '캐시' stage change"
    # "결제"는 포함되면 안 됨
    assert "결제" not in html_repo1, "Repo1 should not contain '결제' from other repo"

    # repo2 (backend/api): "인증", "결제" 포함
    assert "인증" in html_repo2, "Repo2 should contain '인증' group"
    assert "결제" in html_repo2, "Repo2 should contain '결제' stage change"
    # "캐시"는 포함되면 안 됨
    assert "캐시" not in html_repo2, "Repo2 should not contain '캐시' from other repo"

    # 전체 (필터 없음): 모든 것을 포함
    assert "에디터" in html_all and "인증" in html_all
    assert "캐시" in html_all and "결제" in html_all
