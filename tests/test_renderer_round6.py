"""6차 신규 렌더 함수 테스트 (수명주기 뱃지·스트립·MR 이력·릴리스 열차)."""

from datetime import datetime

from pulse.models import (
    FeatureGroup,
    GroupLifecycleView,
    MergeRequestInfo,
    MRState,
    PromotionRung,
    ReleaseTrain,
    TaskSummary,
)
from pulse.renderer.sections import (
    STALE_PROMOTION_DAYS,
    _render_mr_mini_history,
    render_feature_cards,
    render_release_lines,
    render_release_train,
)
from pulse.renderer.styles import CSS

NOW = datetime(2026, 7, 27, 9, 0, 0)


def make_lifecycle(
    *,
    stage: str = "developing",
    total_days: int = 8,
    stage_days: int = 2,
    active_days: int = 6,
    commits: int = 54,
) -> GroupLifecycleView:
    """테스트용 수명주기 뷰를 만든다."""
    return GroupLifecycleView(
        first_seen="2026-07-20",
        total_days=total_days,
        current_stage=stage,
        current_stage_days=stage_days,
        active_days=active_days,
        cumulative_commits=commits,
    )


def make_group_with_lifecycle(kind: str = "feature") -> FeatureGroup:
    """수명주기 뷰가 붙은 그룹 (뱃지 폐기·기간 게이팅 검증용)."""
    return FeatureGroup(
        name="tiptap",
        source_rule="branch",
        evidence="tiptap",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=("tiptap",),
        participants=(),
        task_summary=TaskSummary((), (), ()),
        group_kind=kind,  # type: ignore[arg-type]
        lifecycle=make_lifecycle(),
    )


def make_rung(
    source: str,
    target: str,
    *,
    merged_at: datetime | None = datetime(2026, 7, 24, 17, 0, 0),
    open_count: int = 0,
    merged_count: int = 5,
    iid: int | None = 3010,
) -> PromotionRung:
    """테스트용 승격 사다리 칸을 만든다."""
    return PromotionRung(
        source=source,
        target=target,
        last_merged_at=merged_at,
        last_mr_iid=iid,
        merged_count=merged_count,
        open_count=open_count,
    )


def make_mr(
    iid: int,
    *,
    title: str = "승격",
    target: str = "devqa",
    source: str = "develop",
    state: MRState = "merged",
    is_draft: bool = False,
    merged_at: datetime | None = datetime(2026, 7, 24, 17, 0, 0),
    web_url: str | None = None,
) -> MergeRequestInfo:
    """테스트용 MR을 만든다 (author_name은 노출 금지 검증용으로 식별 가능한 값 사용)."""
    return MergeRequestInfo(
        iid=iid,
        title=title,
        state=state,
        is_draft=is_draft,
        labels=(),
        source_branch=source,
        target_branch=target,
        author_name="ZZUNIQUEAUTHOR",
        created_at=datetime(2026, 7, 23, 10, 0, 0),
        updated_at=datetime(2026, 7, 24, 17, 0, 0),
        merged_at=merged_at,
        reviews=(),
        is_external=False,
        web_url=f"http://example.com/mr/{iid}" if web_url is None else web_url,
    )


def make_group(merge_requests: tuple[MergeRequestInfo, ...] = ()) -> FeatureGroup:
    """테스트용 그룹을 만든다."""
    return FeatureGroup(
        name="develop",
        source_rule="branch",
        evidence="develop",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=merge_requests,
        branch_names=("develop",),
        participants=(),
        task_summary=TaskSummary((), (), ()),
        group_kind="line",
    )


class TestLifecycleBadgeRemoved:
    """수명주기 뱃지는 폐기됐다 (회귀 방지).

    뱃지의 "진행 N일차"는 도구가 그룹을 처음 관측한 날 기준이라, 브랜치가 실제로
    갈라진 날 기준인 생애 타임라인의 "N일차"와 같은 화면에서 다른 값을 보였다
    (실측: 같은 그룹이 뱃지 13일차 · 타임라인 62일차). 두 수치를 화면에서 조정할
    방법이 없고 관측 기준값은 프로젝트의 속성이 아니라 도구 도입 시점의 부산물이므로,
    더 정확한 타임라인만 남기고 뱃지를 걷어냈다.
    """

    def test_weekly_row_has_no_lifecycle_badge(self) -> None:
        html = render_feature_cards((make_group_with_lifecycle(),), period="weekly")
        assert "lifecycle-badge" not in html

    def test_observation_based_day_count_is_gone(self) -> None:
        html = render_feature_cards((make_group_with_lifecycle(),), period="weekly")
        assert "진행 8일차" not in html
        assert "첫 관측" not in html


class TestMrMiniHistory:
    """행 확장 내 MR 미니 이력."""

    def test_no_merge_requests_renders_empty(self) -> None:
        assert _render_mr_mini_history(make_group()) == ""

    def test_renders_iid_title_and_target_branch(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3010, title="버전 업데이트"),)))
        assert "3010" in html
        assert "버전 업데이트" in html
        assert "devqa" in html

    def test_never_exposes_author_name(self) -> None:
        # 개인 실적·개인 이름 노출 금지 (프로젝트 정책)
        html = _render_mr_mini_history(make_group((make_mr(3010),)))
        assert "ZZUNIQUEAUTHOR" not in html

    def test_limits_to_five_entries(self) -> None:
        mrs = tuple(make_mr(iid, title=f"승격 {iid}") for iid in range(3001, 3011))
        html = _render_mr_mini_history(make_group(mrs))
        rendered = sum(1 for iid in range(3001, 3011) if str(iid) in html)
        assert rendered <= 5


class TestMrMiniHistoryReadability:
    """MR 이력은 용어 설명 없이도 읽힌다.

    이전 표기 `!3015 · Devqa · ✅ sqa · 07-28`은 실제 사용자가 세 가지를 물어봤다:
    이모지가 무슨 뜻인지, `!3015`가 무슨 번호인지, 뒤 낱말(sqa)이 무엇인지.
    """

    def test_state_uses_korean_badge_not_emoji(self) -> None:
        # ✅·❌는 대상 브랜치 바로 앞에 붙어 "브랜치의 성패"처럼 읽혔고,
        # ❌(닫힘=합치지 않고 종료)를 실패로 오해하게 했다.
        html = _render_mr_mini_history(make_group((make_mr(3015),)))
        assert "병합됨" in html
        for emoji in ("✅", "❌", "🔵", "⚪"):
            assert emoji not in html

    def test_closed_state_reads_as_closed(self) -> None:
        # 배지 기준으로 확인한다 — 툴팁 범례에는 네 상태 이름이 모두 들어 있다
        html = _render_mr_mini_history(make_group((make_mr(3012, state="closed", merged_at=None),)))
        assert ">닫힘</span>" in html
        assert ">병합됨</span>" not in html

    def test_open_state_reads_as_open(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3020, state="open", merged_at=None),)))
        assert "열림" in html

    def test_draft_is_distinguished_from_open(self) -> None:
        # 초안은 아직 리뷰 대상이 아니다 — "열림"으로 뭉치면 진행 상태를 잘못 읽는다
        html = _render_mr_mini_history(
            make_group((make_mr(3021, state="open", is_draft=True, merged_at=None),))
        )
        assert "초안" in html

    def test_shows_merge_direction_not_bare_target(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3015, source="devqa", target="sqa"),)))
        assert "devqa" in html
        assert "sqa" in html
        assert "→" in html

    def test_number_is_labeled_and_linked(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3015),)))
        assert "MR !3015" in html
        assert 'href="http://example.com/mr/3015"' in html

    def test_number_without_url_stays_plain_text(self) -> None:
        # 링크 없이도 번호는 보여야 한다 (우아한 저하)
        html = _render_mr_mini_history(make_group((make_mr(3015, web_url=""),)))
        assert "MR !3015" in html
        assert "<a href" not in html

    def test_date_says_which_event_it_is(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3015),)))
        assert "07-24 (금) 병합" in html

    def test_closed_date_labeled_closed(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3012, state="closed", merged_at=None),)))
        assert "07-24 (금) 닫힘" in html

    def test_open_date_labeled_updated(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3020, state="open", merged_at=None),)))
        assert "07-24 (금) 갱신" in html

    def test_heading_and_tooltip_explain_terms(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3015),)))
        assert "MR 이력" in html
        assert "tooltip-bubble" in html
        assert "Merge Request" in html

    def test_truncated_history_reports_total(self) -> None:
        mrs = tuple(make_mr(iid) for iid in range(3001, 3011))
        html = _render_mr_mini_history(make_group(mrs))
        assert "최근 5건" in html
        assert "전체 10건" in html

    def test_untruncated_history_shows_plain_count(self) -> None:
        html = _render_mr_mini_history(make_group((make_mr(3015), make_mr(3014))))
        assert "2건" in html
        assert "전체" not in html

    def test_title_and_branch_are_escaped(self) -> None:
        html = _render_mr_mini_history(
            make_group((make_mr(3015, title="<script>x</script>", source="a<b"),))
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "a&lt;b" in html


class TestReleaseTrain:
    """릴리스 승격 사다리 패널."""

    def test_none_train_renders_empty(self) -> None:
        assert render_release_train(None, NOW) == ""

    def test_empty_rungs_renders_empty(self) -> None:
        # 라인→라인 MR이 없는 레포(MR 0건)는 패널 흔적도 남기지 않는다
        assert render_release_train(ReleaseTrain(rungs=()), NOW) == ""

    def test_contiguous_chain_renders_each_line_once(self) -> None:
        # develop → devqa → sqa → master 체인에서 중간 라인 이름이 중복되면 안 된다
        train = ReleaseTrain(
            rungs=(
                make_rung("develop", "devqa"),
                make_rung("devqa", "sqa"),
                make_rung("sqa", "master"),
            )
        )
        html = render_release_train(train, NOW)
        # 쌍 나열("develop → devqa ─▶ devqa → sqa")이면 중간 라인이 2번 등장해 실패한다
        for line in ("develop", "devqa", "sqa", "master"):
            assert html.count(line) == 1, f"{line}: {html.count(line)}회 등장"

    def test_non_chain_falls_back_to_pair_rendering(self) -> None:
        # 분기(한 source가 두 target)면 노드로 잇지 않고 쌍으로 나열한다
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa"), make_rung("develop", "sqa")))
        html = render_release_train(train, NOW)
        assert "develop → devqa" in html
        assert "develop → sqa" in html

    def test_shows_last_promotion_date_only_as_date(self) -> None:
        # merged_at은 구버전 GitLab에서 updated_at 근사이므로 시각을 표기하지 않는다
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa"),))
        html = render_release_train(train, NOW)
        assert "07-24" in html
        assert "17:00" not in html

    def test_shows_waiting_count_when_open_promotion_exists(self) -> None:
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa", open_count=2),))
        assert "대기 2" in render_release_train(train, NOW)

    def test_marks_stale_rung(self) -> None:
        stale_at = NOW.replace(day=NOW.day - STALE_PROMOTION_DAYS - 1)
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa", merged_at=stale_at),))
        assert "train-rung--stale" in render_release_train(train, NOW)

    def test_fresh_rung_is_not_marked_stale(self) -> None:
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa", merged_at=NOW),))
        assert "train-rung--stale" not in render_release_train(train, NOW)

    def test_missing_now_does_not_mark_stale(self) -> None:
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa"),))
        assert "train-rung--stale" not in render_release_train(train, None)

    def test_never_renders_percentage(self) -> None:
        # % 진행률은 가짜 정밀도이므로 금지 (PRP 제외 항목)
        train = ReleaseTrain(rungs=(make_rung("develop", "devqa"), make_rung("devqa", "sqa")))
        assert "%" not in render_release_train(train, NOW)

    def test_escapes_branch_names(self) -> None:
        train = ReleaseTrain(rungs=(make_rung("develop", "<script>x</script>"),))
        html = render_release_train(train, NOW)
        assert "<script>" not in html


class TestLifecyclePeriodGating:
    """누적 서사(생애 타임라인)는 주간 뷰 전용 (일간은 같은 값이 반복돼 정보량이 없다)."""

    def test_line_row_never_shows_history(self) -> None:
        # 라인은 상시 존재하는 통로 — 일간·주간 어느 쪽에서도 누적 서사를 렌더하지 않는다
        html = render_release_lines((make_group_with_lifecycle("line"),))
        assert "history-timeline" not in html


class TestTaskLabelSingleLine:
    """아이콘과 소제목이 한 줄에 붙어야 한다 (strong의 display:block 회귀 방지)."""

    def _group_with_details(self) -> FeatureGroup:
        return FeatureGroup(
            name="tiptap",
            source_rule="branch",
            evidence="tiptap",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=("tiptap",),
            participants=(),
            task_summary=TaskSummary(
                commit_titles=("표 편집 수정",),
                open_mr_titles=("MR 제목",),
                active_branch_names=("tiptap",),
            ),
            group_kind="feature",
        )

    def test_icon_and_label_share_one_element(self) -> None:
        html = render_feature_cards((self._group_with_details(),))
        for icon, label in (("📝", "커밋"), ("🔀", "MR"), ("🌿", "브랜치")):
            assert f'<div class="task-label">{icon} <strong>{label}</strong></div>' in html

    def test_task_label_count_matches_sections(self) -> None:
        html = render_feature_cards((self._group_with_details(),))
        assert html.count('class="task-label"') == 3


class TestLineRowDetails:
    """라인 행을 펼치면 기능 행 수준의 상세가 나온다."""

    def _line_group(self) -> FeatureGroup:
        return FeatureGroup(
            name="develop",
            source_rule="branch",
            evidence="develop",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(make_mr(3010, title="정기 배포"),),
            branch_names=("develop",),
            participants=(),
            task_summary=TaskSummary(
                commit_titles=("직접 푸시한 수정",),
                open_mr_titles=(),
                active_branch_names=("develop",),
            ),
            group_kind="line",
        )

    def test_expand_contains_commit_details(self) -> None:
        # MR 없이 직접 커밋·푸시하는 라인도 상세가 보여야 한다
        html = render_release_lines((self._line_group(),))
        assert "직접 푸시한 수정" in html
        assert 'class="task-label"' in html

    def test_expand_contains_analysis_slot(self) -> None:
        html = render_release_lines((self._line_group(),))
        assert "PULSE_GROUP_ANALYSIS_SLOT:org/repo::develop" in html

    def test_summary_keeps_title_slot_and_name(self) -> None:
        html = render_release_lines((self._line_group(),))
        assert "PULSE_GROUP_AI_TITLE_SLOT:org/repo::develop" in html
        assert '<div class="line-name">develop</div>' in html

    def test_summary_shows_scale_and_mr_count(self) -> None:
        html = render_release_lines((self._line_group(),))
        assert "커밋 0 · MR 1" in html

    def test_expand_never_exposes_author(self) -> None:
        html = render_release_lines((self._line_group(),))
        assert "ZZUNIQUEAUTHOR" not in html


class TestLineRowDoesNotClipTooltips:
    """라인 행이 안쪽 툴팁을 자르지 않는다.

    .line-row에 overflow: hidden이 있으면 확장 영역의 MR 이력 툴팁이 위로 열릴 때
    행의 윗변에서 잘린다(실측: 말풍선 206px 중 159px 잘림). 형제인 .feature-row는
    자르지 않고 자식이 각자 모서리를 둥글게 해서 같은 모양을 만든다.
    """

    def _line_rule(self) -> str:
        start = CSS.index(".line-row {")
        return CSS[start : CSS.index(".line-summary {", start)]

    def test_line_row_does_not_clip_overflow(self) -> None:
        assert "overflow" not in self._line_rule()

    def test_summary_rounds_its_own_corners_instead(self) -> None:
        """자르지 않아도 hover 배경이 모서리를 넘지 않아야 한다."""
        rule = self._line_rule()
        assert ".line-row > summary:hover { background: #f8f9fb; border-radius: 10px; }" in rule

    def test_open_summary_squares_its_bottom_corners(self) -> None:
        """펼친 상태의 아래 모서리는 각져야 확장 영역과 이어진다.

        :hover와 명시도가 같으므로 [open] 규칙이 뒤에 와야 이긴다.
        """
        rule = self._line_rule()
        hover_at = rule.index("> summary:hover")
        open_at = rule.index("[open] > summary")
        assert open_at > hover_at
        assert "border-radius: 10px 10px 0 0" in rule[open_at:]
