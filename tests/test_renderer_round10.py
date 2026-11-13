"""라운드 10 벤치마크 재설계 테스트 (styles.py, sections.py, html.py 통합)."""

from datetime import datetime, timezone
from typing import Literal

from pulse.models import (
    CommitInfo,
    FeatureGroup,
    MergeRequestInfo,
    TaskSummary,
    WarningSignal,
)
from pulse.renderer.sections import _render_stage_badge, _render_warning_item, render_kpi_strip
from pulse.renderer.styles import CSS

# ═══ KPI 스트립 테스트


class TestRenderKpiStrip:
    """render_kpi_strip() — 4개 KPI 카드 렌더 검증."""

    def _make_group(
        self,
        name: str = "feature/test",
        group_kind: Literal["feature", "line"] = "feature",
        commits_count: int = 0,
        mrs_count: int = 0,
        repo: str = "org/repo",
    ) -> FeatureGroup:
        """테스트용 그룹 생성."""
        commits = tuple(
            CommitInfo(
                sha="abc",
                author_name="test",
                authored_at=datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc),
                message=f"commit {i}",
                branch=name,
                changed_files=(),
                web_url="http://example.com",
            )
            for i in range(commits_count)
        )
        return FeatureGroup(
            name=name,
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path=repo,
            commits=commits,
            merge_requests=tuple(
                MergeRequestInfo(
                    iid=i,
                    title=f"MR {i}",
                    state="open",
                    is_draft=False,
                    labels=(),
                    source_branch=name,
                    target_branch="develop",
                    author_name="tester",
                    created_at=datetime(2026, 7, 22, 9, 0, 0, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc),
                    merged_at=None,
                    reviews=(),
                    is_external=False,
                    web_url=f"http://example.com/mr/{i}",
                )
                for i in range(mrs_count)
            ),
            branch_names=(name,),
            participants=(),
            task_summary=TaskSummary(
                commit_titles=(),
                open_mr_titles=(),
                active_branch_names=(),
            ),
            group_kind=group_kind,
            issue_keys=(),
            daily_commit_counts=(),
            last_activity_at=None,
            branch_history=None,
        )

    def test_kpi_strip_four_values_from_groups_and_warnings(self) -> None:
        """4개 KPI가 그룹과 경고에서 정확히 파생된다.

        - 프로젝트/기능: group_kind=="feature"만 세고, line 그룹은 제외
        - 커밋: 모든 그룹(feature+line)의 len(g.commits) 합
        - MR: 모든 그룹의 len(g.merge_requests) 합
        - 경고: repo 일치 건수
        """
        repo = "org/repo"

        # 그룹 구성: feature 2개(커밋 3+2), line 1개(커밋 1)
        groups = (
            self._make_group("feature/a", "feature", commits_count=3, mrs_count=2, repo=repo),
            self._make_group("feature/b", "feature", commits_count=2, mrs_count=1, repo=repo),
            self._make_group("release/main", "line", commits_count=1, mrs_count=0, repo=repo),
        )

        # 경고: 해당 repo 2건, 다른 repo 1건
        warnings = (
            WarningSignal(
                kind="stale_mr",
                title="MR A",
                description="desc",
                days=5,
                repo_full_path=repo,
                web_url=None,
            ),
            WarningSignal(
                kind="stale_branch",
                title="Branch B",
                description="desc",
                days=10,
                repo_full_path=repo,
                web_url=None,
            ),
            WarningSignal(
                kind="collection_failure",
                title="Other repo failure",
                description="desc",
                days=None,
                repo_full_path="other/repo",
                web_url=None,
            ),
        )

        html = render_kpi_strip(groups, warnings, repo)

        # 프로젝트/기능: feature 2개
        assert ">2<" in html
        # 커밋: 3+2+1 = 6 (line도 포함)
        assert ">6<" in html
        # MR: 2+1+0 = 3
        assert ">3<" in html
        # 경고: repo 일치 2건
        assert ">2<" in html

    def test_kpi_strip_repo_filter_isolation(self) -> None:
        """repo 필터가 실제로 듣는다 (다른 repo의 그룹·경고 제외)."""
        repo1 = "org/repo1"
        repo2 = "org/repo2"

        groups = (
            self._make_group("feature/repo1", "feature", commits_count=5, mrs_count=2, repo=repo1),
            self._make_group("feature/repo2", "feature", commits_count=10, mrs_count=5, repo=repo2),
        )

        warnings = (
            WarningSignal(
                kind="stale_mr",
                title="W1",
                description="",
                days=None,
                repo_full_path=repo1,
                web_url=None,
            ),
            WarningSignal(
                kind="stale_mr",
                title="W2",
                description="",
                days=None,
                repo_full_path=repo2,
                web_url=None,
            ),
        )

        # repo1 기준: feature 1개, commit 5, MR 2, warning 1
        html1 = render_kpi_strip(groups, warnings, repo1)
        assert ">1<" in html1  # 프로젝트
        assert ">5<" in html1  # 커밋
        assert ">2<" in html1  # MR
        assert ">1<" in html1  # 경고

        # repo2 기준: feature 1개, commit 10, MR 5, warning 1
        html2 = render_kpi_strip(groups, warnings, repo2)
        assert ">1<" in html2  # 프로젝트
        assert ">10<" in html2  # 커밋
        assert ">5<" in html2  # MR
        assert ">1<" in html2  # 경고

    def test_kpi_strip_zero_warnings_drops_the_warn_accent(self) -> None:
        """경고 0건이면 카드는 남기되 강조(kpi-warn)는 주지 않는다.

        0을 경고색으로 칠하면 아무 문제 없는 레포가 문제 있는 것처럼 읽힌다.
        """
        groups = (self._make_group("feature/test", "feature", commits_count=1, repo="org/repo"),)

        html = render_kpi_strip(groups, (), "org/repo")

        assert "주의 신호" in html
        assert "kpi-warn" not in html

    def test_kpi_strip_marks_warnings_when_present(self) -> None:
        groups = (self._make_group("feature/test", "feature", commits_count=1, repo="org/repo"),)
        warnings = (
            WarningSignal(
                kind="stale_branch",
                title="feature/old",
                description="push 없음: 30일",
                repo_full_path="org/repo",
                days=30,
                web_url=None,
            ),
        )

        assert "kpi-warn" in render_kpi_strip(groups, warnings, "org/repo")

    def test_kpi_strip_renders_even_when_everything_is_zero(self) -> None:
        """활동이 전혀 없는 레포에서도 스트립은 항상 나온다.

        레포마다 스트립이 있다 없다 하면 탭을 옮길 때 아래 내용이 튀어 자리를 잃는다.
        0도 읽을 정보이므로 숨기지 않는다 — 경고 강조만 빼면 오해가 없다.
        """
        html = render_kpi_strip((), (), "org/repo")

        assert '<div class="kpi-row">' in html
        assert html.count('<div class="n">0</div>') == 4
        assert "kpi-warn" not in html

    def test_kpi_strip_renders_when_only_warnings_exist(self) -> None:
        """그룹이 없어도 경고가 있으면 스트립은 나온다 (수집 실패 레포 등)."""
        warnings = (
            WarningSignal(
                kind="stale_branch",
                title="feature/old",
                description="push 없음: 30일",
                repo_full_path="org/repo",
                days=30,
                web_url=None,
            ),
        )

        html = render_kpi_strip((), warnings, "org/repo")

        assert "kpi-row" in html
        assert "kpi-warn" in html


# ═══ 상태 배지 테스트


class TestRenderStageBadge:
    """_render_stage_badge() — 진행 단계 배지 렌더 검증."""

    def test_badge_developing_shows_correct_class_and_text(self) -> None:
        """developing 단계는 'b-prog' 클래스와 '진행 중' 문안."""
        html = _render_stage_badge("developing")

        assert '<span class="badge b-prog">' in html
        assert "진행 중" in html
        assert 'class="tooltip-host' in html  # 래퍼에 전용 클래스가 덧붙는다

    def test_badge_reviewing_shows_correct_class_and_text(self) -> None:
        """reviewing 단계는 'b-qa' 클래스와 '리뷰 중' 문안."""
        html = _render_stage_badge("reviewing")
        assert '<span class="badge b-qa">' in html
        assert "리뷰 중" in html

    def test_badge_merged_shows_correct_class_and_text(self) -> None:
        """merged 단계는 'b-done' 클래스와 '머지됨' 문안."""
        html = _render_stage_badge("merged")
        assert '<span class="badge b-done">' in html
        assert "머지됨" in html

    def test_badge_other_returns_empty_string(self) -> None:
        """other 단계는 빈 문자열을 반환한다.

        판정 불가를 '—' 배지로 표시하면, 활동이 많은 그룹이 빈 상태로 읽힌다는
        설계 결정으로, 배지를 아예 렌더하지 않고 그리드 셀만 비운다.
        """
        html = _render_stage_badge("other")
        assert html == ""

    def test_badge_includes_tooltip_with_rules(self) -> None:
        """배지가 있을 때 판정 기준 툴팁이 포함된다."""
        html = _render_stage_badge("developing")
        # 툴팁 구조
        assert '<span class="tooltip-lead">' in html
        assert "<ul>" in html
        assert "<li>" in html


# ═══ 경고 항목 테스트


class TestRenderWarningItem:
    """_render_warning_item() — 경고 행 한 줄 조밀 배치 검증."""

    def test_warning_collection_failure_has_severe_class(self) -> None:
        """collection_failure는 'warning-item--severe' 클래스."""
        signal = WarningSignal(
            kind="collection_failure",
            title="수집 실패",
            description="API 에러",
            days=None,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert 'class="warning-item warning-item--severe"' in html

    def test_warning_revert_commit_has_notable_class(self) -> None:
        """revert_commit는 'warning-item--notable' 클래스."""
        signal = WarningSignal(
            kind="revert_commit",
            title="Revert 커밋",
            description="커밋이 되돌려짐",
            days=2,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert 'class="warning-item warning-item--notable"' in html

    def test_warning_hotfix_commit_has_notable_class(self) -> None:
        """hotfix_commit는 'warning-item--notable' 클래스."""
        signal = WarningSignal(
            kind="hotfix_commit",
            title="Hotfix 커밋",
            description="긴급 대응",
            days=1,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert 'class="warning-item warning-item--notable"' in html

    def test_warning_stale_mr_has_no_extra_class(self) -> None:
        """stale_mr는 추가 심각도 클래스가 없다."""
        signal = WarningSignal(
            kind="stale_mr",
            title="방치된 MR",
            description="30일 이상 대기",
            days=30,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert 'class="warning-item"' in html
        assert "--notable" not in html
        assert "--severe" not in html

    def test_warning_stale_branch_has_no_extra_class(self) -> None:
        """stale_branch는 추가 심각도 클래스가 없다."""
        signal = WarningSignal(
            kind="stale_branch",
            title="방치된 브랜치",
            description="푸시 없음",
            days=20,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert 'class="warning-item"' in html
        assert "--notable" not in html
        assert "--severe" not in html

    def test_warning_has_no_kind_label_in_row(self) -> None:
        """경고 행에 종류 라벨이 없다 (그룹 헤더가 이미 말한다)."""
        signal = WarningSignal(
            kind="stale_branch",
            title="Branch Name",
            description="Push 없음: 15일",
            days=15,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        # 종류 라벨 div가 없다 (기존처럼 <div class="warning-title">가 없다)
        assert "warning-title" not in html

    def test_warning_has_no_days_label_in_row(self) -> None:
        """경고 행에 'N일 경과' div가 없다 (설명과 같은 수를 반복하므로)."""
        signal = WarningSignal(
            kind="stale_branch",
            title="Branch Name",
            description="Push 없음: 15일",
            days=15,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert "warning-days" not in html

    def test_warning_has_no_inline_style(self) -> None:
        """경고 행에 style 속성이 없다 (CSS 클래스로만 스타일링)."""
        signal = WarningSignal(
            kind="stale_mr",
            title="MR #123",
            description="Open 상태 진행 중",
            days=7,
            repo_full_path="org/repo",
            web_url="http://example.com/mr/123",
        )

        html = _render_warning_item(signal)

        # style= 속성이 없다
        assert 'style="' not in html

    def test_warning_has_no_emoji(self) -> None:
        """경고 행에 ⚠️ 이모지가 없다."""
        signal = WarningSignal(
            kind="stale_branch",
            title="Branch Name",
            description="desc",
            days=5,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        assert "⚠️" not in html
        assert "warning-title" not in html  # 종류 라벨도 없으므로 이모지는 당연히 없음

    def test_warning_escapes_xss(self) -> None:
        """제목과 설명의 <script> 태그가 escape된다."""
        signal = WarningSignal(
            kind="stale_mr",
            title="<script>alert('xss')</script>",
            description="<img src=x onerror=alert(1)>",
            days=None,
            repo_full_path="org/repo",
            web_url=None,
        )

        html = _render_warning_item(signal)

        # HTML 태그가 escape되었으므로 브라우저가 실행하지 않는다
        assert "&lt;script&gt;" in html  # <script> 태그가 escape됨
        assert "&lt;img" in html  # <img> 태그가 escape됨
        # 실행 가능한 형태가 없다 (태그가 escape되어 있으므로 브라우저가 해석하지 않음)
        assert "<script>" not in html
        assert "<img" not in html


# ═══ 회귀 방지 (styles.py)


class TestStylesCssRoundTenCompliance:
    """라운드 10 설계 결정이 CSS에 유지되는지 회귀 방지."""

    def test_css_has_no_old_stage_stepper_class(self) -> None:
        """구 스테퍼 클래스(.stage-stepper, .step-active)가 없다."""
        assert ".stage-stepper" not in CSS
        assert "step-active" not in CSS
        assert "step-connector" not in CSS

    def test_css_has_no_text_muted_variable(self) -> None:
        """호환성 토큰 --text-muted가 없다 (인라인 style 제거됨)."""
        assert "--text-muted:" not in CSS

    def test_css_has_no_badge_empty_rule(self) -> None:
        """빈 배지 규칙(.badge-empty)이 없다 (배지 미렌더 구현으로 불필요)."""
        assert ".badge-empty" not in CSS

    def test_css_has_no_important_declarations(self) -> None:
        """!important 선언이 없다 (마크업을 직접 고칠 수 있으므로)."""
        assert "!important" not in CSS

    def test_css_has_round10_palette_hex(self) -> None:
        """벤치마크 hex 팔레트가 있다."""
        assert "#f2f3f5" in CSS  # --bg
        assert "#eaf1fe" in CSS  # --accent-soft, --prog-bg
        assert "#fdebec" in CSS  # --hi-bg

    def test_css_has_no_dead_grid_classes(self) -> None:
        """.card, .grid, .grid-cols- 같은 죽은 CSS 규칙이 없다."""
        # 다만 .cards-grid는 있어야 함 (grid 컬럼 고정)
        assert ".card {" not in CSS  # 수정해서 card 규칙이 없음
        assert ".grid-cols-1" not in CSS  # 일반 grid 클래스 없음
        assert ".participant {" not in CSS  # 낡은 참여 규칙 없음


class TestWarningRowAlignment:
    """경고 행의 링크 정렬 — 링크가 없는 행에서 설명이 밀려나지 않아야 한다."""

    def _signal(self, web_url: str | None) -> WarningSignal:
        return WarningSignal(
            kind="hotfix_commit",
            title="hotfix: 급한 수정",
            description="긴급 대응 커밋",
            repo_full_path="org/repo",
            days=1,
            web_url=web_url,
        )

    def test_link_row_gets_its_own_alignment_hook(self) -> None:
        html = _render_warning_item(self._signal("http://example.com/c/1"))
        assert 'class="warning-link"' in html

    def test_row_without_link_has_no_alignment_hook(self) -> None:
        """링크가 없으면 정렬 훅도 없다 — 설명이 오른쪽으로 밀려가는 것을 막는다."""
        html = _render_warning_item(self._signal(None))
        assert "warning-link" not in html

    def test_alignment_targets_the_link_not_the_last_child(self) -> None:
        """CSS가 마지막 자식을 미는 방식이면 링크 없는 행이 깨진다."""
        assert ".warning-link { margin-left: auto; }" in CSS
        assert ".warning-item > div:last-child" not in CSS


class TestNarrowViewportOverflow:
    """좁은 화면 가로 스크롤 방지 — 닫힌 툴팁이 폭을 늘리던 문제(2라운드 잔존)."""

    def test_canvas_clips_horizontal_overflow(self) -> None:
        """html·body 양쪽에 clip이 있어야 한다 (한쪽만으로는 스크롤이 남는다)."""
        html_rule = CSS[CSS.index("html {") : CSS.index("body {")]
        body_rule = CSS[CSS.index("body {") : CSS.index("a { color")]
        assert "overflow-x: clip" in html_rule
        assert "overflow-x: clip" in body_rule

    def test_uses_clip_not_hidden(self) -> None:
        """hidden은 스크롤 컨테이너를 만들어 열린 말풍선의 가장자리 보정을 깨뜨린다."""
        assert "overflow-x: hidden" not in CSS


class TestRootScrollbarHidden:
    """루트 스크롤바 숨김 — 공간 차지형 스크롤바가 생기고 사라질 때 가로 폭이 튀는 문제."""

    def test_hides_scrollbar_on_both_engines(self) -> None:
        """scrollbar-width(Firefox·Chrome 121+)와 ::-webkit-scrollbar(Safari) 둘 다 필요하다."""
        html_rule = CSS[CSS.index("html {") : CSS.index("body {")]
        assert "scrollbar-width: none" in html_rule
        assert "html::-webkit-scrollbar { display: none; }" in html_rule

    def test_vertical_scrolling_not_disabled(self) -> None:
        """표시만 숨긴다 — 세로 overflow를 자르면 스크롤 자체가 죽는다."""
        assert "overflow-y" not in CSS
        assert "overflow: clip" not in CSS


class TestFeatureSummaryColumnPinning:
    """요약 행 칸 고정 — 배지 없는 행에서 뒤 칸들이 당겨오지 않아야 한다.

    자동 배치에 맡기면 stage="other" 행은 자식이 하나 적어서 스파크라인·규모가
    한 열씩 왼쪽으로 이동하고, 행마다 눈높이가 어긋난다(실측으로 확인된 문제).
    """

    def test_badge_wrapper_has_its_own_hook(self) -> None:
        """배지 래퍼는 스파크라인 래퍼와 tooltip-host를 공유하므로 전용 클래스가 필요하다."""
        html = _render_stage_badge("developing")
        assert "stage-badge-wrap" in html

    def test_each_cell_is_pinned_to_a_column(self) -> None:
        for selector in (
            ".feature-summary > .stage-badge-wrap",
            ".feature-summary > .sparkline-wrap",
            ".feature-summary > .feature-meta",
        ):
            assert selector in CSS, selector

    def test_narrow_viewport_releases_every_pinned_cell(self) -> None:
        """한 열로 접힐 때 고정을 풀지 않으면 없는 열을 참조해 4열 구조가 남는다.

        해제 셀렉터는 고정 규칙과 같은 형태(클래스 2개)여야 한다 — 미디어쿼리는
        특이도를 올려주지 않으므로 `> *` 한 줄로는 고정 규칙에 진다(실측 확인).
        """
        narrow = CSS[CSS.index("@media (max-width: 768px)") :]
        for selector in (
            ".feature-summary > .stage-badge-wrap",
            ".feature-summary > .sparkline-wrap",
            ".feature-summary > .feature-meta",
        ):
            assert selector in narrow, selector
        assert "grid-column: auto" in narrow


class TestFeatureRowHeightIsStable:
    """닫힌 기능 행 높이 고정 — 최근 활동(상대시각)이 없는 행도 같은 높이여야 한다.

    meta 열은 규모·최근활동 두 줄이라, 최근활동이 없으면 한 줄로 줄어들고 행 높이가
    배지(21px)에 지배된다. 실측: 같은 목록에서 닫힌 행이 61px과 43px로 갈렸다.
    """

    def _summary_rule(self) -> str:
        start = CSS.index(".feature-summary {")
        return CSS[start : CSS.index("}", start)]

    def test_summary_row_reserves_two_meta_lines(self) -> None:
        """규모(12.5px) + 최근활동(12px) + 사이 gap(2px) ≈ 39px를 항상 차지한다."""
        assert "min-height: 39px;" in self._summary_rule()

    def test_reservation_is_a_minimum_not_a_fixed_height(self) -> None:
        """좁은 화면에서 한 열로 접히면 자연 높이대로 늘어나야 내용이 잘리지 않는다."""
        assert "\n  height:" not in self._summary_rule()


class TestLineRowHeightIsStable:
    """닫힌 라인 행 높이 고정 — 긴 AI 제목이 두 줄로 접히면 안 된다.

    제목 칸은 폭이 고정(minmax(7rem, 14rem))이라 주간처럼 제목이 길어지면 두 줄이 되고,
    실측에서 닫힌 라인 행이 42.3px과 62.5px로 갈렸다. 행마다 그리드가 따로라 칸 폭을
    내용에 맞춰 늘리면 행끼리 표가 어긋나므로, 같은 행의 가운데 칸(.line-latest)과 같은
    한 줄 말줄임으로 맞춘다.
    """

    def _clamp_rule(self) -> str:
        start = CSS.index(".line-head > .group-ai-title,")
        return CSS[start : CSS.index("}", start)]

    def test_ai_title_and_branch_name_are_clamped_to_one_line(self) -> None:
        """AI 제목이 없는 행은 브랜치명이 그 자리에 오므로 둘 다 잘라야 한다."""
        rule = self._clamp_rule()
        assert ".line-name" in rule
        for declaration in (
            "min-width: 0",
            "overflow: hidden",
            "text-overflow: ellipsis",
            "white-space: nowrap",
        ):
            assert declaration in rule, declaration

    def test_narrow_viewport_lets_the_title_wrap_again(self) -> None:
        """한 열로 접히면 제목이 화면 폭을 다 쓰므로, 자르면 제목만 손실된다."""
        narrow = CSS[CSS.index("@media (max-width: 768px)") :]
        start = narrow.index(".line-head > .group-ai-title,")
        rule = narrow[start : narrow.index("}", start)]
        assert "white-space: normal" in rule
        assert "overflow: visible" in rule
