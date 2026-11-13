"""repo-path 전체 URL 하이퍼링크 렌더링 테스트 (4차 개선 — 문자열 단언 관례)."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.models import DashboardModel, RepoActivity, RepoRef, RepoSummary
from pulse.renderer.assemble import build_dashboard_model
from pulse.renderer.html import render_html

KST = ZoneInfo("Asia/Seoul")

GITLAB_REPO_URL = "http://gitlab.test.local/org/repo"


def _make_model(web_url: str | None) -> DashboardModel:
    """repo-path 렌더 검증용 최소 모델 생성."""
    return DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 22),
        lookback_hours=24,
        summary_line="요약",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
        repo_summaries=(
            RepoSummary(
                repo_full_path="org/repo",
                summary_line="활동 요약",
                display_name="org/repo",
                web_url=web_url,
            ),
        ),
    )


def _make_config(repos: tuple[RepoRef, ...]) -> Config:
    """assemble 검증용 최소 Config 생성."""
    return Config(
        team_name="테스트팀",
        repos=repos,
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


def test_repo_summary_web_url_default_none() -> None:
    """RepoSummary 기존 3-인자 생성이 여전히 유효하다 (web_url 기본 None)."""
    summary = RepoSummary(
        repo_full_path="org/repo",
        summary_line="요약",
        display_name="repo",
    )

    assert summary.web_url is None


def test_repo_path_renders_full_url_hyperlink() -> None:
    """web_url이 있으면 repo-path가 전체 URL 하이퍼링크로 렌더된다."""
    html = render_html(_make_model(web_url=GITLAB_REPO_URL))

    assert '<div class="repo-path">' in html
    assert f'<a href="{GITLAB_REPO_URL}"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html
    # 링크 텍스트도 전체 URL
    assert f">{GITLAB_REPO_URL}</a>" in html


def test_repo_path_renders_without_nickname() -> None:
    """display_name이 full_path와 같아도(닉네임 없음) web_url이 있으면 렌더된다."""
    model = _make_model(web_url=GITLAB_REPO_URL)

    assert model.repo_summaries[0].display_name == "org/repo"
    assert '<div class="repo-path">' in render_html(model)


def test_css_defines_text_sm_used_by_repo_path() -> None:
    """repo-path가 쓰는 --text-sm 변수가 실제로 정의돼 있다 (미정의 var 회귀 방지)."""
    from pulse.renderer.styles import CSS

    assert "--text-sm:" in CSS
    assert "font-size: var(--text-sm)" in CSS


def test_repo_path_absent_without_web_url() -> None:
    """web_url이 None(구 경로)이면 repo-path 부제를 렌더하지 않는다."""
    html = render_html(_make_model(web_url=None))

    assert '<div class="repo-path">' not in html


def test_build_dashboard_model_injects_web_url() -> None:
    """build_dashboard_model이 config.repos의 web_url을 RepoSummary로 주입한다."""
    repo_ref = RepoRef(
        provider="gitlab",
        base_url="http://gitlab.test.local",
        namespace="org",
        name="repo",
        web_url=GITLAB_REPO_URL,
    )
    config = _make_config(repos=(repo_ref,))
    now = datetime(2026, 7, 22, 9, 0, 0, tzinfo=KST)
    # 레포 탭은 activities에서 파생되므로 활동 0건 레포도 activity 항목은 필요하다
    activity = RepoActivity(
        repo=repo_ref,
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
    )

    model = build_dashboard_model(
        groups=(),
        warnings=(),
        new_work=(),
        unclassified_ratio=0.0,
        activities=(activity,),
        config=config,
        report_date=date(2026, 7, 22),
        now=now,
    )

    summaries_by_repo = {rs.repo_full_path: rs for rs in model.repo_summaries}
    assert summaries_by_repo["org/repo"].web_url == GITLAB_REPO_URL
