"""공개 진입점: group_activities (오케스트레이션)."""

from datetime import datetime, timedelta

from pulse.config.loader import Config
from pulse.grouper.group import assemble_groups
from pulse.grouper.signals import generate_new_work_signals
from pulse.grouper.stagnation import detect_stagnation_signals, detect_stale_branch
from pulse.models import FeatureGroup, NewWorkSignal, RepoActivity, WarningSignal


def filter_activities_to_window(
    activities: tuple[RepoActivity, ...],
    window_hours: int,
    now: datetime,
) -> tuple[RepoActivity, ...]:
    """활동을 시간 창으로 필터링한다 (일간/주간 뷰 분리용).

    활동의 시간 범위: [now - window_hours, now] (폐곡간, 양끝 inclusive)
    - 커밋: authored_at이 창 내
    - MR: updated_at이 창 내 (수집기의 updated_after 기준과 일치)
    - active_branches: 마지막 커밋 시각이 창 내

    created_branches, deleted_branches, stale_branches는 상한 미적용.

    Args:
        activities: 수집된 전체 활동들
        window_hours: 필터링 윈도우 (시간)
        now: 기준 시각 (조회창 상한)

    Returns:
        필터링된 RepoActivity 튜플
    """
    cutoff = now - timedelta(hours=window_hours)

    filtered = []
    for activity in activities:
        # 커밋 필터링 (하한 AND 상한)
        filtered_commits = tuple(c for c in activity.commits if cutoff <= c.authored_at <= now)

        # MR 필터링 (updated_at 기준: 수집기의 updated_after와 일치, 하한 AND 상한)
        filtered_mrs = tuple(m for m in activity.merge_requests if cutoff <= m.updated_at <= now)

        # active_branches 필터링 (마지막 커밋이 창 내, 하한 AND 상한)
        filtered_active_branches = tuple(
            b
            for b in activity.active_branches
            if b.last_pushed_at and cutoff <= b.last_pushed_at <= now
        )

        # 필터링된 데이터로 새 RepoActivity 생성
        filtered_activity = RepoActivity(
            repo=activity.repo,
            status=activity.status,
            failure_reason=activity.failure_reason,
            commits=filtered_commits,
            active_branches=filtered_active_branches,
            created_branches=activity.created_branches,  # 생성 브랜치는 전체 유지
            deleted_branches=activity.deleted_branches,
            merge_requests=filtered_mrs,
            collected_at=activity.collected_at,
            stale_branches=activity.stale_branches,  # 정체 브랜치는 전체 유지
        )
        filtered.append(filtered_activity)

    return tuple(filtered)


def _calculate_unclassified_ratio(
    activities: tuple[RepoActivity, ...],
    groups: tuple[FeatureGroup, ...],
) -> float:
    """미분류율을 계산한다 (source_rule == 'unclassified'인 항목 수 / 전체 항목 수).

    branch-name 폴백 도입 후 미분류율은 '명시적 규칙이 적용되지 않은' 항목만 카운트한다.
    branch-name은 정보(브랜치명)가 명확하므로 미분류에 포함하지 않는다.
    """
    total_items = 0
    unclassified_count = 0

    for activity in activities:
        total_items += len(activity.commits) + len(activity.merge_requests)
        # 브랜치는 유니크 이름 집합
        unique_branch_names = set(activity.created_branches) | {
            b.name for b in activity.active_branches
        }
        total_items += len(unique_branch_names)

    for group in groups:
        if group.source_rule == "unclassified":
            unclassified_count += len(group.commits) + len(group.merge_requests)
            # 그룹의 branch_names도 유니크 집합
            unclassified_count += len(set(group.branch_names))

    return unclassified_count / total_items if total_items > 0 else 0.0


def group_activities(
    activities: tuple[RepoActivity, ...],
    config: Config,
    now: datetime,
) -> tuple[tuple[FeatureGroup, ...], tuple[WarningSignal, ...], tuple[NewWorkSignal, ...], float]:
    """수집된 활동을 그룹핑하고 신호를 생성한다.

    Args:
        activities: 수집된 활동 (RepoActivity 튜플)
        config: 설정
        now: 현재 시각 (now 인자로 주입하여 순수성 보증)

    Returns:
        (groups, warnings, new_work, unclassified_ratio)
    """
    # 1. FeatureGroup 조립
    groups = assemble_groups(activities, config.grouping_hints, now)

    # 2. 정체 신호 수집
    all_warnings = []
    for group in groups:
        group_warnings = detect_stagnation_signals(group, now, config.stagnation)
        all_warnings.extend(group_warnings)

    # stale_branches 감지 (레포 스코프, 그룹에 속하지 않는 정체 브랜치)
    for activity in activities:
        for branch in activity.stale_branches:
            signal = detect_stale_branch(
                branch,
                now,
                config.stagnation.no_push_days,
                repo_full_path=activity.repo.full_path,
            )
            if signal:
                all_warnings.append(signal)

    # 3. 신규 작업 신호
    new_work_signals = generate_new_work_signals(activities, now, config.lookback_hours)

    # 4. 미분류율 계산
    unclassified_ratio = _calculate_unclassified_ratio(activities, groups)

    return (groups, tuple(all_warnings), tuple(new_work_signals), unclassified_ratio)
