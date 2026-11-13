"""기능 그룹 확장형 리스트 행 렌더링 테스트 (test_renderer_feature_rows.py)."""

from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal

import pytest

from pulse.grouper.group import _derive_task_summary
from pulse.models import (
    CommitInfo,
    FeatureGroup,
    FeatureStage,
    MergeRequestInfo,
    MRState,
    TaskSummary,
)
from pulse.renderer.sections import (
    _format_relative_time,
    _render_feature_row,
    _render_sparkline_svg,
    _render_stage_badge,
    render_feature_cards,
    render_release_lines,
)
from pulse.renderer.styles import CSS


def _make_group(
    name: str = "feature/test",
    stage: FeatureStage = "developing",
    group_kind: Literal["feature", "line"] = "feature",
    commits: tuple[CommitInfo, ...] = (),
    issue_keys: tuple[str, ...] = (),
    daily_commit_counts: tuple[tuple[str, int], ...] = (),
    last_activity_at: datetime | None = None,
) -> FeatureGroup:
    """테스트용 그룹 생성."""
    return FeatureGroup(
        name=name,
        source_rule="branch",
        evidence="",
        stage=stage,
        repo_full_path="org/repo",
        commits=commits,
        merge_requests=(),
        branch_names=(name,),
        participants=(),
        task_summary=TaskSummary(
            commit_titles=(),
            open_mr_titles=(),
            active_branch_names=(),
        ),
        group_kind=group_kind,
        issue_keys=issue_keys,
        daily_commit_counts=daily_commit_counts,
        last_activity_at=last_activity_at,
    )


def _make_commit(
    message: str = "test commit",
    authored_at: datetime | None = None,
    changed_files: tuple[str, ...] = (),
) -> CommitInfo:
    """테스트용 커밋 생성."""
    if authored_at is None:
        authored_at = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    return CommitInfo(
        sha="abc123",
        author_name="team",
        authored_at=authored_at,
        message=message,
        branch="feature/test",
        changed_files=changed_files,
        web_url="https://example.com/commit/abc123",
    )


# ═══ render_feature_cards 테스트


def test_render_feature_rows_details_markup() -> None:
    """기능 그룹이 <details class="feature-row"> 마크업으로 렌더된다."""
    html = render_feature_cards((_make_group(),))
    assert '<details class="feature-row">' in html
    assert "<summary>" in html
    assert "</summary>" in html
    assert "</details>" in html


def test_render_feature_rows_sorted_by_commit_count() -> None:
    """기능 그룹이 커밋 수 내림차순으로 정렬된다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)

    c1 = _make_commit("a", authored_at=now, changed_files=("file1.py",))
    c2 = _make_commit("b", authored_at=now, changed_files=("file2.py",))

    g1 = _make_group(name="feature/few", commits=(c1,), last_activity_at=now)
    g2 = _make_group(name="feature/many", commits=(c1, c2), last_activity_at=now)

    html = render_feature_cards((g1, g2), generated_at=now)
    # g2(2커밋)가 g1(1커밋)보다 먼저 나와야 함
    idx_many = html.find("feature/many")
    idx_few = html.find("feature/few")
    assert idx_many < idx_few


def test_render_feature_rows_merged_after_active() -> None:
    """merged 그룹은 활성 그룹(developing/reviewing) 뒤로 정렬된다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    c = _make_commit("test", authored_at=now, changed_files=("f.py",))

    g_active = _make_group(
        name="feature/active", stage="developing", commits=(c,), last_activity_at=now
    )
    g_merged = _make_group(
        name="feature/merged", stage="merged", commits=(c,), last_activity_at=now
    )

    html = render_feature_cards((g_merged, g_active), generated_at=now)
    idx_active = html.find("feature/active")
    idx_merged = html.find("feature/merged")
    assert idx_active < idx_merged


def test_render_feature_rows_includes_sparkline() -> None:
    """기능 그룹의 summary에 스파크라인이 포함된다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    daily_counts = (
        ("2026-07-22", 3),
        ("2026-07-21", 2),
    )
    g = _make_group(daily_commit_counts=daily_counts)

    html = _render_feature_row(g, generated_at=now)
    assert '<svg class="sparkline"' in html
    assert "viewBox=" in html


def test_render_feature_rows_shows_scale() -> None:
    """기능 그룹의 규모('커밋 N · 파일 M')가 표시된다."""
    c1 = _make_commit("a", changed_files=("file1.py", "file2.py"))
    c2 = _make_commit("b", changed_files=("file2.py", "file3.py"))
    g = _make_group(commits=(c1, c2))

    html = _render_feature_row(g)
    # 커밋 2개, 파일 3개(합집합)
    assert "커밋 2" in html
    assert "파일 3" in html


def test_render_feature_rows_shows_relative_time() -> None:
    """기능 그룹의 마지막 활동 상대시간이 표시된다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    target = datetime(2026, 7, 22, 9, 30, 0, tzinfo=timezone.utc)
    g = _make_group(last_activity_at=target)

    html = _render_feature_row(g, generated_at=now)
    assert "30분 전" in html


def test_render_feature_rows_ai_title_slot_preserved() -> None:
    """AI 제목 슬롯이 정확한 마커 형식으로 유지된다."""
    g = _make_group(name="feature/auth")
    html = _render_feature_row(g)
    assert "<!--PULSE_GROUP_AI_TITLE_SLOT:org/repo::feature/auth-->" in html


def test_render_feature_rows_ai_analysis_slot_preserved() -> None:
    """AI 분석 슬롯이 정확한 마커 형식으로 유지된다."""
    g = _make_group(name="feature/oauth")
    html = _render_feature_row(g)
    assert "<!--PULSE_GROUP_ANALYSIS_SLOT:org/repo::feature/oauth-->" in html


def test_render_feature_rows_fallback_branch_name() -> None:
    """AI 제목 미주입 시 브랜치명이 폴백으로 표시된다."""
    g = _make_group(name="feature/fallback")
    html = _render_feature_row(g)
    assert 'class="group-name"' in html
    assert "feature/fallback" in html


def test_render_feature_rows_issue_key_links_with_template() -> None:
    """이슈 키가 URL 템플릿으로 링크되고 escape된다."""
    g = _make_group(issue_keys=("DOCS-123",))
    template = "https://jira.example.com/browse/{key}"
    html = _render_feature_row(g, issue_url_template=template)

    assert '<a href="https://jira.example.com/browse/DOCS-123"' in html
    assert 'rel="noopener"' in html
    assert 'target="_blank"' in html


def test_render_feature_rows_issue_keys_plain_without_template() -> None:
    """이슈 템플릿 없으면 이슈 키가 텍스트로만 표시된다."""
    g = _make_group(issue_keys=("DOCS-456",))
    html = _render_feature_row(g, issue_url_template=None)

    assert "DOCS-456" in html
    assert "href=" not in html or "jira" not in html


# ═══ render_release_lines 테스트


def test_render_release_lines_expandable_row_markup() -> None:
    """라인 그룹이 확장형 <details class="line-row"> 마크업으로 렌더된다.

    MR 없이 라인에 직접 커밋하는 경우가 있어 표가 아니라 펼침 행으로 상세를 제공한다.
    """
    g = _make_group(name="release/main", group_kind="line")
    html = render_release_lines((g,))

    assert '<details class="line-row">' in html
    assert "<summary>" in html
    assert '<div class="feature-expand">' in html
    assert "<table" not in html


def test_render_release_lines_shows_latest_commit() -> None:
    """라인 그룹의 최근 비머지 커밋 제목이 표시된다."""
    c1 = _make_commit("Merge pull request")  # 머지 커밋 (제외)
    c2 = _make_commit(
        "feat: important change",
        authored_at=datetime(2026, 7, 22, 11, 0, 0, tzinfo=timezone.utc),
    )
    g = _make_group(name="release/main", group_kind="line", commits=(c1, c2))

    html = render_release_lines((g,))
    assert "feat: important change" in html
    assert "Merge pull request" not in html or html.find("feat:") < html.find("Merge")


def test_render_release_lines_filters_line_kind() -> None:
    """라인 그룹만 필터링되어 표시된다 (feature 그룹은 제외)."""
    g_feature = _make_group(name="feature/test", group_kind="feature")
    g_line = _make_group(name="release/main", group_kind="line")

    html = render_release_lines((g_feature, g_line))
    assert "release/main" in html
    assert "feature/test" not in html


def test_render_release_lines_empty_when_no_lines() -> None:
    """라인 그룹이 없으면 빈 문자열을 반환한다."""
    g = _make_group(group_kind="feature")
    html = render_release_lines((g,))
    assert html == ""


def test_render_release_lines_analysis_slot_preserved() -> None:
    """라인 그룹의 분석 슬롯이 정확한 마커 형식으로 유지된다."""
    g = _make_group(name="release/prod", group_kind="line")
    html = render_release_lines((g,))
    assert "<!--PULSE_GROUP_ANALYSIS_SLOT:org/repo::release/prod-->" in html


# ═══ 헬퍼 함수 테스트


def test_render_sparkline_svg_valid() -> None:
    """스파크라인이 유효한 SVG를 생성한다."""
    counts = (
        ("2026-07-22", 5),
        ("2026-07-21", 3),
        ("2026-07-20", 2),
    )
    svg = _render_sparkline_svg(counts)

    assert "<svg" in svg
    assert "viewBox=" in svg
    assert "<rect" in svg
    assert "fill=" in svg


def test_render_sparkline_svg_empty() -> None:
    """빈 커밋 히스토그램은 자리 유지용 빈 슬롯을 반환한다."""
    svg = _render_sparkline_svg(())
    assert '<span class="sparkline-wrap sparkline-empty"></span>' in svg


@pytest.mark.parametrize(
    "stage,expected_class",
    [
        ("developing", "b-prog"),
        ("reviewing", "b-qa"),
        ("merged", "b-done"),
        ("other", None),  # other는 배지를 렌더하지 않음
    ],
)
def test_render_stage_badge_states(stage: str, expected_class: str | None) -> None:
    """단계별 배지가 올바른 CSS 클래스를 포함한다."""
    html = _render_stage_badge(stage)  # type: ignore[arg-type]

    if expected_class is None:
        # other 단계는 빈 문자열 반환
        assert html == ""
    else:
        # 배지가 있으면 tooltip-host와 배지 span을 포함
        assert 'class="tooltip-host' in html  # 래퍼에 전용 클래스가 덧붙는다
        assert f'<span class="badge {expected_class}">' in html


@pytest.mark.parametrize(
    "delta_seconds,expected",
    [
        (30, "방금 전"),
        (300, "5분 전"),
        (3600, "1시간 전"),
        (86400, "어제"),
        (172800, "2일 전"),
    ],
)
def test_format_relative_time_cases(delta_seconds: int, expected: str) -> None:
    """상대시간이 정확하게 포맷된다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    target = datetime.fromtimestamp(now.timestamp() - delta_seconds, tz=timezone.utc)

    result = _format_relative_time(target, now)
    assert result == expected


def test_format_relative_time_none_handling() -> None:
    """None 값이 전달되면 빈 문자열을 반환한다."""
    now = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)

    assert _format_relative_time(None, now) == ""
    assert _format_relative_time(now, None) == ""


def test_render_stage_badge_has_tooltip() -> None:
    """배지 툴팁이 설명 한 줄 + 판정 기준 불릿으로 구성된다."""
    from pulse.renderer.sections import (
        STAGE_STEPPER_TOOLTIP,
        STAGE_STEPPER_TOOLTIP_RULES,
        _render_stage_badge,
    )

    # other를 제외한 모든 단계는 배지와 툴팁을 렌더 (other는 빈 문자열 반환)
    for stage in ("developing", "reviewing", "merged"):
        html = _render_stage_badge(stage)
        assert 'class="tooltip-host' in html  # 래퍼에 전용 클래스가 덧붙는다
        assert '<span class="badge' in html
        assert f'<span class="tooltip-lead">{STAGE_STEPPER_TOOLTIP}</span>' in html
        # 판정 기준은 한 줄로 이어붙이지 않고 불릿으로 나눈다
        assert "<ul>" in html
        for rule in STAGE_STEPPER_TOOLTIP_RULES:
            assert f"<li>{rule}</li>" in html

    # other는 빈 문자열 반환
    assert _render_stage_badge("other") == ""


def test_render_sparkline_svg_has_tooltip() -> None:
    """스파크라인 툴팁이 설명 한 줄 + 읽는 법 불릿으로 구성된다."""
    from pulse.renderer.sections import (
        SPARKLINE_TOOLTIP,
        SPARKLINE_TOOLTIP_NOTES,
        _render_sparkline_svg,
    )

    html = _render_sparkline_svg((("2026-07-21", 2), ("2026-07-22", 5)))
    assert '<span class="tooltip-host sparkline-wrap">' in html
    assert f'<span class="tooltip-lead">{SPARKLINE_TOOLTIP}</span>' in html
    for note in SPARKLINE_TOOLTIP_NOTES:
        assert f"<li>{note}</li>" in html


def test_render_feature_row_includes_empty_sparkline_slot() -> None:
    """스파크라인이 없는 행도 자리 유지용 빈 슬롯을 포함한다."""
    # 스파크라인 데이터 없는 그룹
    g_no_sparkline = _make_group(daily_commit_counts=())

    # 스파크라인 데이터 있는 그룹
    g_with_sparkline = _make_group(daily_commit_counts=(("2026-07-22", 3),))

    html_empty = _render_feature_row(g_no_sparkline)
    html_full = _render_feature_row(g_with_sparkline)

    # 빈 슬롯이 포함되어야 함 (자리 유지용)
    assert '<span class="sparkline-wrap sparkline-empty"></span>' in html_empty
    # 실제 SVG 스파크라인도 포함되어야 함
    assert '<svg class="sparkline"' in html_full


# ═══ 커밋 목록 "외 N건" 꼬리표 테스트


def _make_mr(iid: int, title: str, state: MRState = "open") -> MergeRequestInfo:
    """테스트용 MR 생성."""
    moment = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    return MergeRequestInfo(
        iid=iid,
        title=title,
        state=state,
        is_draft=False,
        labels=(),
        source_branch="feature/test",
        target_branch="develop",
        author_name="team",
        created_at=moment,
        updated_at=moment,
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url=f"https://example.com/mr/{iid}",
    )


def _make_group_with_derived_summary(
    commits: tuple[CommitInfo, ...],
    merge_requests: tuple[MergeRequestInfo, ...] = (),
    branch_names: tuple[str, ...] = ("feature/test",),
) -> FeatureGroup:
    """실제 절단 로직(_derive_task_summary)을 거친 그룹.

    상한 값(커밋 3·MR 2·브랜치 3)을 테스트에 박아두지 않기 위해 그룹 파생 함수를
    그대로 쓴다 — 상한이 바뀌면 이 테스트들도 함께 따라간다.
    """
    return replace(
        _make_group(commits=commits),
        merge_requests=merge_requests,
        task_summary=_derive_task_summary(commits, merge_requests, branch_names),
    )


def _commit_section(html: str) -> str:
    """커밋 소제목 뒤의 <ul> 블록만 잘라낸다."""
    after_label = html.split("📝 <strong>커밋</strong>")[1]
    return after_label.split("<ul>")[1].split("</ul>")[0]


def test_commit_list_appends_hidden_count_tail() -> None:
    """상한을 넘긴 커밋은 잘린 건수를 "외 N건"으로 알린다."""
    commits = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(5))

    html = _render_feature_row(_make_group_with_derived_summary(commits))

    assert '<li class="task-more">외 2건</li>' in html


def test_no_tail_when_nothing_is_hidden() -> None:
    """상한에 못 미치면 꼬리표를 붙이지 않는다."""
    commits = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(3))

    html = _render_feature_row(_make_group_with_derived_summary(commits))

    assert "task-more" not in html


def test_tail_does_not_count_merge_commits() -> None:
    """머지 커밋은 목록에서 빠지므로 꼬리표 건수에도 들어가지 않는다.

    목록에 결코 나올 수 없는 건수를 약속하면 안 된다.
    """
    real = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(4))
    merges = tuple(
        _make_commit(message=f"Merge branch 'topic/{index}' into develop") for index in range(3)
    )

    html = _render_feature_row(_make_group_with_derived_summary(real + merges))

    assert '<li class="task-more">외 1건 (머지·중복 제외)</li>' in html
    assert "외 4건" not in html


def test_tail_explains_gap_only_when_header_count_differs() -> None:
    """헤더의 "커밋 N"과 꼬리표 합이 맞으면 사유를 덧붙이지 않는다.

    맞는데도 "(머지·중복 제외)"를 달면 빠진 것이 있다고 오해시킨다.
    """
    clean = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(5))

    html = _render_feature_row(_make_group_with_derived_summary(clean))

    assert '<li class="task-more">외 2건</li>' in html
    assert "머지·중복 제외" not in html


def test_tail_does_not_count_duplicate_titles() -> None:
    """제목 중복 제거 후 남는 수를 센다 — 같은 제목 반복은 꼬리표를 만들지 않는다."""
    unique = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(3))
    duplicates = tuple(_make_commit(message="feat: 작업 0") for _ in range(4))

    html = _render_feature_row(_make_group_with_derived_summary(unique + duplicates))

    assert "task-more" not in html


def test_tail_is_distinguishable_from_real_titles() -> None:
    """꼬리표는 전용 클래스를 달아 실제 커밋 제목과 구별된다."""
    commits = tuple(_make_commit(message=f"feat: 작업 {index}") for index in range(6))

    section = _commit_section(_render_feature_row(_make_group_with_derived_summary(commits)))

    assert section.count("<li>") == 3  # 제목은 상한만큼만
    assert section.count('<li class="task-more">') == 1


def test_mr_and_branch_lists_have_no_tail() -> None:
    """MR·브랜치는 상한 도달 실측이 0건이라 꼬리표를 만들지 않는다."""
    merge_requests = tuple(_make_mr(iid=index, title=f"MR {index}") for index in range(5))
    branch_names = tuple(f"feature/branch-{index}" for index in range(5))
    group = _make_group_with_derived_summary(
        commits=(), merge_requests=merge_requests, branch_names=branch_names
    )

    html = _render_feature_row(group)

    assert "🔀 <strong>MR</strong>" in html  # MR 목록 자체는 렌더된다
    assert "task-more" not in html


def test_release_line_rows_also_get_the_tail() -> None:
    """라인 표(develop·test 등)에도 꼬리표가 붙는다.

    실측상 절단 격차가 가장 큰 곳이 라인 그룹이다 (test: 원본 31 → 제목 15).
    기능 행만 고치고 라인 행을 빠뜨리면 정작 필요한 쪽이 빈다.
    """
    commits = tuple(_make_commit(message=f"fix: 검증 보정 {index}") for index in range(9))
    group = replace(_make_group_with_derived_summary(commits), name="test", group_kind="line")

    html = render_release_lines((group,))

    assert '<li class="task-more">외 6건</li>' in html


def test_css_strips_bullet_from_tail() -> None:
    """꼬리표에는 불릿을 주지 않는다 — 붙이면 커밋 제목처럼 읽힌다."""
    assert ".task-summary li.task-more:before { content: none; }" in CSS
    assert ".task-summary li.task-more { color: var(--muted); }" in CSS
