"""7개 섹션 렌더링 함수 + 라벨 상수."""

from datetime import date, datetime, timedelta

from pulse.grouper.group import normalize_commit_titles
from pulse.models import (
    BranchHistoryView,
    BranchTagDistribution,
    DiffSummary,
    FeatureGroup,
    FeatureStage,
    MergeRequestInfo,
    MRState,
    NewWorkSignal,
    ParticipationEntry,
    PromotionRung,
    ReleaseTrain,
    WarningKind,
    WarningSignal,
)
from pulse.renderer.escape import escape_html, escape_url
from pulse.renderer.textmark import (
    IMPACT_PARAGRAPH_LABEL,
    apply_emphasis,
    is_attention_line,
    split_brief_paragraphs,
    strip_emphasis,
)

# ═══ 라벨 상수 (매직 문자열 금지)
_WEEKDAY_KOREAN = ["월", "화", "수", "목", "금", "토", "일"]

STAGE_LABELS: dict[FeatureStage, str] = {
    "developing": "진행 중",
    "reviewing": "리뷰 중",
    "merged": "머지됨",
    "other": "—",
}

# 툴팁 문안 — 판정 기준처럼 나열 성격인 내용은 한 줄로 이어붙이지 않고 불릿으로 나눈다.
STAGE_STEPPER_TOOLTIP = "진행 단계는 활동으로 자동 추정합니다 (진행 → 리뷰 → 완료)"
STAGE_STEPPER_TOOLTIP_RULES = (
    "48시간 안에 머지된 MR이 있으면 완료",
    "리뷰 활동이 있거나 24시간 지난 open MR이 있으면 리뷰",
    "draft·open MR이 있거나 7일 안에 push가 있으면 진행",
)

SPARKLINE_TOOLTIP = "최근 7일 일별 커밋 수"
SPARKLINE_TOOLTIP_NOTES = (
    "왼쪽이 과거, 오른쪽이 최근",
    "머지 커밋은 제외",
)

MR_HISTORY_TOOLTIP = "MR(Merge Request)은 한 브랜치의 변경을 다른 브랜치로 합치는 요청입니다"
MR_HISTORY_TOOLTIP_NOTES = (
    "화살표는 합치는 방향입니다 (원본 브랜치 → 대상 브랜치)",
    "상태는 열림·초안(아직 작업 중)·병합됨·닫힘(합치지 않고 종료) 중 하나입니다",
    "MR 뒤의 !번호는 저장소가 매긴 MR 번호입니다 — 누르면 원문으로 이동합니다",
    "날짜는 그 상태가 된 날입니다 (병합·닫힘·갱신)",
)

# MR 상태별 (라벨, 배지 클래스).
# 이모지(✅·❌·🔵)를 쓰지 않는 이유: 대상 브랜치 바로 앞에 붙어 브랜치의 성패처럼
# 읽혔고, ❌(닫힘 = 합치지 않고 종료)를 실패로 오해하게 했다.
MR_STATE_LABELS: dict[MRState, tuple[str, str]] = {
    "open": ("열림", "b-prog"),
    "merged": ("병합됨", "b-done"),
    "closed": ("닫힘", "b-todo"),
}
# 초안은 열림이지만 아직 리뷰 대상이 아니다 — 같은 "열림"으로 뭉치면 진행을 잘못 읽는다
MR_DRAFT_LABEL = ("초안", "b-todo")
MR_UNKNOWN_STATE_LABEL = ("기타", "b-todo")

_MAX_MR_HISTORY_ITEMS = 5  # 이력에 보여줄 최근 MR 수

BEHIND_TOOLTIP = "기준 브랜치에는 있지만 이 브랜치에 아직 없는 커밋 수입니다"
BEHIND_TOOLTIP_NOTES = (
    "병합 전에 최신화(merge·rebase)가 얼마나 필요한지 나타냅니다",
    "0이면 기준 브랜치의 모든 커밋을 이미 반영한 상태입니다",
)

# 경고 종류별 면 강조 — 모든 경고를 빨갛게 칠하면 색이 신호 구실을 못 한다.
# 여기 없는 종류는 강조 없이(흰 행) 나온다: 새 종류가 조용히 빨개지는 것보다,
# 조용히 평범해지는 편이 오해가 적다.
WARNING_SEVERITY_CLASSES: dict[WarningKind, str] = {
    "collection_failure": "warning-item--severe",  # 데이터 자체가 비었다는 뜻
    "revert_commit": "warning-item--notable",  # 되돌림의 흔적
    "hotfix_commit": "warning-item--notable",  # 긴급 대응의 흔적
}

WARNING_KIND_LABELS: dict[WarningKind, str] = {
    "stale_mr": "정체된 MR",
    "stale_branch": "방치된 브랜치",
    "revert_commit": "Revert 커밋",
    "hotfix_commit": "Hotfix 커밋",
    "collection_failure": "수집 실패",
}


def _format_window_text(window_start: datetime | None, window_end: datetime | None) -> str:
    """조회 기간을 포맷한다 (tooltip 텍스트용).

    포맷 규칙:
    - window_start/end가 None이면 빈 문자열 반환
    - 양끝이 모두 00:00:00이면:
      - 시작과 종료-1일이 같은 날짜면: "2026-07-22 (수)" (단일 날짜)
      - 아니면: "2026-07-24 (금) ~ 2026-07-26 (일)" (범위)
    - 그 외(시각이 있으면): "2026-07-22 (수) 15:30 ~ 2026-07-23 (목) 15:30"

    Args:
        window_start: 조회 기간 시작
        window_end: 조회 기간 끝

    Returns:
        포맷된 기간 텍스트 (또는 빈 문자열)
    """
    if window_start is None or window_end is None:
        return ""

    # 양끝이 모두 00:00:00인지 확인
    is_midnight_start = (
        window_start.hour == 0 and window_start.minute == 0 and window_start.second == 0
    )
    is_midnight_end = window_end.hour == 0 and window_end.minute == 0 and window_end.second == 0

    def format_date_with_weekday(dt: datetime) -> str:
        """날짜와 요일을 포맷한다. 예: "2026-07-22 (수)"."""
        weekday_idx = dt.weekday()  # 월=0, 일=6
        weekday_korean = _WEEKDAY_KOREAN[weekday_idx]
        return f"{dt.strftime('%Y-%m-%d')} ({weekday_korean})"

    def format_datetime_with_time(dt: datetime) -> str:
        """날짜, 시각, 요일을 포맷한다. 예: "2026-07-22 (수) 15:30"."""
        weekday_idx = dt.weekday()
        weekday_korean = _WEEKDAY_KOREAN[weekday_idx]
        return f"{dt.strftime('%Y-%m-%d')} ({weekday_korean}) {dt.strftime('%H:%M')}"

    if is_midnight_start and is_midnight_end:
        # 양끝 00:00: 창 길이 기반으로 분기
        display_end = window_end - timedelta(days=1)
        if display_end.date() == window_start.date():
            # 단일 날짜 (예: 24h 일간)
            return format_date_with_weekday(window_start)
        else:
            # 범위 (예: 72h 일간 또는 168h 주간)
            return (
                f"{format_date_with_weekday(window_start)} ~ "
                f"{format_date_with_weekday(display_end)}"
            )
    else:
        # 시각 포함: 양끝 모두 시각 표시
        return (
            f"{format_datetime_with_time(window_start)} ~ {format_datetime_with_time(window_end)}"
        )


def render_kpi_strip(
    groups: tuple[FeatureGroup, ...],
    warnings: tuple[WarningSignal, ...],
    repo_full_path: str,
) -> str:
    """레포 탭용 KPI 스트립을 렌더한다 (repo 필터 적용).

    활동이 전혀 없어도 항상 렌더한다 — 값이 0이라는 것도 읽을 정보이고, 레포마다
    스트립이 있다 없다 하면 탭을 옮길 때 아래 내용이 위아래로 튀어 자리를 잃는다.
    "0"의 의미는 같은 탭의 빈 상태 문구가 이어서 설명한다.

    주의 신호 강조(kpi-warn)는 실제로 경고가 있을 때만 준다: 0을 빨갛게 칠하면
    아무 문제 없는 레포가 문제 있는 것처럼 읽힌다.

    Args:
        groups: 모든 기능 그룹들
        warnings: 모든 주의신호들
        repo_full_path: 필터링할 레포 경로

    Returns:
        KPI 스트립 HTML
    """
    repo_groups = tuple(g for g in groups if g.repo_full_path == repo_full_path)

    features = len(tuple(g for g in repo_groups if g.group_kind == "feature"))
    total_commits = sum(len(g.commits) for g in repo_groups)
    total_mrs = sum(len(g.merge_requests) for g in repo_groups)
    warning_count = len(tuple(w for w in warnings if w.repo_full_path == repo_full_path))

    warn_class = "kpi kpi-warn" if warning_count else "kpi"

    return f"""<div class="kpi-row">
  <div class="kpi"><div class="l">프로젝트/기능</div><div class="n">{features}</div></div>
  <div class="kpi"><div class="l">커밋</div><div class="n">{total_commits}</div></div>
  <div class="kpi"><div class="l">MR</div><div class="n">{total_mrs}</div></div>
  <div class="{warn_class}"><div class="l">주의 신호</div><div class="n">{warning_count}</div></div>
</div>"""


def _render_ai_line_item(escaped_line: str) -> str:
    """escape된 AI 텍스트 한 줄을 li로 렌더한다 (강조 마커·주의 접두 반영).

    Args:
        escaped_line: escape_html을 거친 한 줄 텍스트

    Returns:
        li HTML (⚠ 접두 줄이면 attention 클래스)
    """
    css_class = ' class="attention"' if is_attention_line(escaped_line) else ""
    return f"<li{css_class}>{apply_emphasis(escaped_line)}</li>"


def _render_ai_summary_block(text: str) -> str:
    """AI 문단 텍스트를 escape한 뒤 ul(2줄 이상) 또는 p(1줄)로 렌더한다.

    Args:
        text: escape 전 문단 텍스트 (줄바꿈 = 불릿 경계)

    Returns:
        ul 또는 p HTML (강조 마커·주의 접두 반영)
    """
    safe = escape_html(text)
    lines = safe.split("\n")
    # 빈 줄 제거
    lines = [line.strip() for line in lines if line.strip()]

    if len(lines) > 1:
        # 다중 줄: 불릿 리스트 (스타일은 styles.py의 .ai-summary ul/li 클래스)
        items = "\n".join(f"      {_render_ai_line_item(line)}" for line in lines)
        return f"<ul>\n{items}\n      </ul>"
    # 단일 줄 또는 줄바꿈 없음: 문단 유지
    return f'<p class="ai-summary-content">{apply_emphasis(safe)}</p>'


def _render_ai_summary_impact(impact: str) -> str:
    """개선점 문단 블록(점선 구분 div + h3 소제목 + 본문)을 렌더한다.

    Args:
        impact: escape 전 개선점 문단 텍스트

    Returns:
        흐름 문단 뒤에 이어 붙일 div HTML (앞에 줄바꿈 포함)
    """
    content = _render_ai_summary_block(impact)
    return (
        '\n  <div class="ai-summary-impact">\n'
        f'    <h3 class="ai-summary-impact-label">{IMPACT_PARAGRAPH_LABEL}</h3>\n'
        f"    {content}\n"
        "  </div>"
    )


def render_ai_summary(summary: str | None, period: str = "daily") -> str:
    """AI 요약 섹션을 렌더링한다 (graceful degradation).

    요약이 비거나 None이면 빈 문자열을 반환해 슬롯을 제거한다.
    줄바꿈(\n)이 있으면 불릿 리스트로 렌더링하고, 없으면 단일 문단 유지.
    내용 줄 사이에 빈 줄이 있으면 첫 빈 줄 뒤를 개선점 문단으로 보고 소제목과 함께
    흐름 문단 아래에 덧붙인다 (빈 줄이 없으면 종전과 같은 출력).
    요약 텍스트는 XSS 공격 방지를 위해 escape_html로 처리되며,
    escape 이후 강조 마커(**…**)와 주의 접두(⚠)가 스타일로 변환된다.

    Args:
        summary: 요약 텍스트 (None 또는 빈 문자열이면 제거)
        period: "daily" (기본) 또는 "weekly" — 제목 동적화

    Returns:
        요약 섹션 HTML 또는 빈 문자열
    """
    if not summary or not summary.strip():
        return ""

    paragraphs = split_brief_paragraphs(summary)
    content = _render_ai_summary_block(paragraphs.flow)
    impact_html = _render_ai_summary_impact(paragraphs.impact) if paragraphs.impact else ""

    # 제목 분기 (period에 따라)
    title = "주간 브리핑" if period == "weekly" else "일간 브리핑"

    return f'<section class="ai-summary">\n  <h2>{title}</h2>\n  {content}{impact_html}\n</section>'


def render_header(
    team_name: str,
    report_date: str,
    lookback_hours: int,
    summary_line: str | None = None,
    period: str = "daily",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> str:
    """헤더: "Daily/Weekly Pulse · 날짜 · N시간/7일 기준 · 전환 링크".

    period에 따라 헤더 텍스트와 링크가 다르다.
    팀명은 <title> 태그에만 사용되고, 헤더는 "Daily/Weekly Pulse"로 표시된다.
    전체 summary_line은 제거되고 레포별 요약이 각 탭 헤더에 표시된다.
    DashboardModel.summary_line은 CLI 출력용으로만 사용된다.

    period별로 상대 뷰로의 링크를 포함한다 (href는 파일별 치환을 위한 플레이스홀더 포함).

    window_start/end가 제공되면 조회 기간을 커스텀 tooltip으로 period_text 위에 표시한다.

    Args:
        team_name: 팀명 (HTML에서 미사용, <title>용)
        report_date: 리포트 날짜 (ISO 형식)
        lookback_hours: 조회 범위(시간)
        summary_line: 한 줄 요약 (선택사항, HTML에서 미사용)
        period: 기간 ("daily" 또는 "weekly", 기본 "daily")
        window_start: 조회 기간 시작 (선택)
        window_end: 조회 기간 끝 (선택)

    Returns:
        HTML 문자열
    """
    safe_date = escape_html(report_date)

    if period == "weekly":
        title_text = "Weekly Pulse"
        period_text = "7일 기준"
        switch_text = "← 일간 보기"
    else:
        title_text = "Daily Pulse"
        period_text = f"{lookback_hours}시간 기준"
        switch_text = "주간 보기 →"

    # 조회 기간 tooltip 텍스트 생성 (graceful degradation: 빈 문자열이면 tooltip 제거)
    window_tooltip = _format_window_text(window_start, window_end)
    if window_tooltip:
        # page-meta는 페이지 최상단이므로 말풍선을 아래로 열고 왼쪽 끝에 맞춘다
        # (--below·--align-start: 위로 열면 잘리고, 가운데 정렬이면 좌측이 뷰포트를 벗어난다)
        bubble = render_tooltip_bubble(
            "이 대시보드가 집계한 조회 기간", (window_tooltip,), align_start=True
        ).replace('class="tooltip-bubble', 'class="tooltip-bubble tooltip-bubble--below', 1)
        period_text_html = f'<span class="tooltip-host">{period_text}{bubble}</span>'
    else:
        # window_tooltip이 없으면 순수 period_text만
        period_text_html = period_text

    return f"""<header class="page-header">
  <h1>{title_text}</h1>
  <div class="page-meta">
    {safe_date} · {period_text_html}
    <span> · <a href="__PULSE_SWITCH_HREF__" class="period-switch">{switch_text}</a></span>
  </div>
</header>"""


def render_tooltip_bubble(
    lead: str,
    items: tuple[str, ...] = (),
    *,
    align_start: bool = False,
) -> str:
    """커스텀 툴팁 말풍선을 만든다 (마크업의 단일 진실원).

    설명이 길거나 여러 항목을 나열하는 성격이면 한 줄로 이어붙이지 않고 불릿으로 나눈다.
    모든 텍스트는 escape 처리하므로 호출자가 별도로 escape하지 않는다.

    Args:
        lead: 첫 줄 설명
        items: 불릿으로 나열할 항목들 (없으면 목록을 렌더하지 않음)
        align_start: 말풍선을 트리거의 왼쪽 끝에 맞출지 (뷰포트 좌측 잘림 방지)

    Returns:
        말풍선 HTML
    """
    classes = "tooltip-bubble"
    if align_start:
        classes += " tooltip-bubble--align-start"

    parts = []
    if lead:
        parts.append(f'<span class="tooltip-lead">{escape_html(lead)}</span>')
    if items:
        bullets = "".join(f"<li>{escape_html(item)}</li>" for item in items)
        parts.append(f"<ul>{bullets}</ul>")

    return f'<span class="{classes}" role="tooltip">{"".join(parts)}</span>'


def _safe_slot_marker(group_name: str) -> str:
    """그룹명을 HTML 주석 안전한 형태로 변환한다.

    HTML 주석 조기 종료(-->)와 특수 문자(<, >)를 제거하여
    slot 마커에 안전하게 사용할 수 있도록 한다.

    Args:
        group_name: 그룹명

    Returns:
        주석 안전한 문자열
    """
    safe = group_name.replace("-->", "").replace("<", "").replace(">", "")
    return safe


def group_ai_title_slot(repo_full_path: str, group_name: str) -> str:
    """그룹별 AI 제목 slot 마커를 생성한다 (마커 포맷의 단일 진실원).

    Args:
        repo_full_path: 레포 full_path (예: "org/repo")
        group_name: 그룹명

    Returns:
        HTML 주석 마커
    """
    safe_name = _safe_slot_marker(group_name)
    return f"<!--PULSE_GROUP_AI_TITLE_SLOT:{repo_full_path}::{safe_name}-->"


def group_analysis_slot(repo_full_path: str, group_name: str) -> str:
    """그룹별 분석 slot 마커를 생성한다 (마커 포맷의 단일 진실원).

    Args:
        repo_full_path: 레포 full_path (예: "org/repo")
        group_name: 그룹명

    Returns:
        HTML 주석 마커
    """
    safe_name = _safe_slot_marker(group_name)
    return f"<!--PULSE_GROUP_ANALYSIS_SLOT:{repo_full_path}::{safe_name}-->"


def _is_unclassified(group: FeatureGroup) -> bool:
    """그룹이 unclassified 규칙으로 분류되었는지 판별한다.

    Args:
        group: 기능 그룹

    Returns:
        unclassified 여부
    """
    return group.source_rule == "unclassified"


def _render_stage_badge(stage: FeatureStage) -> str:
    """진행 단계를 상태 배지로 렌더한다 (스테퍼 대체).

    other(판정 불가)는 빈 문자열을 반환한다 — "—" 배지를 달면 활동이 가장 많은
    그룹조차 빈 상태처럼 읽힌다. 이때 요약 행의 칸이 하나 비지만, 각 칸이
    grid-column으로 고정돼 있어 뒤 칸들이 당겨오지 않는다.

    래퍼에 stage-badge-wrap을 붙이는 이유: 스파크라인 래퍼도 tooltip-host를
    공유하므로, 열 고정 규칙이 둘을 구별할 수 있어야 한다.

    Args:
        stage: 진행 단계

    Returns:
        배지 HTML 또는 빈 문자열 (other는 배지 렌더하지 않음)
    """
    labels: dict[FeatureStage, tuple[str, str]] = {
        "developing": ("진행 중", "b-prog"),
        "reviewing": ("리뷰 중", "b-qa"),
        "merged": ("머지됨", "b-done"),
        "other": ("", ""),
    }
    text, css_class = labels.get(stage, ("", ""))

    if not text:
        return ""

    # 판정 기준 툴팁 포함
    tooltip = render_tooltip_bubble(STAGE_STEPPER_TOOLTIP, STAGE_STEPPER_TOOLTIP_RULES)

    return (
        f'<span class="tooltip-host stage-badge-wrap">'
        f'<span class="badge {css_class}">{text}</span>{tooltip}</span>'
    )


_MAX_TAG_ITEMS = 5  # 작업 성격 칩에 넣을 태그 수
_MAX_TIMELINE_WEEKS = 12  # 주별 막대로 보여줄 최근 구간
_MIN_BAR_PERCENT = 8  # 커밋이 있는 주는 최소 높이를 줘서 0과 구별한다
_SILENT_GAP_MIN_DAYS = 3  # 이보다 짧은 공백은 표시하지 않는다 (주말 등)


def _format_month_day(target: date | datetime, *, with_weekday: bool = True) -> str:
    """날짜를 "MM-DD" 또는 "MM-DD (요일)"로 표기한다."""
    text = f"{target.month:02d}-{target.day:02d}"
    if with_weekday:
        return f"{text} ({_WEEKDAY_KOREAN[target.weekday()]})"
    return text


def _format_first_seen(first_seen: str, *, with_weekday: bool = False) -> str:
    """등록부의 ISO 날짜를 "MM-DD" 또는 "MM-DD (요일)"로 표기한다."""
    try:
        parsed = datetime.strptime(first_seen, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return first_seen or "—"
    return _format_month_day(parsed, with_weekday=with_weekday)


def _format_tag_counts(tags: BranchTagDistribution) -> str:
    """태그 구성을 커밋 규약 표기 그대로 나열한다 (건수 내림차순, 상위 항목만).

    한국어로 번역하지 않는다 — 개발자가 커밋에 실제로 쓰는 낱말(feat·fix·chore)이
    그대로 보이는 편이 대조하기 쉽다.
    """
    labeled = [f"{tag} {count}" for tag, count in tags.counts[:_MAX_TAG_ITEMS] if count > 0]
    return " · ".join(labeled)


def _render_history_weeks(week_counts: tuple[tuple[str, int], ...]) -> str:
    """주별 커밋 추이를 막대로 렌더한다 (최근 구간만).

    막대 높이는 구간 내 최댓값 대비 비율이다 — 절대 수치는 툴팁으로 준다.
    """
    recent = week_counts[-_MAX_TIMELINE_WEEKS:]
    if not recent:
        return ""

    peak = max(count for _, count in recent) or 1
    bars = []
    for week_start, count in recent:
        ratio = max(round(count / peak * 100), _MIN_BAR_PERCENT) if count else 0
        # 슬롯이 툴팁 트리거를 겸한다 — 막대 자체를 트리거로 쓰면 커밋이 적은 주는
        # 높이가 거의 0이어서 가리킬 영역이 없다
        tooltip = render_tooltip_bubble(
            f"{_format_first_seen(week_start)} 주",
            (f"커밋 {count}건", f"구간 최다({peak}건) 대비 {round(count / peak * 100)}%"),
        )
        bars.append(
            '<span class="history-week tooltip-host">'
            f'<span class="history-week-bar" style="--bar:{ratio}%"></span>'
            f"{tooltip}"
            "</span>"
        )

    # 캡션과 기간 축 — 요약 행의 스파크라인(최근 7일 일별)과 역할을 구분한다
    span_text = f"{_format_first_seen(recent[0][0])} ~ {_format_first_seen(recent[-1][0])}"
    return (
        '<div class="history-chart">'
        f'<div class="history-chart-head"><em>주별 추이</em>'
        f'<span class="history-span">{escape_html(span_text)}</span>'
        f'<span class="history-peak">최다 {peak}건</span></div>'
        f'<div class="history-weeks" role="img" aria-label="주별 커밋 추이">{"".join(bars)}</div>'
        "</div>"
    )


def _history_fact_items(history: BranchHistoryView) -> list[str]:
    """타임라인 하단에 놓을 사실 칩들을 만든다."""
    facts = []

    if history.behind_count is not None:
        base = escape_html(history.base_branch)
        gap = (
            f"{base} 최신 상태 반영됨"
            if history.behind_count == 0
            else f"{base}의 {history.behind_count}커밋 미반영"
        )
        tooltip = render_tooltip_bubble(BEHIND_TOOLTIP, BEHIND_TOOLTIP_NOTES)
        facts.append(
            f'<span class="history-fact tooltip-host"><em>최신화</em> {gap}{tooltip}</span>'
        )

    if history.tags:
        composition = _format_tag_counts(history.tags)
        if composition:
            facts.append(
                f'<span class="history-fact"><em>작업 성격</em> {escape_html(composition)}</span>'
            )

    if history.fix_surge:
        facts.append('<span class="history-fact history-fact-alert">수정·검증 작업 집중</span>')

    if history.silent_gap_days >= _SILENT_GAP_MIN_DAYS:
        facts.append(
            f'<span class="history-fact"><em>공백</em> 최장 {history.silent_gap_days}일</span>'
        )

    if history.truncated:
        # 총 커밋 수는 정확하지만 추이·성격 집계는 상한까지만 반영됐다는 사실을 알린다
        facts.append('<span class="history-fact">추이·성격은 최근 구간만 집계</span>')

    return facts


def _render_history_timeline(history: BranchHistoryView | None) -> str:
    """브랜치 생애 타임라인을 렌더한다 (graceful degradation).

    분기점부터 지금까지를 하나의 서사로 보여준다 — 시작일·경과일·주별 추이·기준선 격차.
    history가 None이면 빈 문자열을 반환한다: 브랜치가 기본 하나뿐인 레포나 미수집
    상태에서 빈 컨테이너조차 남기지 않는다.

    Args:
        history: 브랜치 생애 뷰

    Returns:
        타임라인 HTML 또는 빈 문자열
    """
    # 커밋이 0건이면 서사가 없다 — base에 이미 병합된 브랜치 등
    if history is None or history.total_commits == 0:
        return ""

    started_display = _format_first_seen(history.started_on, with_weekday=True)
    commit_text = f"커밋 {history.total_commits}건"
    facts_html = "".join(_history_fact_items(history))
    facts_block = f'\n  <div class="history-facts">{facts_html}</div>' if facts_html else ""

    return f"""<div class="history-timeline">
  <div class="history-timeline-head">
    <span class="history-start">{escape_html(started_display)} 시작 ·
      {history.total_days}일차</span>
    <span class="history-scale">{commit_text} · 활동 {history.active_days}일</span>
  </div>
  {_render_history_weeks(history.week_commit_counts)}{facts_block}
</div>"""


def _render_mr_state_badge(mr: MergeRequestInfo) -> str:
    """MR 상태를 한국어 배지로 렌더한다 (진행 단계 배지와 같은 어휘·모양)."""
    if mr.state == "open" and mr.is_draft:
        text, css_class = MR_DRAFT_LABEL
    else:
        text, css_class = MR_STATE_LABELS.get(mr.state, MR_UNKNOWN_STATE_LABEL)
    return f'<span class="badge {css_class}">{escape_html(text)}</span>'


def _format_mr_event(mr: MergeRequestInfo) -> str:
    """MR의 마지막 사건을 "MM-DD (요일) 병합"처럼 표기한다.

    날짜만 두면 무슨 날짜인지 알 수 없다 — 생성·갱신·병합 중 무엇인지 함께 말한다.

    Args:
        mr: MR 정보

    Returns:
        사건 텍스트
    """
    if mr.state == "merged":
        # 구버전 GitLab은 merged_at을 주지 않는다 — collector가 updated_at으로 근사한다
        return f"{_format_month_day(mr.merged_at or mr.updated_at)} 병합"
    if mr.state == "closed":
        return f"{_format_month_day(mr.updated_at)} 닫힘"
    return f"{_format_month_day(mr.updated_at)} 갱신"


def _render_mr_number(mr: MergeRequestInfo) -> str:
    """MR 번호를 "MR !3015"로 표기하고, 가능하면 원문으로 링크한다.

    번호만 두면(`!3015`) 무슨 값인지 알 수 없다 — 접두사로 정체를 밝히고,
    링크로 확인 경로를 준다. URL이 없거나 허용 스킴이 아니면 텍스트로만 남긴다.

    Args:
        mr: MR 정보

    Returns:
        번호 HTML
    """
    label = escape_html(f"MR !{mr.iid}")
    safe_url = escape_url(mr.web_url)
    if not safe_url:
        return f'<span class="mr-number">{label}</span>'
    return (
        f'<span class="mr-number">'
        f'<a href="{safe_url}" target="_blank" rel="noopener">{label}</a></span>'
    )


def _render_mr_history_item(mr: MergeRequestInfo) -> str:
    """MR 한 건을 두 줄로 렌더한다 — 윗줄 상태·제목, 아랫줄 방향·날짜·번호.

    author는 넣지 않는다 (개인 노출 금지).

    Args:
        mr: MR 정보

    Returns:
        항목 HTML
    """
    flow_html = (
        f'<span class="mr-flow">{escape_html(mr.source_branch)}'
        f'<span class="mr-arrow"> → </span>{escape_html(mr.target_branch)}</span>'
    )
    return (
        f'<div class="mr-history-item">'
        f"{_render_mr_state_badge(mr)}"
        f'<span class="mr-history-title">{escape_html(mr.title)}</span>'
        f'<span class="mr-history-meta">{flow_html}'
        f'<span class="mr-when">{escape_html(_format_mr_event(mr))}</span>'
        f"{_render_mr_number(mr)}</span>"
        f"</div>"
    )


def _render_mr_mini_history(group: FeatureGroup) -> str:
    """MR 미니 이력을 렌더한다 (최신순 최근 5건).

    이전 표기(`!3015 · Devqa · ✅ sqa · 07-28`)는 네 값이 모두 무표지여서
    읽는 사람이 뜻을 물어야 했다: 이모지가 상태인지, `!3015`가 무슨 번호인지,
    뒤 낱말이 브랜치인지, 날짜가 어떤 사건인지. 그래서 값마다 이름을 붙였다 —
    상태는 한국어 배지, 번호는 "MR !번호" 링크, 브랜치는 원본 → 대상 방향,
    날짜는 사건(병합·닫힘·갱신)과 함께.

    Args:
        group: 기능 그룹

    Returns:
        MR 이력 HTML 또는 빈 문자열
    """
    if not group.merge_requests:
        return ""

    sorted_mrs = sorted(group.merge_requests, key=lambda mr: mr.updated_at, reverse=True)
    shown_mrs = sorted_mrs[:_MAX_MR_HISTORY_ITEMS]

    # 잘렸을 때만 전체 건수를 말한다 — 안 잘렸는데 "5건 / 전체 5건"은 같은 수를 두 번 말한다
    if len(sorted_mrs) > len(shown_mrs):
        count_text = f"최근 {len(shown_mrs)}건 · 전체 {len(sorted_mrs)}건"
    else:
        count_text = f"{len(shown_mrs)}건"

    tooltip = render_tooltip_bubble(MR_HISTORY_TOOLTIP, MR_HISTORY_TOOLTIP_NOTES, align_start=True)
    items_content = "\n  ".join(_render_mr_history_item(mr) for mr in shown_mrs)

    return f"""<div class="mr-mini-history">
  <div class="mr-history-head">
    <span class="tooltip-host mr-history-label">🔀 <strong>MR 이력</strong>{tooltip}</span>
    <span class="mr-history-count">{escape_html(count_text)}</span>
  </div>
  {items_content}
</div>"""


def _render_sparkline_svg(daily_commit_counts: tuple[tuple[str, int], ...]) -> str:
    """7일 커밋 히스토그램을 인라인 SVG 스파크라인으로 렌더한다.

    빈 입력이면 자리 유지용 빈 슬롯을 반환한다.

    Args:
        daily_commit_counts: (ISO date, count) 튜플 목록

    Returns:
        인라인 SVG 또는 빈 슬롯 마크업
    """
    if not daily_commit_counts:
        return '<span class="sparkline-wrap sparkline-empty"></span>'

    counts = [count for _, count in daily_commit_counts]
    max_count = max(counts) if counts else 1
    if max_count == 0:
        max_count = 1

    # SVG 파라미터
    svg_width = 80
    svg_height = 20
    bar_width = svg_width / len(counts)
    y_scale = svg_height / max_count

    bars = ""
    for i, count in enumerate(counts):
        x = i * bar_width
        bar_height = count * y_scale
        y = svg_height - bar_height
        bars += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.9:.1f}" '
            f'height="{bar_height:.1f}" fill="#4b5563" />'
        )

    return (
        '<span class="tooltip-host sparkline-wrap">'
        f'<svg class="sparkline" width="{svg_width}" height="{svg_height}" '
        f'viewBox="0 0 {svg_width} {svg_height}" aria-hidden="true">'
        f"{bars}</svg>"
        f"{render_tooltip_bubble(SPARKLINE_TOOLTIP, SPARKLINE_TOOLTIP_NOTES)}"
        "</span>"
    )


def _format_relative_time(target: datetime | None, now: datetime | None) -> str:
    """두 datetime 사이의 상대 시간을 한국어로 포맷한다.

    둘 중 하나라도 None이면 빈 문자열을 반환한다.

    Args:
        target: 기준 시각
        now: 현재 시각

    Returns:
        "방금 전", "N분 전", "N시간 전", "어제", "N일 전" 등
    """
    if target is None or now is None:
        return ""

    delta = now - target
    if delta.total_seconds() < 0:
        return ""

    # 방금 전 (1분 이내)
    if delta.total_seconds() < 60:
        return "방금 전"

    # N분 전 (1시간 이내)
    minutes = delta.total_seconds() / 60
    if minutes < 60:
        return f"{int(minutes)}분 전"

    # N시간 전 (24시간 이내)
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}시간 전"

    # 어제 (24~48시간)
    days = hours / 24
    if days < 2:
        return "어제"

    # N일 전
    if days < 365:
        return f"{int(days)}일 전"

    return f"{int(days / 365)}년 전"


def _hidden_commit_tail(group: FeatureGroup) -> str:
    """커밋 목록에서 잘린 나머지 건수를 "외 N건"으로 만든다 (없으면 빈 문자열).

    세는 모집단은 목록과 같아야 한다 — normalize_commit_titles를 거친 제목 수다.
    그룹 헤더의 "커밋 N"(원본 커밋 수)보다 작을 수 있다: 머지 커밋과 중복 제목은
    목록에서 의도적으로 뺀 것이므로 꼬리표에도 넣지 않는다. 헤더 수를 그대로 쓰면
    꼬리표가 목록에 결코 나올 수 없는 건수를 약속하게 된다.

    실측(2026-07-27 주간): feat/tiptap은 원본 50 = 제목 50이라 3+47이 헤더와 맞고,
    test는 원본 31 → 제목 15로 절반이 빠져 3+12가 헤더와 어긋난다. 어긋나는 경우에만
    사유를 덧붙인다 — 맞는 경우엔 군더더기다.
    """
    total_titles = len(normalize_commit_titles(group.commits))
    hidden = total_titles - len(group.task_summary.commit_titles)
    if hidden <= 0:
        return ""
    if total_titles < len(group.commits):
        return f"외 {hidden}건 (머지·중복 제외)"
    return f"외 {hidden}건"


def _render_task_details(group: FeatureGroup) -> str:
    """task_summary를 상세 보기로 렌더한다.

    Args:
        group: 기능 그룹 (잘린 건수를 세려면 잘리기 전 커밋 원본도 필요하다)

    Returns:
        상세 보기 HTML 또는 빈 문자열
    """
    task_summary = group.task_summary
    if not (
        task_summary.commit_titles
        or task_summary.open_mr_titles
        or task_summary.active_branch_names
    ):
        return ""

    task_sections = []

    def build_section(icon: str, label: str, values: tuple[str, ...], tail: str = "") -> str:
        """아이콘·소제목을 한 줄로 묶고 목록을 붙인다 (아이콘 단독 줄바꿈 방지)."""
        items = "\n".join(f"              <li>{escape_html(value)}</li>" for value in values)
        if tail:
            items += f'\n              <li class="task-more">{escape_html(tail)}</li>'
        return (
            f'              <div class="task-label">{icon} <strong>{label}</strong></div>\n'
            f"              <ul>\n{items}\n              </ul>"
        )

    if task_summary.commit_titles:
        task_sections.append(
            build_section("📝", "커밋", task_summary.commit_titles, _hidden_commit_tail(group))
        )

    # MR·브랜치에는 꼬리표를 붙이지 않는다 — 상한(2/3)에 걸린 사례가 실측 0건이다
    # (발행된 리포트 44행 전수 조사: MR 최대 0건, 브랜치 최대 1건).
    # 일어나지 않는 절단을 위해 꼬리표를 미리 만들지 않는다.
    if task_summary.open_mr_titles:
        task_sections.append(build_section("🔀", "MR", task_summary.open_mr_titles))

    if task_summary.active_branch_names:
        task_sections.append(build_section("🌿", "브랜치", task_summary.active_branch_names))

    task_content = "\n            </div>\n            <div>".join(task_sections)
    return f"""<div class="task-summary">
              <div>
              {task_content}
              </div>
            </div>"""


def _get_latest_non_merge_commit(group: FeatureGroup) -> str | None:
    """그룹의 커밋 중 가장 최근의 비머지 커밋 제목을 반환한다.

    Args:
        group: 기능 그룹

    Returns:
        커밋 제목 또는 None
    """
    # grouper와 동일한 머지 커밋 판정·최신순 정렬을 재사용 (기준 이원화 방지)
    titles = normalize_commit_titles(group.commits)
    return titles[0] if titles else None


def _render_feature_row(
    group: FeatureGroup,
    issue_url_template: str | None = None,
    generated_at: datetime | None = None,
    *,
    show_history: bool = False,
) -> str:
    """기능 그룹을 확장형 리스트 행으로 렌더한다.

    Args:
        group: 기능 그룹
        issue_url_template: 이슈 URL 템플릿 (예: "https://jira.example.com/browse/{key}")
        generated_at: 대시보드 생성 시각 (상대시간 계산용)
        show_history: 생애 타임라인 표시 여부 (누적 서사가 의미 있는 주간 뷰에서만 True)

    Returns:
        행 HTML
    """
    safe_name = escape_html(group.name)
    unclassified = _is_unclassified(group)

    # Summary 행: 제목 + 배지 + 스파크라인 + 규모 + 상대시간
    ai_title_slot = group_ai_title_slot(group.repo_full_path, group.name)
    badge_html = _render_stage_badge(group.stage)
    sparkline_html = _render_sparkline_svg(group.daily_commit_counts)

    # 규모: "커밋 N · 파일 M"
    commit_count = len(group.commits)
    # 파일 수: 그룹 커밋의 changed_files 합집합 크기
    all_files: set[str] = set()
    for commit in group.commits:
        all_files.update(commit.changed_files)
    file_count = len(all_files)
    scale_text = f"커밋 {commit_count} · 파일 {file_count}"

    # 상대시간: last_activity_at와 generated_at 기준
    relative_time = _format_relative_time(group.last_activity_at, generated_at)

    summary_content = f"""        <div class="feature-summary">
          {ai_title_slot}
          <div class="group-name">{safe_name}</div>
          {badge_html}
          {sparkline_html}
          <div class="feature-meta">
            <span class="scale">{scale_text}</span>
            {f'<span class="relative-time">{relative_time}</span>' if relative_time else ""}
          </div>
        </div>"""

    # 확장 내용: AI 분석 슬롯 + task_summary + issue_keys + participants
    ai_analysis_slot = group_analysis_slot(group.repo_full_path, group.name)

    # issue_keys 렌더링
    issue_keys_html = ""
    if group.issue_keys:
        key_items = []
        for key in group.issue_keys:
            safe_key = escape_html(key)
            if issue_url_template:
                # 단순 치환 사용 — str.format은 템플릿의 다른 중괄호에서 KeyError로 렌더를 중단시킴
                url = issue_url_template.replace("{key}", key)
                safe_url = escape_url(url)
                key_items.append(
                    f'<a href="{safe_url}" target="_blank" rel="noopener">{safe_key}</a>'
                )
            else:
                key_items.append(safe_key)
        issue_keys_html = f"""            <div class="issue-keys">
              <strong>이슈:</strong> {" ".join(key_items)}
            </div>"""

    # task_summary 렌더링
    task_details_html = _render_task_details(group)

    # MR 미니 이력 렌더링
    mr_history_html = _render_mr_mini_history(group)

    # 생애 타임라인 렌더링 (주간 뷰 전용 — 일간에는 같은 값이 반복돼 정보량이 없다)
    history_timeline_html = _render_history_timeline(group.branch_history) if show_history else ""

    # 참여자 렌더링
    participants_html = ""
    if group.participants:
        safe_participants = [escape_html(p) for p in sorted(group.participants)]
        participant_items = ", ".join(safe_participants)
        participants_html = f"""            <div class="feature-participants">
              <strong>참여자:</strong> {participant_items}
            </div>"""

    # unclassified 힌트
    hint_html = ""
    if unclassified:
        hint_msg = (
            "💡 이 기능은 규칙으로 분류되지 않았습니다. "
            "config.yaml의 grouping_hints에 브랜치/라벨 규칙을 추가하면 자동 분류됩니다."
        )
        hint_html = f"""
            <div class="unclassified-hint">
              {hint_msg}
            </div>"""

    expand_content = f"""{ai_analysis_slot}{hint_html}
{mr_history_html if mr_history_html else ""}
{history_timeline_html if history_timeline_html else ""}
{task_details_html if task_details_html else ""}
{issue_keys_html}
{participants_html}"""

    return f"""  <details class="feature-row">
    <summary>
{summary_content}
    </summary>
    <div class="feature-expand">
{expand_content}
    </div>
  </details>"""


def render_feature_cards(
    groups: tuple[FeatureGroup, ...],
    repo_filter: str | None = None,
    *,
    generated_at: datetime | None = None,
    issue_url_template: str | None = None,
    period: str = "daily",
) -> str:
    """2️⃣  프로젝트/기능 확장형 리스트.

    기능 그룹(group_kind=="feature")을 필터링·정렬한 뒤 <details> 확장형 리스트로 렌더링한다.
    정렬: 커밋 수 내림차순 → 동률 시 last_activity_at 최신순 → stage=="merged"는 뒤로.

    Args:
        groups: 기능 그룹들
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)
        generated_at: 대시보드 생성 시각 (상대시간 계산용)
        issue_url_template: 이슈 URL 템플릿
        period: "daily" 또는 "weekly" — 수명주기 표시는 주간 뷰에서만 (일간은 같은 값 반복)

    Returns:
        HTML 문자열 (빈 경우 빈 문자열)
    """
    # group_kind=="feature" 필터링
    feature_groups = tuple(g for g in groups if g.group_kind == "feature")

    # 레포 필터링
    filtered_groups = feature_groups
    if repo_filter is not None:
        filtered_groups = tuple(g for g in feature_groups if g.repo_full_path == repo_filter)

    if not filtered_groups:
        return ""

    # 정렬: 커밋 수 내림차순 → 동률 시 last_activity_at 최신순 → merged는 뒤로
    def sort_key(group: FeatureGroup) -> tuple[bool, int, float]:
        # 1. merged가 아니면 False(먼저), merged면 True(뒤로)
        is_merged = group.stage == "merged"
        # 2. 커밋 수 내림차순 (음수로 내림차순)
        commit_count = -len(group.commits)
        # 3. last_activity_at 최신순 (None은 맨 뒤, 매우 작은 음수 사용)
        if group.last_activity_at is None:
            last_activity_desc = float("-inf")
        else:
            last_activity_desc = -group.last_activity_at.timestamp()
        return (is_merged, commit_count, last_activity_desc)

    sorted_groups = sorted(filtered_groups, key=sort_key)

    section_description = (
        "현재 진행 중인 프로젝트/기능들을 활동량으로 우선순위를 두어 표시합니다. "
        "분류는 브랜치명, 라벨, 및 설정된 힌트 규칙을 기준으로 자동 그룹핑됩니다."
    )

    show_history = period == "weekly"
    rows_html = "\n".join(
        _render_feature_row(group, issue_url_template, generated_at, show_history=show_history)
        for group in sorted_groups
    )

    return f"""<section>
  <h2>프로젝트 현황</h2>
  <p class="section-description">{escape_html(section_description)}</p>
  <div class="feature-list">
{rows_html}
  </div>
</section>"""


STALE_PROMOTION_DAYS = 7


def _is_contiguous_chain(rungs: tuple[PromotionRung, ...]) -> bool:
    """칸들이 앞 칸의 target = 다음 칸의 source로 이어지는 단일 체인인지 판정한다."""
    return all(
        current.target == following.source
        for current, following in zip(rungs, rungs[1:], strict=False)
    )


def _promotion_node_html(label: str, rung: PromotionRung | None, now: datetime | None) -> str:
    """사다리 노드 하나를 렌더한다 (rung이 None이면 날짜 없는 시작 노드)."""
    safe_label = escape_html(label)
    if rung is None:
        return f'<span class="train-rung">{safe_label}</span>'

    last_date = rung.last_merged_at.strftime("%m-%d") if rung.last_merged_at else "—"
    wait = f' <span class="mr-wait">대기 {rung.open_count}</span>' if rung.open_count > 0 else ""
    stale_class = " train-rung--stale" if _is_stale_promotion(rung, now) else ""
    return f'<span class="train-rung{stale_class}">{safe_label} ({last_date}){wait}</span>'


def _is_stale_promotion(rung: PromotionRung, now: datetime | None) -> bool:
    """마지막 승격이 STALE_PROMOTION_DAYS 이상 지났는지 판정한다 (정체 표시용)."""
    if now is None or rung.last_merged_at is None:
        return False
    return (now - rung.last_merged_at).days >= STALE_PROMOTION_DAYS


def _render_train_nodes(rungs: tuple[PromotionRung, ...], now: datetime | None) -> list[str]:
    """체인 사다리를 노드 목록으로 렌더한다 (중간 라인 이름 중복 없음)."""
    nodes = [_promotion_node_html(rungs[0].source, None, now)]
    nodes.extend(_promotion_node_html(rung.target, rung, now) for rung in rungs)
    return nodes


def _render_train_pair(rung: PromotionRung, now: datetime | None) -> str:
    """체인이 아닐 때 쓰는 "source → target" 쌍 표기."""
    return _promotion_node_html(f"{rung.source} → {rung.target}", rung, now)


def render_release_train(train: ReleaseTrain | None, now: datetime | None) -> str:
    """릴리스 승격 사다리 패널을 렌더한다 (graceful degradation).

    train이 None이거나 rungs가 비어있으면 빈 문자열을 반환한다.
    포맷: develop ─▶ devqa (07-24) ─▶ sqa (07-24) ─▶ master (07-22)

    각 칸에는 최근 승격 날짜와 대기 건수를 표시한다.

    Args:
        train: 릴리스 사다리
        now: 현재 시각 (정체 감지용, None이면 무시)

    Returns:
        패널 HTML 또는 빈 문자열
    """
    if train is None or not train.rungs:
        return ""

    if _is_contiguous_chain(train.rungs):
        items = _render_train_nodes(train.rungs, now)
    else:
        # 사다리가 단일 체인이 아니면(분기·순환) 노드로 잇지 않고 칸을 그대로 나열한다
        items = [_render_train_pair(rung, now) for rung in train.rungs]

    connector = '<span class="train-connector"> ─▶ </span>'
    rungs_html = connector.join(items)

    return f"""<div class="release-train">
  <div class="release-train-label">릴리스 승격</div>
  <div class="release-train-visual">
    {rungs_html}
  </div>
</div>"""


def _render_line_row(
    group: FeatureGroup,
    generated_at: datetime | None = None,
) -> str:
    """릴리스/검증 라인을 확장형 리스트 행으로 렌더한다.

    MR 없이 라인에 직접 커밋·푸시하는 경우가 있어, 펼치면 기능 행과 같은 수준의
    상세(커밋·MR·브랜치·참여자)를 보여준다. 수명주기는 렌더하지 않는다 —
    라인은 상시 존재하는 통로여서 "며칠째 진행"이라는 누적 서사가 의미를 갖지 않는다.

    Args:
        group: 라인 그룹
        generated_at: 대시보드 생성 시각 (상대시간 계산용)

    Returns:
        행 HTML
    """
    safe_name = escape_html(group.name)
    ai_title_slot = group_ai_title_slot(group.repo_full_path, group.name)

    latest_commit = _get_latest_non_merge_commit(group)
    latest_commit_text = escape_html(latest_commit) if latest_commit else "—"
    relative_time = _format_relative_time(group.last_activity_at, generated_at)
    commit_count = len(group.commits)
    merge_request_count = len(group.merge_requests)

    scale_parts = [f"커밋 {commit_count}"]
    if merge_request_count:
        scale_parts.append(f"MR {merge_request_count}")

    summary_content = f"""        <div class="line-summary">
          <div class="line-head">
            {ai_title_slot}
            <div class="line-name">{safe_name}</div>
          </div>
          <div class="line-latest">{latest_commit_text}</div>
          <div class="line-meta">
            <span class="scale">{" · ".join(scale_parts)}</span>
            {f'<span class="relative-time">{relative_time}</span>' if relative_time else ""}
          </div>
        </div>"""

    expand_parts = [
        group_analysis_slot(group.repo_full_path, group.name),
        _render_mr_mini_history(group),
        _render_task_details(group),
    ]
    if group.participants:
        participant_items = ", ".join(escape_html(p) for p in sorted(group.participants))
        expand_parts.append(
            f'            <div class="feature-participants">\n'
            f"              <strong>참여자:</strong> {participant_items}\n"
            f"            </div>"
        )

    expand_content = "\n".join(part for part in expand_parts if part)

    return f"""  <details class="line-row">
    <summary>
{summary_content}
    </summary>
    <div class="feature-expand">
{expand_content}
    </div>
  </details>"""


def render_release_lines(
    groups: tuple[FeatureGroup, ...],
    repo_filter: str | None = None,
    *,
    generated_at: datetime | None = None,
) -> str:
    """릴리스/검증 라인 확장형 리스트.

    라인 그룹(group_kind=="line")을 필터링해 <details> 확장형 리스트로 렌더링한다.
    접힌 행: 라인명(AI 제목 슬롯) · 최근 반영(최신 비머지 커밋) · 규모 · 최근성.
    펼친 내용: AI 분석 슬롯 · MR 이력 · 커밋/MR/브랜치 · 참여자.
    라인 그룹이 0개면 빈 문자열을 반환한다.

    Args:
        groups: 기능 그룹들
        repo_filter: 레포 필터
        generated_at: 대시보드 생성 시각

    Returns:
        HTML 문자열 (빈 경우 빈 문자열)
    """
    line_groups = tuple(g for g in groups if g.group_kind == "line")

    filtered_groups = line_groups
    if repo_filter is not None:
        filtered_groups = tuple(g for g in line_groups if g.repo_full_path == repo_filter)

    if not filtered_groups:
        return ""

    rows_html = "\n".join(_render_line_row(group, generated_at) for group in filtered_groups)

    return f"""<section>
  <h2>릴리스/검증 라인</h2>
  <p class="section-description">
    라인에 반영된 내용입니다. 각 행을 클릭하면 커밋·MR·브랜치 상세를 볼 수 있습니다.
  </p>
  <div class="line-rows">
{rows_html}
  </div>
</section>"""


def _render_new_work_item(signal: NewWorkSignal) -> str:
    """신규 작업 항목을 렌더한다.

    Args:
        signal: 신규 작업 신호

    Returns:
        항목 HTML
    """
    safe_title = escape_html(signal.title)
    safe_repo = escape_html(signal.repo_full_path)
    safe_branch_mr = escape_html(signal.branch_or_mr)
    safe_url = escape_url(signal.web_url)

    if safe_url:
        title_element = f'<a href="{safe_url}" target="_blank">• {safe_title}</a>'
    else:
        title_element = f"• {safe_title}"

    return f"""  <div class="new-work-item">
    <div class="new-work-title">{title_element}</div>
    <div class="new-work-repo">{safe_repo} / {safe_branch_mr}</div>
  </div>"""


def render_new_work(
    signals: tuple[NewWorkSignal, ...],
    repo_filter: str | None = None,
    period: str = "daily",
    baseline_date: date | None = None,
) -> str:
    """4️⃣  새로 시작된 작업 (G4).

    Args:
        signals: 신규 작업 신호들
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)
        period: "daily" 또는 "weekly"
        baseline_date: 주간 뷰에서 신규 브랜치 비교 기준 날짜

    Returns:
        HTML 문자열 (빈 경우 빈 문자열)
    """
    # 레포 필터링
    filtered_signals = signals
    if repo_filter is not None:
        filtered_signals = tuple(
            signal for signal in signals if signal.repo_full_path == repo_filter
        )

    if not filtered_signals:
        return ""

    # G4: period와 baseline_date로 섹션 설명 분기
    if period == "weekly":
        if baseline_date is not None:
            baseline_str = baseline_date.strftime("%m-%d")
            section_description = (
                f"지난 7일 내 생성된 MR과, {baseline_str} 수집 스냅샷 이후 새로 생긴 브랜치입니다."
            )
        else:
            section_description = (
                "지난 7일 내 생성된 MR입니다. 신규 브랜치는 비교 기준 축적 중입니다."
            )
    else:
        section_description = "직전 수집 이후 새로 생긴 브랜치와, 조회 기간 내 생성된 MR입니다."

    items_html = "\n".join(_render_new_work_item(signal) for signal in filtered_signals)
    return f"""<section>
  <h2>신규 작업</h2>
  <p class="section-description">{escape_html(section_description)}</p>
{items_html}
</section>"""


def _make_warning_url_html(web_url: str | None) -> str:
    """경고의 상세 보기 링크를 생성."""
    if not web_url:
        return ""
    safe_url = escape_url(web_url)
    if not safe_url:
        return ""
    return f'<a href="{safe_url}" target="_blank">상세 보기</a>'


def _render_warning_item(signal: WarningSignal) -> str:
    """경고 항목을 렌더한다 (한 줄 조밀 배치).

    종류 라벨과 "N일 경과"는 표시하지 않는다 — 종류는 그룹 헤더가 이미 말하고,
    경과일은 설명("push 없음: N일")과 같은 수를 두 번 말한다.
    """
    severity_class = WARNING_SEVERITY_CLASSES.get(signal.kind, "")
    css_class = f"warning-item {severity_class}".strip()

    safe_title = escape_html(signal.title)
    safe_description = escape_html(signal.description)
    url_html = _make_warning_url_html(signal.web_url)

    # 링크만 오른쪽 끝으로 보낸다 — 마지막 자식을 밀면 링크 없는 행은 설명이 밀려간다
    url_html_wrapper = f'<div class="warning-link">{url_html}</div>' if url_html else ""

    return f"""  <div class="{css_class}">
    <div class="warning-description">{safe_title}</div>
    <div class="warning-detail">{safe_description}</div>
    {url_html_wrapper}
  </div>"""


def render_warnings(signals: tuple[WarningSignal, ...], repo_filter: str | None = None) -> str:
    """5️⃣  주의 신호.

    Args:
        signals: 주의 신호들
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)

    Returns:
        HTML 문자열 (빈 경우 빈 문자열)
    """
    # 레포 필터링
    filtered_signals = signals
    if repo_filter is not None:
        filtered_signals = tuple(
            s for s in signals if s.repo_full_path == repo_filter or s.repo_full_path is None
        )

    if not filtered_signals:
        return ""

    section_description = "정체된 MR, 방치된 브랜치, Revert/Hotfix 커밋, 수집 실패 등을 표시합니다."
    items_html = "\n".join(_render_warning_item(signal) for signal in filtered_signals)
    return f"""<section>
  <h2>주의 신호</h2>
  <p class="section-description">{escape_html(section_description)}</p>
{items_html}
</section>"""


def _render_participation_entry(entry: ParticipationEntry) -> str:
    """참여 항목을 렌더한다.

    Args:
        entry: 팀원 참여 정보

    Returns:
        항목 HTML
    """
    safe_name = escape_html(entry.person_name)
    safe_groups = [escape_html(g) for g in entry.group_names]
    groups_html = ", ".join(safe_groups)

    return f"""  <div class="participation-entry">
    <div class="participation-name">{safe_name}</div>
    <div class="participation-groups">{groups_html}</div>
  </div>"""


def render_participation(groups: tuple[FeatureGroup, ...], repo_filter: str | None = None) -> str:
    """6️⃣  팀 참여 맵 (수치 없음).

    groups에서 동적으로 참여자를 파생시키는 순수 함수.

    Args:
        groups: 기능 그룹들
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)

    Returns:
        HTML 문자열 (빈 경우 빈 문자열)
    """
    # 레포 필터링
    filtered_groups = groups
    if repo_filter is not None:
        filtered_groups = tuple(g for g in groups if g.repo_full_path == repo_filter)

    # 참여자 집계 (사람 → 그룹 목록)
    person_groups: dict[str, set[str]] = {}
    for group in filtered_groups:
        for person in group.participants:
            if person not in person_groups:
                person_groups[person] = set()
            person_groups[person].add(group.name)

    if not person_groups:
        return ""

    # 사람별 항목 생성 (사전순 정렬)
    entries = [
        ParticipationEntry(person_name=p, group_names=tuple(sorted(gs)))
        for p, gs in sorted(person_groups.items())
    ]

    section_description = "팀원들이 참여하는 프로젝트/기능입니다 (수치 없음, 부록 B 준수)."
    items_html = "\n".join(_render_participation_entry(entry) for entry in entries)
    return f"""<section class="participation-section">
  <h2>팀 참여</h2>
  <p class="section-description">{escape_html(section_description)}</p>
  <div class="participation-map">
{items_html}
  </div>
</section>"""


def render_diff(diff: DiffSummary | None, repo_filter: str | None = None) -> str:
    """7️⃣  전일 대비 변화 (diff 섹션).

    신규 그룹과 단계 변화를 표시한다.
    diff가 None이거나 변화가 없으면 빈 문자열 반환.

    Args:
        diff: DiffSummary 또는 None
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)

    Returns:
        HTML 문자열 (변화 없으면 빈 문자열)
    """
    if diff is None:
        return ""

    # 레포 필터링
    filtered_new_groups = diff.new_groups
    if repo_filter is not None:
        filtered_new_groups = tuple(
            (repo, name) for repo, name in diff.new_groups if repo == repo_filter
        )

    filtered_stage_changes = diff.stage_changes
    if repo_filter is not None:
        filtered_stage_changes = tuple(
            change for change in diff.stage_changes if change.repo_full_path == repo_filter
        )

    # 신규/변화가 없으면 생략
    if not filtered_new_groups and not filtered_stage_changes:
        return ""

    items = []

    # 신규 그룹 (repo, name) 튜플
    for _repo_full_path, group_name in filtered_new_groups:
        safe_name = escape_html(group_name)
        items.append(f'    <div class="diff-item">신규: <strong>{safe_name}</strong></div>')

    # 단계 변화
    for change in filtered_stage_changes:
        safe_name = escape_html(change.group_name)
        stage_from = STAGE_LABELS.get(change.previous_stage, "—")
        stage_to = STAGE_LABELS.get(change.current_stage, "—")
        items.append(f'    <div class="diff-item">{safe_name}: {stage_from} → {stage_to}</div>')

    items_html = "\n".join(items)
    compared_date = escape_html(diff.compared_to.isoformat())

    return f"""<section>
  <h2>변화 ({compared_date} 대비)</h2>
  <div class="diff-items">
{items_html}
  </div>
</section>"""


def render_group_ai_title(title: str | None) -> str:
    """AI 작성 제목을 렌더링한다 (graceful degradation).

    제목이 비거나 None이면 빈 문자열을 반환한다.

    Args:
        title: AI 제목 (None 또는 빈 문자열이면 제거)

    Returns:
        제목 섹션 HTML 또는 빈 문자열
    """
    if not title or not title.strip():
        return ""
    # 제목에는 강조 마커를 쓰지 않는 규약 — 들어와도 방어적으로 제거한다
    safe = escape_html(strip_emphasis(title))
    return f'<div class="group-ai-title"><strong>{safe}</strong></div>'


def render_group_analysis(analysis: str | None) -> str:
    """AI 분석 내용을 렌더링한다.

    줄바꿈이 있으면 불릿 리스트로, 없으면 텍스트 유지.
    escape 이후 강조 마커(**…**)와 주의 접두(⚠)가 스타일로 변환된다.

    Args:
        analysis: AI 분석 텍스트

    Returns:
        분석 섹션 HTML 또는 빈 문자열
    """
    if not analysis or not analysis.strip():
        return ""

    safe = escape_html(analysis)
    lines = [line.strip() for line in safe.split("\n") if line.strip()]

    if len(lines) > 1:
        # 스타일은 styles.py의 .group-analysis ul/li 클래스
        items = "\n".join(f"        {_render_ai_line_item(line)}" for line in lines)
        content = f"<ul>\n{items}\n        </ul>"
    else:
        content = apply_emphasis(safe)

    return f'<div class="group-analysis">{content}</div>'


def render_warnings_grouped(
    signals: tuple[WarningSignal, ...],
    repo_filter: str | None = None,
) -> str:
    """주의신호를 kind별로 그룹핑해 렌더링한다 (expand/collapse).

    Args:
        signals: 주의신호 튜플
        repo_filter: 레포 필터 (None="전체", "org/repo"=특정 레포)

    Returns:
        그룹핑된 HTML (빈 경우 빈 문자열)
    """
    # 레포 필터링
    filtered_signals = signals
    if repo_filter is not None:
        filtered_signals = tuple(
            s for s in signals if s.repo_full_path == repo_filter or s.repo_full_path is None
        )

    if not filtered_signals:
        return ""

    # kind별로 집계: {kind: [signals...]}
    signals_by_kind: dict[WarningKind, list[WarningSignal]] = {}
    for signal in filtered_signals:
        if signal.kind not in signals_by_kind:
            signals_by_kind[signal.kind] = []
        signals_by_kind[signal.kind].append(signal)

    # 요약 헤더 생성 (WARNING_KIND_LABELS 순서대로)
    summary_items = []
    for kind in WARNING_KIND_LABELS:
        if kind in signals_by_kind:
            count = len(signals_by_kind[kind])
            label = WARNING_KIND_LABELS[kind]
            badge_class = kind.replace("_", "-")
            summary_items.append(
                f'<span class="warning-badge warning-badge-{badge_class}">{label} ({count})</span>'
            )

    summary_html = ""
    if summary_items:
        summary_html = f'<div class="warning-summary">\n    {"".join(summary_items)}\n  </div>\n  '

    # 상세 (expand/collapse)
    detail_sections = []
    for kind in WARNING_KIND_LABELS:
        if kind in signals_by_kind:
            kind_signals = signals_by_kind[kind]
            count = len(kind_signals)
            label = WARNING_KIND_LABELS[kind]
            items_html = "\n".join(_render_warning_item(s) for s in kind_signals)
            details_html = f"""<details class="warning-group">
    <summary>{label} ({count})</summary>
    <div class="warning-items">
{items_html}
    </div>
  </details>"""
            detail_sections.append(details_html)

    section_description = "정체된 MR, 방치된 브랜치, Revert/Hotfix 커밋, 수집 실패 등을 표시합니다."
    details_content = "\n  ".join(detail_sections)
    return f"""<section>
  <h2>주의 신호</h2>
  <p class="section-description">{escape_html(section_description)}</p>
  {summary_html}{details_content}
</section>"""
