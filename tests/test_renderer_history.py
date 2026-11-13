"""브랜치 생애 타임라인 렌더 테스트."""

from pulse.models import (
    BranchHistoryView,
    BranchTagDistribution,
    FeatureGroup,
    TaskSummary,
)
from pulse.renderer.sections import (
    _render_history_timeline,
    render_feature_cards,
    render_release_lines,
)
from pulse.renderer.styles import CSS


def make_history(
    *,
    started_on: str = "2026-05-27",
    total_days: int = 62,
    active_days: int = 46,
    total_commits: int = 211,
    truncated: bool = False,
    weeks: tuple[tuple[str, int], ...] = (("2026-07-13", 12), ("2026-07-20", 50)),
    silent_gap_days: int = 0,
    tags: BranchTagDistribution | None = None,
    fix_surge: bool = False,
    behind_count: int | None = None,
    base_branch: str = "develop",
) -> BranchHistoryView:
    """테스트용 생애 뷰 (실측값을 기본으로 둔다)."""
    return BranchHistoryView(
        base_branch=base_branch,
        started_on=started_on,
        total_days=total_days,
        active_days=active_days,
        total_commits=total_commits,
        truncated=truncated,
        week_commit_counts=weeks,
        silent_gap_days=silent_gap_days,
        tags=tags,
        fix_surge=fix_surge,
        behind_count=behind_count,
    )


def make_group(
    history: BranchHistoryView | None = None,
    kind: str = "feature",
) -> FeatureGroup:
    """타임라인 검증용 그룹."""
    return FeatureGroup(
        name="feature/oauth",
        source_rule="branch",
        evidence="feature/oauth",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/oauth",),
        participants=(),
        task_summary=TaskSummary((), (), ()),
        group_kind=kind,  # type: ignore[arg-type]
        branch_history=history,
    )


class TestGracefulDegradation:
    def test_none_history_renders_nothing(self) -> None:
        """브랜치가 기본 하나뿐인 레포 등 — 빈 컨테이너조차 남기지 않는다."""
        assert _render_history_timeline(None) == ""

    def test_zero_commit_history_renders_nothing(self) -> None:
        """base에 이미 병합된 브랜치는 서사가 없다 — 0건 타임라인을 띄우지 않는다."""
        empty = make_history(total_commits=0, active_days=0, weeks=())
        assert _render_history_timeline(empty) == ""


class TestTimelineHead:
    def test_shows_real_start_date_not_observation_date(self) -> None:
        html = _render_history_timeline(make_history())
        assert "05-27" in html
        assert "시작" in html
        assert "62일차" in html

    def test_shows_scale(self) -> None:
        html = _render_history_timeline(make_history())
        assert "커밋 211건" in html
        assert "활동 46일" in html

    def test_truncated_reports_partial_aggregation(self) -> None:
        """총 커밋 수는 정확하고, 집계가 부분적이라는 사실을 별도로 알린다."""
        html = _render_history_timeline(make_history(total_commits=1500, truncated=True))
        assert "커밋 1500건" in html
        assert "최근 구간만 집계" in html

    def test_untruncated_has_no_partial_notice(self) -> None:
        html = _render_history_timeline(make_history(total_commits=211, truncated=False))
        assert "커밋 211건" in html
        assert "최근 구간만 집계" not in html


class TestWeekBars:
    def test_renders_one_bar_per_week(self) -> None:
        html = _render_history_timeline(
            make_history(weeks=(("2026-07-06", 5), ("2026-07-13", 10), ("2026-07-20", 20)))
        )
        assert html.count('class="history-week tooltip-host"') == 3

    def test_peak_week_is_full_height(self) -> None:
        weeks = (("2026-07-13", 10), ("2026-07-20", 20))
        assert "--bar:100%" in _render_history_timeline(make_history(weeks=weeks))

    def test_zero_week_has_no_height(self) -> None:
        html = _render_history_timeline(make_history(weeks=(("2026-07-13", 0), ("2026-07-20", 20))))
        assert "--bar:0%" in html

    def test_small_nonzero_week_keeps_minimum_height(self) -> None:
        """1건인 주가 0건과 구별되어야 한다."""
        weeks = (("2026-07-13", 1), ("2026-07-20", 200))
        assert "--bar:0%" not in _render_history_timeline(make_history(weeks=weeks))

    def test_bar_has_tooltip_with_absolute_count(self) -> None:
        html = _render_history_timeline(make_history(weeks=(("2026-07-20", 50),)))
        assert "커밋 50건" in html

    def test_recent_weeks_are_capped(self) -> None:
        weeks = tuple((f"2026-0{1 + index // 4}-0{1 + index % 4}", index) for index in range(20))
        html = _render_history_timeline(make_history(weeks=weeks))
        assert html.count('class="history-week tooltip-host"') == 12

    def test_no_weeks_renders_no_bar_block(self) -> None:
        html = _render_history_timeline(make_history(weeks=()))
        assert "history-weeks" not in html
        assert "history-chart" not in html

    def test_chart_is_labelled_to_distinguish_from_sparkline(self) -> None:
        """요약 행의 스파크라인(최근 7일 일별)과 역할이 다름을 캡션으로 밝힌다."""
        html = _render_history_timeline(make_history(weeks=(("2026-06-01", 3), ("2026-07-20", 50))))
        assert "주별 추이" in html
        # 기간 축 — 어디부터 어디까지인지
        assert "06-01" in html
        assert "07-20" in html
        # 최댓값 기준을 밝혀 막대 높이의 의미를 알 수 있게 한다
        assert "최다 50건" in html


class TestFacts:
    def test_behind_gap_is_shown(self) -> None:
        html = _render_history_timeline(make_history(behind_count=90))
        assert "develop의 90커밋 미반영" in html
        # 무엇을 뜻하는 수치인지 툴팁으로 설명한다
        assert "tooltip-host" in html
        assert "기준 브랜치에는 있지만" in html

    def test_zero_behind_reads_as_up_to_date(self) -> None:
        html = _render_history_timeline(make_history(behind_count=0))
        assert "develop 최신 상태 반영됨" in html

    def test_unknown_behind_is_omitted(self) -> None:
        html = _render_history_timeline(make_history(behind_count=None))
        assert "최신화" not in html

    def test_tag_composition_uses_commit_convention_words(self) -> None:
        """커밋에 실제로 쓰는 낱말을 그대로 보여준다 (번역하지 않는다)."""
        tags = BranchTagDistribution(
            counts=(("feat", 106), ("fix", 45), ("refactor", 30)), recognized=181, total=181
        )
        html = _render_history_timeline(make_history(tags=tags))
        assert "feat 106" in html
        assert "fix 45" in html
        assert "refactor 30" in html
        assert "기능 106" not in html

    def test_uncommon_tag_is_shown_as_is(self) -> None:
        tags = BranchTagDistribution(counts=(("hotfix", 4),), recognized=4, total=4)
        html = _render_history_timeline(make_history(tags=tags))
        assert "hotfix 4" in html

    def test_absent_tags_omit_composition(self) -> None:
        """인식률이 낮아 tags=None이면 작업 성격 칩을 렌더하지 않는다."""
        html = _render_history_timeline(make_history(tags=None))
        assert "작업 성격" not in html

    def test_fix_surge_badge(self) -> None:
        html = _render_history_timeline(make_history(fix_surge=True))
        assert "history-fact-alert" in html
        assert "수정·검증 작업 집중" in html

    def test_no_surge_no_badge(self) -> None:
        assert "history-fact-alert" not in _render_history_timeline(make_history(fix_surge=False))

    def test_long_silence_is_shown(self) -> None:
        html = _render_history_timeline(make_history(silent_gap_days=9))
        assert "최장 9일" in html

    def test_short_silence_is_omitted(self) -> None:
        """주말 수준의 공백은 신호가 아니다."""
        html = _render_history_timeline(make_history(silent_gap_days=2))
        assert "공백" not in html

    def test_no_facts_omits_block(self) -> None:
        html = _render_history_timeline(make_history())
        assert "history-facts" not in html


class TestPeriodGating:
    def test_daily_view_hides_timeline(self) -> None:
        html = render_feature_cards((make_group(make_history()),), period="daily")
        assert "history-timeline" not in html

    def test_weekly_view_shows_timeline(self) -> None:
        html = render_feature_cards((make_group(make_history()),), period="weekly")
        assert "history-timeline" in html
        assert "05-27" in html

    def test_default_period_is_daily(self) -> None:
        assert "history-timeline" not in render_feature_cards((make_group(make_history()),))

    def test_group_without_history_renders_no_timeline_in_weekly(self) -> None:
        html = render_feature_cards((make_group(None),), period="weekly")
        assert "history-timeline" not in html

    def test_release_line_never_shows_timeline(self) -> None:
        html = render_release_lines((make_group(make_history(), kind="line"),))
        assert "history-timeline" not in html


class TestHorizontalInset:
    """확장 영역 블록들이 하나의 좌우 정렬선을 공유한다.

    여백이 0이면 점선 구분선·소제목이 확장 영역 경계까지 닿아, 들여쓰기된
    .group-analysis 불릿보다 넓은 영역을 차지하는 것처럼 보인다.
    실측(1440px): 수정 전 timeline 41 · task-summary 소제목 57 · 불릿 65로
    정렬선이 셋으로 갈렸고, 수정 후 여섯 블록 전부 65 하나로 모인다.
    """

    def test_expand_blocks_share_one_alignment_rule(self) -> None:
        """블록마다 여백을 반복하지 않고 한 규칙으로 묶는다."""
        assert ".feature-expand > *:not(.group-analysis) {" in CSS

    def test_alignment_uses_the_bullet_indent_token(self) -> None:
        """--space-lg는 .group-analysis ul의 padding-left와 같은 토큰이다."""
        shared = CSS.split(".feature-expand > *:not(.group-analysis) {")[1].split("}")[0]
        assert "margin-left: var(--space-lg);" in shared
        assert "margin-right: var(--space-lg);" in shared

    def test_analysis_is_excluded_from_the_shared_margin(self) -> None:
        """불릿 ul의 padding-left가 이미 정렬선을 만든다 — 여백을 더하면 한 단계 밀린다."""
        assert ":not(.group-analysis)" in CSS

    def test_timeline_declares_no_horizontal_margin_of_its_own(self) -> None:
        """단축 지정(margin: … 0)을 남기면 읽는 사람이 공통 규칙과 충돌로 오해한다."""
        timeline_block = CSS.split(".history-timeline {")[1].split("}")[0]
        assert "margin-top:" in timeline_block
        assert "margin: " not in timeline_block

    def test_inset_moves_the_dashed_border_too(self) -> None:
        """padding으로 주면 점선은 경계에 그대로 남아 문제가 해소되지 않는다."""
        timeline_block = CSS.split(".history-timeline {")[1].split("}")[0]
        assert "padding: var(--space-sm) 0;" in timeline_block
        assert "border-top: 1px dashed" in timeline_block


class TestTaskSummaryFlattened:
    """보이지 않는 배경 카드를 걷어냈다 (회귀 방지).

    .task-summary의 background는 부모(.feature-expand)와 같은 --bg-hover라서
    화면에 박스가 드러나지 않는데, padding만 남아 소제목을 이웃보다 안쪽으로
    밀고 있었다. 실측으로 두 요소의 계산된 배경색이 oklch(0.96 0 0)로 동일함을 확인했다.
    """

    def test_no_invisible_background_card(self) -> None:
        block = CSS.split(".task-summary {")[1].split("}")[0]
        assert "background:" not in block
        assert "border-radius:" not in block

    def test_no_padding_pushing_the_heading_inward(self) -> None:
        block = CSS.split(".task-summary {")[1].split("}")[0]
        assert "padding:" not in block

    def test_list_items_indent_only_once(self) -> None:
        """ul의 padding-left에 좌측 마진까지 더하면 소제목에서 40px 떨어진다."""
        item_block = CSS.split(".task-summary li {")[1].split("}")[0]
        assert "margin: var(--space-xs) 0;" in item_block
