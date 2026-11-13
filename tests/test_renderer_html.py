"""HTML 생성 및 부록 B 검증 테스트 (Phase 4 — html.py)."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse.models import (
    CommitInfo,
    DashboardModel,
    FeatureGroup,
    NewWorkSignal,
    RepoSummary,
    WarningSignal,
)
from pulse.renderer.escape import escape_url
from pulse.renderer.html import render_html, write_report

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def now_fixture() -> datetime:
    """테스트용 현재 시각."""
    return datetime(2026, 7, 16, 10, 0, 0, tzinfo=KST)


@pytest.fixture
def basic_dashboard_model(now_fixture: datetime) -> DashboardModel:
    """기본 대시보드 모델."""
    return DashboardModel(
        team_name="테스트팀",
        report_date=date(2026, 7, 16),
        lookback_hours=24,
        summary_line="3개 프로젝트 활동, MR 1건 머지, 주의 1건",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("test/repo",),
    )


class TestRenderHtmlBasics:
    """기본 HTML 렌더 테스트."""

    def test_render_html_generates_valid_html(self, basic_dashboard_model: DashboardModel) -> None:
        """유효한 HTML을 생성하는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "<head>" in html
        assert "<body>" in html
        assert "</html>" in html

    def test_render_html_includes_title(self, basic_dashboard_model: DashboardModel) -> None:
        """타이틀에 팀명이 포함되는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert f"Daily Pulse — {basic_dashboard_model.team_name}" in html

    def test_render_html_includes_meta_tags(self, basic_dashboard_model: DashboardModel) -> None:
        """viewport과 charset 메타 태그가 포함되는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert 'charset="UTF-8"' in html
        assert "viewport" in html

    def test_render_html_includes_inline_css(self, basic_dashboard_model: DashboardModel) -> None:
        """인라인 CSS가 포함되는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert "<style>" in html
        # 라운드 10: hex 팔레트 도입 — --done, --prog, --qa 등 새로운 토큰 확인
        assert "--panel" in html and "--done" in html and "--prog" in html
        assert "</style>" in html


class TestRenderHtmlEscaping:
    """XSS 이스케이프 테스트."""

    def test_render_html_escapes_group_names(self, basic_dashboard_model: DashboardModel) -> None:
        """그룹명에 스크립트 태그가 있으면 이스케이프하는지 검증."""
        # Arrange
        malicious_group = FeatureGroup(
            name="<script>alert('xss')</script>",
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
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(malicious_group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        from pulse.renderer.html import (
            _render_expand_animation_script,
            _render_participation_toggle_script,
            _render_tab_state_script,
            _render_tooltip_edge_script,
        )

        # 그룹명의 스크립트 태그가 escape되었는지 확인
        assert "&lt;script&gt;" in html
        # 렌더러가 의도적으로 넣는 인라인 스크립트를 제거한 나머지에는
        # <script> 태그가 없어야 함 (데이터에서 유입된 스크립트 차단)
        data_html = html
        for known_script in (
            _render_tab_state_script(),
            _render_participation_toggle_script(),
            _render_tooltip_edge_script(),
            _render_expand_animation_script(),
        ):
            data_html = data_html.replace(known_script, "")
        assert "<script>" not in data_html

    def test_render_html_escapes_warning_titles(
        self, basic_dashboard_model: DashboardModel
    ) -> None:
        """경고 제목이 이스케이프되는지 검증."""
        # Arrange
        warning = WarningSignal(
            kind="stale_mr",
            title='MR: 제목 < > & "',
            description="설명",
            days=5,
            web_url="http://test.local/test/repo/-/merge_requests/1",
        )
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(),
            new_work=(),
            warnings=(warning,),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        # 경고 제목의 특수문자가 각각 escape되었는지 확인
        assert "&lt;" in html and "&gt;" in html and "&amp;" in html and "&quot;" in html
        # raw 특수문자열이 그대로 주입되지 않았는지 확인
        assert "MR: 제목 < > &" not in html


class TestRenderHtmlStructure:
    """HTML 구조 테스트."""

    def test_render_html_includes_all_6_sections(self, now_fixture: datetime) -> None:
        """6개 섹션이 모두 포함되는지 검증."""
        # Arrange
        group = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=("alice",),
            branches=(),
        )
        signal = NewWorkSignal(
            title="신규 브랜치",
            repo_full_path="test/repo",
            branch_or_mr="feature/new",
            web_url="http://test.local/test/repo/-/tree/feature/new",
        )
        warning = WarningSignal(
            kind="stale_mr",
            title="정체된 MR",
            description="리뷰 대기",
            days=5,
            web_url="http://test.local/test/repo/-/merge_requests/1",
        )
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="1개 프로젝트",
            groups=(group,),
            new_work=(signal,),
            warnings=(warning,),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        # 섹션 식별자나 클래스 확인
        assert "header" in html.lower() or "팀명" in html or "테스트팀" in html
        assert "기능1" in html  # 카드 섹션
        assert "신규 브랜치" in html  # 새 작업 섹션
        assert "정체된 MR" in html  # 경고 섹션
        assert "alice" in html  # 참여 맵

    def test_render_html_omits_sections_when_empty(
        self, basic_dashboard_model: DashboardModel
    ) -> None:
        """빈 섹션이 생략되는지 검증."""
        # Arrange (모든 섹션이 비어있음)
        model = basic_dashboard_model

        # Act
        html = render_html(model)

        # Assert
        # 빈 섹션이 완전히 생략되거나, 없는 컨텐츠로 나타나야 함
        # (구현 방식에 따라 `if s` 필터링으로 인해 생략됨)
        assert html.count("<section") < 6 or model.groups or model.warnings


class TestRenderHtmlAppendixBChecks:
    """부록 B: 감시 금지 체크리스트 검증."""

    def test_render_html_participation_has_no_numbers(self, now_fixture: datetime) -> None:
        """참여 맵에 숫자가 없는지 검증 (부록 B)."""
        # Arrange — 참여 맵은 groups에서 파생되므로 참여자가 있는 그룹을 넣는다
        group = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=("alice",),
        )
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        # 참여 맵 섹션에 숫자 패턴 없음 (정규식으로 확인)
        import re

        # "alice"가 있는 부분 추출
        match = re.search(r"alice.*?(?=</|<section|<div|$)", html, re.DOTALL)
        if match:
            alice_section = match.group(0)
            # 숫자 카운트나 순위 표시 없음
            assert not re.search(r"\d+\s*(건|개|회|명)", alice_section)

    def test_render_html_cards_no_commit_count(self, now_fixture: datetime) -> None:
        """카드에 커밋 수치가 없는지 검증 (부록 B)."""
        # Arrange
        commit = CommitInfo(
            sha="abc123",
            author_name="alice",
            authored_at=now_fixture - timedelta(days=1),
            message="test commit",
            branch="feature/test",
            changed_files=("src/test.ts",),
            web_url="http://test.local/test/repo/-/commit/abc123",
        )
        group = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="test/repo",
            commits=(commit,),
            merge_requests=(),
            branch_names=(),
            participants=("alice",),
            branches=(),
        )
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        # 카드에서 "1건 커밋" 같은 수치 없음
        import re

        match = re.search(r"기능1.*?(?=</|<section|<div class|$)", html, re.DOTALL)
        if match:
            card_section = match.group(0)
            # "커밋" 키워드 뒤 숫자 없음
            assert not re.search(r"커밋\s*\d+", card_section)


class TestWriteReport:
    """파일 저장 테스트."""

    def test_write_report_creates_dated_file(
        self, basic_dashboard_model: DashboardModel, tmp_path: Path
    ) -> None:
        """dated 파일이 생성되는지 검증."""
        # Arrange
        html = render_html(basic_dashboard_model)
        report_date = date(2026, 7, 16)

        # Act
        dated_path, latest_path = write_report(html, tmp_path, report_date)

        # Assert
        assert dated_path.exists()
        assert dated_path.name == "pulse-2026-07-16.html"
        assert "2026-07-16" in dated_path.read_text()

    def test_write_report_creates_latest_copy(
        self, basic_dashboard_model: DashboardModel, tmp_path: Path
    ) -> None:
        """latest.html이 생성되고 주간 링크가 항상 latest-weekly.html을 가리키는지 검증."""
        # Arrange
        html = render_html(basic_dashboard_model)
        report_date = date(2026, 7, 16)

        # Act
        dated_path, latest_path = write_report(html, tmp_path, report_date)

        # Assert
        assert latest_path is not None
        assert latest_path.exists()
        assert latest_path.name == "latest.html"

        # dated 파일도 항상 latest-weekly.html 링크를 가짐 (월요일 게이트 때문에)
        dated_content = dated_path.read_text()
        assert 'href="latest-weekly.html"' in dated_content

        # latest 파일도 latest-weekly.html 링크를 가짐
        latest_content = latest_path.read_text()
        assert 'href="latest-weekly.html"' in latest_content

    def test_write_report_creates_output_dir(
        self, basic_dashboard_model: DashboardModel, tmp_path: Path
    ) -> None:
        """output 디렉토리가 없으면 생성하는지 검증."""
        # Arrange
        html = render_html(basic_dashboard_model)
        report_date = date(2026, 7, 16)
        output_dir = tmp_path / "nested" / "path"

        # Act
        dated_path, latest_path = write_report(html, output_dir, report_date)

        # Assert
        assert output_dir.exists()
        assert dated_path.exists()

    def test_write_report_returns_paths(
        self, basic_dashboard_model: DashboardModel, tmp_path: Path
    ) -> None:
        """반환값이 Path 튜플인지 검증."""
        # Arrange
        html = render_html(basic_dashboard_model)
        report_date = date(2026, 7, 16)

        # Act
        result = write_report(html, tmp_path, report_date)

        # Assert
        assert isinstance(result, tuple)
        assert len(result) == 2
        dated_path, latest_path = result
        assert isinstance(dated_path, Path)
        assert isinstance(latest_path, Path)


class TestRenderHtmlLang:
    """언어 속성 테스트."""

    def test_render_html_includes_korean_lang_attribute(
        self, basic_dashboard_model: DashboardModel
    ) -> None:
        """html 태그에 lang="ko" 속성이 있는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert 'lang="ko"' in html


class TestRenderHtmlEncoding:
    """인코딩 테스트."""

    def test_render_html_korean_characters_preserved(
        self, basic_dashboard_model: DashboardModel
    ) -> None:
        """한글 문자가 보존되는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert "테스트팀" in html
        assert 'charset="UTF-8"' in html or "charset=UTF-8" in html


class TestRenderHtmlMetadata:
    """메타 정보 렌더 테스트."""

    def test_render_html_includes_metadata_footer(
        self, basic_dashboard_model: DashboardModel
    ) -> None:
        """메타 정보(미분류율 등)가 포함되는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        assert "미분류" in html or "footer" in html.lower() or "meta" in html.lower()

    def test_render_html_does_not_leak_tokens(self, basic_dashboard_model: DashboardModel) -> None:
        """HTML에 토큰 같은 민감한 문자열이 없는지 검증."""
        # Act
        html = render_html(basic_dashboard_model)

        # Assert
        # 토큰 같은 민감한 패턴 없음 (GITLAB_TOKEN, GITHUB_TOKEN 등)
        assert "GITLAB_TOKEN" not in html
        assert "GITHUB_TOKEN" not in html
        assert "Bearer " not in html
        assert "token=" not in html.lower()

    def test_html_structure_responsive_320px(self, now_fixture: datetime) -> None:
        """반응형 CSS 메디어 쿼리가 포함되는지 검증 (320px 뷰포트)."""
        # Arrange
        group = FeatureGroup(
            name="기능1",
            source_rule="hints",
            evidence="test",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=("alice",),
            branches=(),
        )
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("test/repo",),
        )

        # Act
        html = render_html(model)

        # Assert
        # 반응형 CSS 구조 확인 (clamp() 또는 메디어 쿼리)
        assert "clamp" in html or "@media" in html
        # viewport 메타 태그 확인
        assert "viewport" in html


class TestEscapeUrlSecurity:
    """escape_url 보안 테스트 (URL 스킴 화이트리스트)."""

    def test_escape_url_blocks_javascript_scheme(self) -> None:
        """javascript: 스킴을 차단하는지 검증."""
        # Act
        result = escape_url("javascript:alert('xss')")

        # Assert
        assert result == ""

    def test_escape_url_blocks_data_scheme(self) -> None:
        """data: 스킴을 차단하는지 검증."""
        # Act
        result = escape_url("data:text/html,<script>alert(1)</script>")

        # Assert
        assert result == ""

    def test_escape_url_allows_http_https(self) -> None:
        """http/https 스킴은 허용하는지 검증."""
        # Act
        http_result = escape_url("http://test.example.com")
        https_result = escape_url("https://test.example.com")

        # Assert
        assert http_result == "http://test.example.com"
        assert https_result == "https://test.example.com"


class TestTabLabels:
    """탭 라벨 테스트."""

    def test_tab_labels_use_display_names(self, basic_dashboard_model: DashboardModel) -> None:
        """탭 라벨에 display_name이 사용된다."""
        # Arrange
        model = DashboardModel(
            team_name="Test Team",
            report_date=date(2026, 7, 16),
            lookback_hours=24,
            summary_line="test",
            groups=(),
            new_work=(),
            warnings=(),
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
                    summary_line="2 프로젝트",
                    display_name="frontend/web",  # 닉네임 없으므로 full_path
                ),
            ),
        )

        # Act
        html = render_html(model)

        # Assert
        # 닉네임이 있는 경우
        assert "백엔드 API" in html
        # 닉네임이 없는 경우 (full_path 사용)
        assert "frontend/web" in html
        # tab-label class가 있어야 함
        assert "tab-label" in html
