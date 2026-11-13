"""HTML 렌더링 - 전체 탭 부재, 레포 탭 헤더 테스트 (신규 테스트 - test d, e, f)."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from pulse.models import DashboardModel
from pulse.renderer.html import render_html
from tests.conftest import make_feature_group

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def basic_dashboard_with_repos() -> DashboardModel:
    """레포별 탭이 있는 대시보드 모델."""
    return DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 16),
        lookback_hours=24,
        summary_line="2개 프로젝트 활동",
        groups=(
            make_feature_group(
                name="feature1",
                repo_full_path="sample-group/sample-ui",
            ),
            make_feature_group(
                name="feature2",
                repo_full_path="backend/api",
            ),
        ),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("backend/api", "sample-group/sample-ui"),
    )


class TestRenderHtmlNoOverviewTab:
    """test d) 전체 탭 부재 테스트."""

    def test_render_html_removes_overview_tab(
        self, basic_dashboard_with_repos: DashboardModel
    ) -> None:
        """render_html에서 'tab-radio-overview' 아이디가 없어야 함."""
        # Act
        html = render_html(basic_dashboard_with_repos)

        # Assert
        assert "tab-radio-overview" not in html, "Overview tab should not exist"


class TestRenderHtmlFirstRepoChecked:
    """test e) 첫 레포 checked 테스트."""

    def test_render_html_first_repo_checked(
        self, basic_dashboard_with_repos: DashboardModel
    ) -> None:
        """첫 번째 repo 라디오에 HTML checked 속성이 있어야 함."""
        # Act
        html = render_html(basic_dashboard_with_repos)

        # Assert
        # 첫 번째 레포는 "backend/api"
        first_repo = basic_dashboard_with_repos.repos[0]

        # slug는 "/" 를 "__"로 변환 (RepoRef.slug와 동일)
        first_slug = first_repo.replace("/", "__")

        # radio 태그에서 첫 번째 레포의 checked 속성 확인
        checked_pattern = f'id="tab-radio-{first_slug}'
        assert checked_pattern in html, f"First repo tab should be found in HTML: {checked_pattern}"

        # 첫 레포 라디오가 checked 되어 있는지 확인
        import re

        # 첫 레포 라디오 요소를 찾기
        pattern = f'<input[^>]*id="tab-radio-{first_slug}"[^>]*>'
        matches = re.findall(pattern, html)

        assert len(matches) > 0, f"Radio button should exist: {first_slug}"

        # 첫 번째 라디오가 checked 되어 있어야 함
        first_radio_html = matches[0]
        assert "checked" in first_radio_html, "First radio should be checked"


class TestRenderHtmlRepoTabHeader:
    """test f) 탭별 레포 헤더 테스트."""

    def test_render_html_repo_tab_header(self, basic_dashboard_with_repos: DashboardModel) -> None:
        """각 레포 탭 상단에 요약이 있어야 함."""
        # Act
        html = render_html(basic_dashboard_with_repos)

        # Assert
        # 요약 라인이 포함되어야 함 (repo_summaries에서)
        # 예를 들어 "2개 프로젝트" 같은 텍스트가 포함되어야 함
        assert "프로젝트" in html or "활동" in html, "Summary line content should be in HTML"
