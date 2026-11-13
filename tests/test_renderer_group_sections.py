"""AI 제목/분석 렌더링 및 경고 그룹화 테스트."""

from pulse.models import WarningSignal
from pulse.renderer.sections import (
    render_group_ai_title,
    render_group_analysis,
    render_warnings_grouped,
)


def test_render_group_ai_title_basic() -> None:
    """render_group_ai_title이 제목을 렌더링한다."""
    title = "인증 시스템 리팩토링"

    result = render_group_ai_title(title)

    assert 'class="group-ai-title"' in result
    assert "<strong>" in result
    assert "인증 시스템 리팩토링" in result


def test_render_group_ai_title_empty_string() -> None:
    """render_group_ai_title이 빈 문자열을 무시한다."""
    result = render_group_ai_title("")

    assert result == ""


def test_render_group_ai_title_none() -> None:
    """render_group_ai_title이 None을 무시한다."""
    result = render_group_ai_title(None)

    assert result == ""


def test_render_group_ai_title_whitespace() -> None:
    """render_group_ai_title이 공백만 있는 문자열을 무시한다."""
    result = render_group_ai_title("   ")

    assert result == ""


def test_render_group_ai_title_escaping() -> None:
    """render_group_ai_title이 HTML을 escape한다."""
    title = "테스트 <script>alert('xss')</script>"

    result = render_group_ai_title(title)

    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_render_group_analysis_basic() -> None:
    """render_group_analysis가 분석을 렌더링한다."""
    analysis = "현재 인증 모듈을 리팩토링 중입니다."

    result = render_group_analysis(analysis)

    assert 'class="group-analysis"' in result
    assert "현재 인증 모듈을 리팩토링 중입니다." in result


def test_render_group_analysis_empty_string() -> None:
    """render_group_analysis가 빈 문자열을 무시한다."""
    result = render_group_analysis("")

    assert result == ""


def test_render_group_analysis_none() -> None:
    """render_group_analysis가 None을 무시한다."""
    result = render_group_analysis(None)

    assert result == ""


def test_render_group_analysis_whitespace() -> None:
    """render_group_analysis가 공백만 있는 문자열을 무시한다."""
    result = render_group_analysis("   \n  ")

    assert result == ""


def test_render_group_analysis_escaping() -> None:
    """render_group_analysis가 HTML을 escape한다."""
    analysis = "분석: <p>태그</p> & 특수문자"

    result = render_group_analysis(analysis)

    assert "<p>" not in result
    assert "&lt;p&gt;" in result
    assert "&amp;" in result


def test_render_warnings_grouped_basic() -> None:
    """render_warnings_grouped가 kind별로 경고를 그룹화한다."""
    warnings = (
        WarningSignal(
            kind="stale_mr",
            title="PR #1 정체",
            description="3일 이상",
            days=3,
            web_url="",
            repo_full_path="org/repo",
        ),
        WarningSignal(
            kind="stale_mr",
            title="PR #2 정체",
            description="5일 이상",
            days=5,
            web_url="",
            repo_full_path="org/repo",
        ),
        WarningSignal(
            kind="stale_branch",
            title="develop 방치",
            description="7일 이상",
            days=7,
            web_url="",
            repo_full_path="org/repo",
        ),
    )

    result = render_warnings_grouped(warnings)

    # 요약 섹션 확인
    assert 'class="warning-summary"' in result
    assert "정체된 MR" in result
    assert "(2)" in result
    assert "방치된 브랜치" in result
    assert "(1)" in result

    # 상세 섹션 확인
    assert 'class="warning-group"' in result
    assert '<details class="warning-group">' in result


def test_render_warnings_grouped_empty() -> None:
    """render_warnings_grouped가 빈 경고를 무시한다."""
    result = render_warnings_grouped(())

    assert result == ""


def test_render_warnings_grouped_repo_filter() -> None:
    """render_warnings_grouped가 레포 필터를 적용한다."""
    warnings = (
        WarningSignal(
            kind="stale_mr",
            title="PR #1",
            description="",
            days=3,
            web_url="",
            repo_full_path="org/repo-a",
        ),
        WarningSignal(
            kind="stale_mr",
            title="PR #2",
            description="",
            days=5,
            web_url="",
            repo_full_path="org/repo-b",
        ),
    )

    result = render_warnings_grouped(warnings, repo_filter="org/repo-a")

    # repo-a의 경고만 포함
    assert "PR #1" in result
    assert "PR #2" not in result
    assert "(1)" in result


def test_render_warnings_grouped_kind_order() -> None:
    """render_warnings_grouped가 kind 순서를 유지한다."""
    warnings = (
        WarningSignal(
            kind="hotfix_commit",
            title="Hotfix",
            description="",
            days=1,
            web_url="",
            repo_full_path="org/repo",
        ),
        WarningSignal(
            kind="stale_mr",
            title="정체 MR",
            description="",
            days=3,
            web_url="",
            repo_full_path="org/repo",
        ),
        WarningSignal(
            kind="revert_commit",
            title="Revert",
            description="",
            days=2,
            web_url="",
            repo_full_path="org/repo",
        ),
    )

    result = render_warnings_grouped(warnings)

    # WARNING_KIND_LABELS 순서: stale_mr, stale_branch, revert_commit, hotfix_commit
    # <summary> 태그 내의 순서로 비교 (요약 섹션은 동일 kind가 먼저 나타남)
    stale_mr_summary_pos = result.find("<summary>정체된 MR")
    revert_summary_pos = result.find("<summary>Revert 커밋")
    hotfix_summary_pos = result.find("<summary>Hotfix 커밋")

    # 순서 확인 (음수 check 추가)
    assert stale_mr_summary_pos > 0
    assert revert_summary_pos > 0
    assert hotfix_summary_pos > 0
    assert stale_mr_summary_pos < revert_summary_pos < hotfix_summary_pos
