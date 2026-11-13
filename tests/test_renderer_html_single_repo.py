"""단일 레포 대시보드 회귀 테스트 (tab-content wrapper 없음, empty-state)."""

from zoneinfo import ZoneInfo

from pulse.models import (
    DashboardModel,
    FeatureGroup,
    RepoSummary,
)
from pulse.renderer.html import render_html

KST = ZoneInfo("Asia/Seoul")


def test_single_repo_html_no_tab_content_wrapper() -> None:
    """단일 레포 대시보드가 tab-content wrapper 없이 렌더된다.

    Critical 1 회귀 테스트: wrapper가 있으면 display: none으로 숨겨지므로
    tab-content div가 없어야 한다.
    """
    model = DashboardModel(
        team_name="Test Team",
        report_date=__import__("datetime").date(2026, 7, 20),
        lookback_hours=72,
        summary_line="1개 프로젝트",
        groups=(
            FeatureGroup(
                name="test-feature",
                source_rule="branch",
                evidence="branch matching",
                stage="developing",
                repo_full_path="test/repo",
                commits=(),
                merge_requests=(),
                branch_names=("feature/test",),
                participants=("alice",),
            ),
        ),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        diff=None,
        repos=("test/repo",),
        repo_summaries=(RepoSummary("test/repo", "1개 프로젝트", "test/repo"),),
    )

    html = render_html(model)

    # tab-content div가 없어야 함 (단일 레포는 wrapper 없음)
    assert 'class="tab-content"' not in html
    # 프로젝트 현황은 있어야 함
    assert "<h2>프로젝트 현황</h2>" in html


def test_single_repo_empty_state_displayed() -> None:
    """활동 0건 레포에 empty-state 메시지가 표시된다.

    Minor 4 회귀 테스트: 섹션만 비면 empty-state 표시.
    """
    model = DashboardModel(
        team_name="Test Team",
        report_date=__import__("datetime").date(2026, 7, 20),
        lookback_hours=72,
        summary_line="활동 없음",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        diff=None,
        repos=("test/repo",),
        repo_summaries=(RepoSummary("test/repo", "활동 없음", "test/repo"),),
    )

    html = render_html(model)

    # empty-state 메시지 확인
    assert "조회 기간 내 활동이 없습니다." in html
