"""HTML 탭 렌더링 테스트."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pulse.models import (
    CommitInfo,
    DashboardModel,
    FeatureGroup,
    MergeRequestInfo,
    RepoSummary,
    WarningSignal,
)
from pulse.renderer.html import _make_css_safe_slug, has_period_activity, render_html

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 16, 10, 0, 0, tzinfo=KST)


class TestMakeCssSafeSlug:
    """_make_css_safe_slug 함수 테스트."""

    def test_make_css_safe_slug_replaces_slash(self) -> None:
        """슬래시를 언더스코어 2개로 치환."""
        # Act
        slug = _make_css_safe_slug("org/repo", ("org/repo",))

        # Assert
        assert slug == "org__repo"

    def test_make_css_safe_slug_replaces_special_chars(self) -> None:
        """특수문자를 하이픈으로 치환."""
        # Act
        slug = _make_css_safe_slug("org/repo.js", ("org/repo.js",))

        # Assert
        assert slug == "org__repo-js"

    def test_make_css_safe_slug_handles_multiple_special_chars(self) -> None:
        """여러 특수문자 처리."""
        # Act
        slug = _make_css_safe_slug("org/repo@v1.0", ("org/repo@v1.0",))

        # Assert
        assert slug == "org__repo-v1-0"

    def test_make_css_safe_slug_handles_collision(self) -> None:
        """충돌 시 인덱스 접미사 부여."""
        # Act
        # "org/repo" -> "org__repo", "org__repo" (이미 safe) -> "org__repo"
        repos = ("org/repo", "org__repo")  # 둘 다 org__repo로 변환됨
        slug1 = _make_css_safe_slug("org/repo", repos)
        slug2 = _make_css_safe_slug("org__repo", repos)

        # Assert - 정렬된 순서대로 인덱스 부여
        # "org/repo" (index 0), "org__repo" (index 1)
        assert slug1 == "org__repo_0"
        assert slug2 == "org__repo_1"

    def test_make_css_safe_slug_no_collision_single_repo(self) -> None:
        """단일 레포는 충돌 없음."""
        # Act
        slug = _make_css_safe_slug("org/repo", ("org/repo",))

        # Assert
        assert slug == "org__repo"
        assert "_" not in slug.split("__")[-1]  # 마지막 부분에 인덱스 없음


class TestRenderHtmlTabs:
    """탭 렌더링 HTML 테스트."""

    @pytest.fixture
    def basic_model(self) -> DashboardModel:
        """기본 대시보드 모델 (레포 없음)."""
        return DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="활동 없음",
            groups=(),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

    def test_render_html_single_repo_no_tabs(self, basic_model: DashboardModel) -> None:
        """단일 레포일 때 탭 UI 없음."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api",),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # <nav class="tab-navigation"> 태그가 없어야 함 (CSS 클래스는 있을 수 있음)
        assert '<nav class="tab-navigation">' not in html
        assert 'id="tab-radio-backend__api"' not in html

    def test_render_html_multi_repo_has_tabs(self, basic_model: DashboardModel) -> None:
        """다중 레포일 때 탭 UI 표시."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        assert "tab-navigation" in html
        assert "tab-radio" in html
        assert 'id="tab-radio-backend__api"' in html
        assert 'id="tab-radio-backend__api"' in html
        assert 'id="tab-radio-frontend__web"' in html

    def test_render_html_tab_labels_include_repo_names(self, basic_model: DashboardModel) -> None:
        """탭 라벨에 레포명 포함."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        assert 'label for="tab-radio-backend__api"' in html
        assert ">backend/api<" in html
        assert ">frontend/web<" in html

    def test_render_html_overview_tab_content_exists(self, basic_model: DashboardModel) -> None:
        """전체 탭 콘텐츠가 존재."""
        # Arrange
        group = FeatureGroup(
            name="테스트 기능",
            source_rule="hints",
            evidence="feature/test",
            stage="developing",
            repo_full_path="backend/api",
            commits=(),
            merge_requests=(),
            branch_names=("feature/test",),
            participants=("alice",),
            branches=(),
        )
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "groups": (group,),
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        assert 'id="tab-content-backend__api"' in html
        assert "테스트 기능" in html

    def test_render_html_repo_tab_content_filtered(self, basic_model: DashboardModel) -> None:
        """레포 탭 콘텐츠가 필터링됨."""
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
            stage="developing",
            repo_full_path="frontend/web",
            commits=(),
            merge_requests=(),
            branch_names=("feature/ui",),
            participants=("bob",),
            branches=(),
        )
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "groups": (group1, group2),
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # 전체 탭에서는 둘 다 보임
        assert "API 기능" in html
        assert "UI 기능" in html
        # 각 탭 콘텐츠는 별도
        assert 'id="tab-content-backend__api"' in html
        assert 'id="tab-content-frontend__web"' in html

    def test_render_html_dynamic_css_includes_tab_selectors(
        self, basic_model: DashboardModel
    ) -> None:
        """동적 CSS에 탭 선택자 포함."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        assert "#tab-radio-backend__api:checked ~ #tab-content-backend__api" in html
        assert "#tab-radio-backend__api:checked ~ #tab-content-backend__api" in html
        assert "#tab-radio-frontend__web:checked ~ #tab-content-frontend__web" in html

    def test_render_html_empty_repo_tab_shows_empty_state(
        self, basic_model: DashboardModel
    ) -> None:
        """활동이 없는 탭에 레포 헤더는 표시되고 다른 섹션은 비어있음."""
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
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "groups": (group,),
                "repos": ("backend/api", "frontend/web"),  # frontend/web는 활동 없음
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # frontend/web 탭 콘텐츠 영역이 존재하고, 레포 헤더는 표시됨
        assert 'id="tab-content-frontend__web"' in html
        assert "frontend/web" in html

    def test_render_html_collection_failure_in_repo_tab(self, basic_model: DashboardModel) -> None:
        """수집 실패 경고가 해당 레포 탭에 표시."""
        # Arrange
        failure_warning = WarningSignal(
            kind="collection_failure",
            title="frontend/web",
            description="Network timeout",
            days=None,
            web_url="http://test.local/frontend/web",
        )
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "warnings": (failure_warning,),
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        assert "수집 실패" in html
        assert "frontend/web" in html
        assert "Network timeout" in html

    def test_render_html_xss_protection_in_repo_names(self, basic_model: DashboardModel) -> None:
        """레포명에 XSS 시도가 있으면 이스케이프됨."""
        # Arrange (다중 레포여야 탭 네비게이션이 렌더됨)
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": (
                    "org/<script>alert('xss')</script>",
                    "backend/api",
                ),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # 레포명이 사용자에게 보이는 탭 라벨에서 escape되어 실행 스크립트로 렌더되지 않음
        assert "&lt;script&gt;" in html
        # slug가 CSS-safe로 치환되어 for/id 속성에 raw 태그가 주입되지 않음
        assert 'for="tab-radio-org/<script>' not in html
        assert "org/" in html  # 레포명 자체는 (escape된 형태로) 존재

    def test_render_html_tab_structure_radio_before_nav(self, basic_model: DashboardModel) -> None:
        """라디오 인풋이 nav 밖의 같은 부모 레벨에 위치함을 검증.

        CSS ~선택자가 작동하려면 라디오가 nav 앞에 있어야 함.
        """
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # <nav> 이전에 모든 radio 인풋이 나타나야 함
        nav_start = html.find('<nav class="tab-navigation">')
        assert nav_start > -1, "nav tag not found"

        html_before_nav = html[:nav_start]
        # 모든 라디오는 nav 이전에
        assert 'id="tab-radio-backend__api"' in html_before_nav
        assert 'id="tab-radio-backend__api"' in html_before_nav
        assert 'id="tab-radio-frontend__web"' in html_before_nav

        # nav 안에는 라디오가 없어야 함
        nav_end = html.find("</nav>")
        html_inside_nav = html[nav_start:nav_end]
        assert "<input" not in html_inside_nav

    def test_render_html_active_label_dynamic_css(self, basic_model: DashboardModel) -> None:
        """동적 CSS에 활성 라벨 스타일 규칙이 포함되는지 검증."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # label[for=...] 선택자 규칙이 동적 CSS에 포함되어야 함
        assert 'label[for="tab-radio-backend__api"]' in html
        assert 'label[for="tab-radio-backend__api"]' in html
        assert 'label[for="tab-radio-frontend__web"]' in html
        # 활성 스타일 규칙이 존재
        assert "var(--bg-card)" in html or "background" in html

    def test_render_html_header_outside_tab_content(self, basic_model: DashboardModel) -> None:
        """헤더가 tab-content div 밖에 위치함을 검증."""
        # Arrange
        model = DashboardModel(
            **{
                **basic_model.__dict__,
                "repos": ("backend/api", "frontend/web"),
            }
        )

        # Act
        html = render_html(model)

        # Assert
        # 헤더가 첫 <div id="tab-content-... 이전에 나타나야 함
        header_pos = html.find('<header class="page-header">')
        first_tab_content_pos = html.find('<div id="tab-content-backend__api"')

        assert header_pos > -1, "header not found"
        assert first_tab_content_pos > -1, "first tab-content not found"
        assert header_pos < first_tab_content_pos, "header must appear before tab-content div"


def _commit_at(repo_branch: str, when: datetime) -> CommitInfo:
    """테스트용 커밋 하나."""
    return CommitInfo(
        sha="a" * 40,
        author_name="alice",
        authored_at=when,
        message="feat: 작업",
        branch=repo_branch,
        changed_files=("src/main.py",),
        web_url="http://test.local/commit/aaa",
    )


def _merge_request_at(when: datetime) -> MergeRequestInfo:
    """테스트용 MR 하나."""
    return MergeRequestInfo(
        iid=1,
        title="MR 제목",
        state="open",
        is_draft=False,
        labels=(),
        source_branch="feature/x",
        target_branch="develop",
        author_name="alice",
        created_at=when,
        updated_at=when,
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url="http://test.local/mr/1",
    )


def _group_with(
    repo_full_path: str,
    *,
    commits: tuple[CommitInfo, ...] = (),
    merge_requests: tuple[MergeRequestInfo, ...] = (),
) -> FeatureGroup:
    """테스트용 기능 그룹."""
    return FeatureGroup(
        name=f"{repo_full_path} 기능",
        source_rule="hints",
        evidence="test",
        stage="developing",
        repo_full_path=repo_full_path,
        commits=commits,
        merge_requests=merge_requests,
        branch_names=(),
        participants=("alice",),
        branches=(),
    )


class TestHasPeriodActivity:
    """탭 '확인 필요' 판정 (순수 로직)."""

    def test_returns_true_when_repo_has_commits(self) -> None:
        """커밋이 있으면 활동으로 판정한다."""
        # Arrange
        groups = (_group_with("backend/api", commits=(_commit_at("develop", NOW),)),)

        # Act
        result = has_period_activity(groups, "backend/api")

        # Assert
        assert result is True

    def test_returns_true_when_repo_has_only_merge_requests(self) -> None:
        """커밋 없이 MR만 있어도 활동으로 판정한다."""
        # Arrange
        groups = (_group_with("backend/api", merge_requests=(_merge_request_at(NOW),)),)

        # Act
        result = has_period_activity(groups, "backend/api")

        # Assert
        assert result is True

    def test_returns_false_when_group_has_no_commits_or_mrs(self) -> None:
        """그룹은 있지만 커밋·MR이 없으면 활동이 아니다."""
        # Arrange
        groups = (_group_with("backend/api"),)

        # Act
        result = has_period_activity(groups, "backend/api")

        # Assert
        assert result is False

    def test_ignores_other_repos_activity(self) -> None:
        """다른 레포의 활동은 판정에 섞이지 않는다."""
        # Arrange
        groups = (_group_with("backend/api", commits=(_commit_at("develop", NOW),)),)

        # Act
        result = has_period_activity(groups, "frontend/web")

        # Assert
        assert result is False

    def test_returns_false_when_no_groups(self) -> None:
        """그룹이 하나도 없으면 활동이 아니다."""
        # Arrange
        groups: tuple[FeatureGroup, ...] = ()

        # Act
        result = has_period_activity(groups, "backend/api")

        # Assert
        assert result is False


class TestTabActivityDot:
    """탭 '확인 필요' 점 렌더."""

    @staticmethod
    def _model_with(
        groups: tuple[FeatureGroup, ...],
        warnings: tuple[WarningSignal, ...] = (),
    ) -> DashboardModel:
        """두 레포 탭을 가진 대시보드 모델."""
        return DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=groups,
            new_work=(),
            warnings=warnings,
            unclassified_ratio=0.0,
            repos=("backend/api", "frontend/web"),
            repo_summaries=(
                RepoSummary(
                    repo_full_path="backend/api",
                    summary_line="1 프로젝트",
                    display_name="백엔드 API",
                ),
                RepoSummary(
                    repo_full_path="frontend/web",
                    summary_line="0 프로젝트",
                    display_name="프론트 웹",
                ),
            ),
        )

    @staticmethod
    def _label_html(html: str, display_name: str) -> str:
        """특정 탭 라벨 한 개의 HTML을 잘라낸다."""
        marker = f">{display_name}<"
        index = html.find(marker)
        assert index != -1, f"{display_name} 라벨을 찾지 못했다"
        start = html.rfind("<label", 0, index)
        end = html.find("</label>", index)
        return html[start : end + len("</label>")]

    def test_dot_only_on_repo_with_activity(self) -> None:
        """활동이 있는 탭에만 점이 붙는다."""
        # Arrange
        model = self._model_with(
            groups=(
                _group_with("backend/api", commits=(_commit_at("develop", NOW),)),
                _group_with("frontend/web"),
            )
        )

        # Act
        html = render_html(model)

        # Assert
        assert "tab-dot" in self._label_html(html, "백엔드 API")
        assert "tab-dot" not in self._label_html(html, "프론트 웹")

    def test_no_dot_when_only_warnings(self) -> None:
        """주의 신호만 있는 레포에는 점이 붙지 않는다 (상시 상태라 매일 반복됨)."""
        # Arrange
        warning = WarningSignal(
            kind="stale_branch",
            title="feature/old",
            description="push 없음: 30일",
            days=30,
            web_url="http://test.local/tree/feature/old",
            repo_full_path="frontend/web",
        )
        model = self._model_with(
            groups=(_group_with("backend/api", commits=(_commit_at("develop", NOW),)),),
            warnings=(warning,),
        )

        # Act
        html = render_html(model)

        # Assert
        assert "tab-dot" not in self._label_html(html, "프론트 웹")

    def test_dot_carries_accessible_label(self) -> None:
        """점에 스크린리더용 레이블이 붙는다."""
        # Arrange
        model = self._model_with(
            groups=(_group_with("backend/api", commits=(_commit_at("develop", NOW),)),)
        )

        # Act
        label_html = self._label_html(render_html(model), "백엔드 API")

        # Assert
        assert 'role="img"' in label_html
        assert 'aria-label="확인 필요"' in label_html

    def test_label_text_wrapped_for_ellipsis(self) -> None:
        """라벨 텍스트가 말줄임 전용 span으로 감싸진다."""
        # Arrange
        model = self._model_with(groups=())

        # Act
        label_html = self._label_html(render_html(model), "백엔드 API")

        # Assert
        assert '<span class="tab-name">백엔드 API</span>' in label_html

    def test_no_dot_markup_for_single_repo(self) -> None:
        """단일 레포는 탭 자체가 없어 점도 없다."""
        # Arrange
        model = self._model_with(groups=())
        single_repo_model = DashboardModel(**{**model.__dict__, "repos": ("backend/api",)})

        # Act
        html = render_html(single_repo_model)

        # Assert (CSS 규칙은 항상 인라인되므로 마크업 출현만 확인한다)
        assert 'class="tab-dot"' not in html
