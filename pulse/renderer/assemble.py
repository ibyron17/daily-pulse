"""대시보드 모델 조립 (grouper 출력 → DashboardModel). now 주입으로 순수성 보증."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Literal

from pulse.config.loader import Config
from pulse.grouper.signals import commit_histogram_by_date
from pulse.models import (
    DashboardModel,
    DiffSummary,
    FeatureGroup,
    NewWorkSignal,
    ReleaseTrain,
    RepoActivity,
    RepoRef,
    RepoSummary,
    WarningSignal,
)


def _prepare_warnings(
    warnings: tuple[WarningSignal, ...],
    activities: tuple[RepoActivity, ...],
) -> tuple[WarningSignal, ...]:
    """경고 신호를 준비한다 (기존 + 수집 실패 자동 추가).

    Args:
        warnings: 입력 경고들
        activities: 활동 (수집 실패 감지용)

    Returns:
        완전한 경고 튜플
    """
    collection_failures = _collect_failure_warnings(activities)
    return warnings + collection_failures


def _extract_repo_tabs(
    activities: tuple[RepoActivity, ...],
    config_repos: tuple[RepoRef, ...],
) -> tuple[str, ...]:
    """config.repos 선언 순서를 기준으로 레포 탭 순서를 반환.

    활동 0건 레포도 탭에 나타나야 하므로 groups가 아닌 activities
    (전체 수집 결과)에서 추출한다. config에 없는 레포는 뒤에 알파벳순.

    Args:
        activities: 수집된 활동들 (실패 레포 포함)
        config_repos: config.repos (순서 유지용)

    Returns:
        config 순서 + fallback 알파벳순의 repo full_path 튜플
    """
    # config 순서 맵 (RepoRef.full_path -> index)
    config_order: dict[str, int] = {}
    for i, repo_ref in enumerate(config_repos):
        # config_repos의 각 원소는 RepoRef 타입 (full_path 속성 있음)
        config_order[repo_ref.full_path] = i

    activity_repos = {activity.repo.full_path for activity in activities}

    # config 순서 우선, 없으면 알파벳순
    # mypy strict: int 타입만 사용 (float 금지)
    return tuple(sorted(activity_repos, key=lambda p: (config_order.get(p, len(config_repos)), p)))


def _extract_repo_display_names(activities: tuple[RepoActivity, ...]) -> dict[str, str]:
    """repo_full_path -> display_name 매핑을 반환한다.

    Args:
        activities: 수집된 활동들

    Returns:
        full_path -> display_name 매핑
    """
    mapping = {}
    for activity in activities:
        mapping[activity.repo.full_path] = activity.repo.display_name
    return mapping


def build_dashboard_model(
    groups: tuple[FeatureGroup, ...],
    warnings: tuple[WarningSignal, ...],
    new_work: tuple[NewWorkSignal, ...],
    unclassified_ratio: float,
    activities: tuple[RepoActivity, ...],
    config: Config,
    report_date: date,
    now: datetime,
    diff: DiffSummary | None = None,
    period: Literal["daily", "weekly"] = "daily",
    new_work_baseline_date: date | None = None,
    weekly_histogram_map: dict[tuple[str, str], tuple[tuple[str, int], ...]] | None = None,
    repo_release_trains: tuple[tuple[str, ReleaseTrain], ...] = (),
) -> DashboardModel:
    """대시보드 모델 조립 (now 주입으로 순수성 보증).

    Args:
        groups: 기능 그룹들
        warnings: 경고 신호들
        new_work: 신규 작업 신호들
        unclassified_ratio: 미분류율
        activities: 수집된 활동들
        config: 설정
        report_date: 리포트 날짜
        now: 현재 시각
        diff: diff 요약 (기본 None)
        period: 기간 ("daily" 또는 "weekly", 기본 "daily")
        new_work_baseline_date: 신규 작업 비교 기준 날짜 (주간 뷰 전용, 기본 None)
        weekly_histogram_map: weekly 그룹 히스토그램 맵 (daily 조인용, 기본 None)
        repo_release_trains: 레포별 릴리스 열차 튜플 (기본값 빈 튜플)

    Returns:
        DashboardModel
    """
    all_warnings = _prepare_warnings(warnings, activities)
    repos = _extract_repo_tabs(activities, config.repos)
    display_names = _extract_repo_display_names(activities)

    # 전체 요약 라인 (CLI 출력용)
    summary_line = _assemble_summary_line_for_repo(groups, all_warnings, repo_full_path=None)

    # config.repos로부터 full_path -> web_url 맵 생성
    web_url_map: dict[str, str] = {r.full_path: r.web_url for r in config.repos}

    # 레포별 요약 라인
    repo_summaries = tuple(
        RepoSummary(
            repo_full_path=repo,
            summary_line=_assemble_summary_line_for_repo(groups, all_warnings, repo_full_path=repo),
            display_name=display_names.get(repo, repo),
            web_url=web_url_map.get(repo),
        )
        for repo in repos
    )

    # 히스토그램 부착: daily 그룹은 weekly 히스토그램 맵에서 조인, weekly는 자기 커밋으로 계산
    if weekly_histogram_map is None:
        weekly_histogram_map = {}

    groups_with_histogram = []
    for group in groups:
        histogram: tuple[tuple[str, int], ...] = ()
        key = (group.repo_full_path, group.name)

        # 맵에 있으면 재사용, 없으면 계산
        if key in weekly_histogram_map:
            histogram = weekly_histogram_map[key]
        elif period == "weekly":
            # 맵에 없을 때만 자기 커밋으로 계산 (7일).
            # 주간은 창 끝(now) 날짜까지 7일 — 이름표(report_date)가 창 뒤 날짜여도
            # 막대가 창에서 벗어나지 않는다
            histogram = commit_histogram_by_date(group.commits, 7, now.date())

        # group을 daily_commit_counts로 업데이트 (frozen dataclass이므로 replace 사용)
        updated_group = replace(group, daily_commit_counts=histogram)
        groups_with_histogram.append(updated_group)

    # 조회 기간 계산
    window_start = now - timedelta(hours=config.lookback_hours)
    window_end = now

    return DashboardModel(
        team_name=config.team_name,
        report_date=report_date,
        lookback_hours=config.lookback_hours,
        summary_line=summary_line,
        groups=tuple(groups_with_histogram),
        new_work=new_work,
        warnings=all_warnings,
        unclassified_ratio=unclassified_ratio,
        diff=diff,
        repos=repos,
        repo_summaries=repo_summaries,
        period=period,
        new_work_baseline_date=new_work_baseline_date,
        generated_at=now,
        issue_url_template=config.issue_tracking.url_template,
        window_start=window_start,
        window_end=window_end,
        repo_release_trains=repo_release_trains,
    )


def _assemble_summary_line_for_repo(
    groups: tuple[FeatureGroup, ...],
    warnings: tuple[WarningSignal, ...],
    repo_full_path: str | None = None,
) -> str:
    """한 줄 요약 생성 (레포별 또는 전체).

    Args:
        groups: 그룹들
        warnings: 경고들
        repo_full_path: 필터링 대상 레포 (None이면 전체)

    Returns:
        요약 문자열
    """
    # 레포 필터링
    if repo_full_path is None:
        filtered_groups = groups
        filtered_warnings = warnings
    else:
        filtered_groups = tuple(g for g in groups if g.repo_full_path == repo_full_path)
        filtered_warnings = tuple(
            w for w in warnings if w.repo_full_path == repo_full_path or w.repo_full_path is None
        )

    merged_count = sum(1 for g in filtered_groups if g.stage == "merged")
    warning_count = len(filtered_warnings)

    parts = []
    if len(filtered_groups) > 0:
        parts.append(f"{len(filtered_groups)}개 프로젝트")
    if merged_count > 0:
        parts.append(f"MR {merged_count}건 머지")
    if warning_count > 0:
        parts.append(f"주의 {warning_count}건")

    return ", ".join(parts) or "활동 없음"


def _collect_failure_warnings(
    activities: tuple[RepoActivity, ...],
) -> tuple[WarningSignal, ...]:
    """수집 실패한 레포를 WarningSignal로 변환 (부록 B: collection_failure).

    Args:
        activities: 수집된 활동들

    Returns:
        WarningSignal 튜플
    """
    failures = []

    for activity in activities:
        if activity.status == "failed":
            failures.append(
                WarningSignal(
                    kind="collection_failure",
                    title=activity.repo.full_path,
                    description=activity.failure_reason or "알 수 없는 오류",
                    days=None,
                    web_url=activity.repo.web_url,
                    repo_full_path=activity.repo.full_path,
                )
            )

    return tuple(failures)
