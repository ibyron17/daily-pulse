"""팀 참여 섹션 기본 숨김 + #team 해시 토글 테스트 (4차 개선 — 문자열 단언 관례)."""

from datetime import date

from pulse.models import DashboardModel, FeatureGroup, TaskSummary
from pulse.renderer.html import render_html
from pulse.renderer.sections import render_participation
from pulse.renderer.styles import CSS


def _make_group_with_participants() -> FeatureGroup:
    """참여자가 있는 최소 그룹 생성."""
    return FeatureGroup(
        name="feature/login",
        source_rule="branch",
        evidence="",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/login",),
        participants=("dev-a", "dev-b"),
        task_summary=TaskSummary(
            commit_titles=(),
            open_mr_titles=(),
            active_branch_names=(),
        ),
    )


def _make_model() -> DashboardModel:
    """참여 섹션이 렌더되는 최소 모델 생성."""
    return DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 22),
        lookback_hours=24,
        summary_line="요약",
        groups=(_make_group_with_participants(),),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
    )


def test_render_participation_has_section_class() -> None:
    """참여 섹션이 participation-section 클래스를 갖는다 (CSS 숨김 대상)."""
    html = render_participation((_make_group_with_participants(),))

    assert '<section class="participation-section">' in html


def test_css_hides_participation_by_default() -> None:
    """CSS가 참여 섹션을 기본 숨기고 body 클래스로만 표시한다."""
    assert ".participation-section" in CSS
    assert "body.show-participation .participation-section" in CSS


def test_dashboard_contains_participation_toggle_js() -> None:
    """대시보드 HTML에 #team 해시 토글 JS가 포함된다 (hashchange 즉시 반영)."""
    html = render_html(_make_model())

    assert "show-participation" in html
    assert "#team" in html
    assert "hashchange" in html


def test_participation_toggle_handles_combined_hash() -> None:
    """토글이 해시를 '#' 세그먼트로 파싱해 #team#repo=slug 조합을 지원한다.

    URL 프래그먼트는 하나뿐이라 탭 상태(#repo=)와 조합되면 hash 전체가
    "#team#repo=..."가 된다 — 엄격 비교(hash === '#team')는 이때 깨진다(실사용 버그).
    """
    html = render_html(_make_model())

    assert "split('#')" in html
    assert "indexOf('team')" in html
    assert "hash === '#team'" not in html  # 엄격 비교 회귀 방지
    # 탭 복원도 세그먼트 파싱 사용 (repo= 위치 무관)
    assert 'indexOf("repo=")' in html
    assert 'hash.indexOf("#repo=") === 0' not in html
