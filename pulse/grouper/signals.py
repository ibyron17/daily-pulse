"""신규 작업 신호 생성 및 활동 시계열 분석."""

from datetime import date, datetime, timedelta

from pulse.grouper.group import _is_merge_commit
from pulse.models import CommitInfo, NewWorkSignal, RepoActivity


def _create_new_work_from_branches(
    activities: tuple[RepoActivity, ...],
) -> list[NewWorkSignal]:
    """created_branches로부터 신규 작업 신호를 생성한다."""
    signals = []

    for activity in activities:
        for branch_name in activity.created_branches:
            # web_url: active_branches에서 이름 매칭, 없으면 repo.web_url
            web_url = activity.repo.web_url
            for active_branch in activity.active_branches:
                if active_branch.name == branch_name:
                    web_url = active_branch.web_url
                    break

            signals.append(
                NewWorkSignal(
                    title=branch_name,
                    repo_full_path=activity.repo.full_path,
                    branch_or_mr=branch_name,
                    web_url=web_url,
                )
            )

    return signals


def _create_new_work_from_recent_mrs(
    activities: tuple[RepoActivity, ...],
    now: datetime,
    lookback_hours: int,
) -> list[NewWorkSignal]:
    """lookback_hours 이내의 신규 MR으로부터 신규 작업 신호를 생성한다."""
    signals = []
    lookback_seconds = lookback_hours * 3600

    for activity in activities:
        for mr in activity.merge_requests:
            if (now - mr.created_at).total_seconds() < lookback_seconds:
                signals.append(
                    NewWorkSignal(
                        title=mr.title,
                        repo_full_path=activity.repo.full_path,
                        branch_or_mr=f"!{mr.iid}",
                        web_url=mr.web_url,
                    )
                )

    return signals


def _sort_new_work_signals(signals: list[NewWorkSignal]) -> list[NewWorkSignal]:
    """신규 작업 신호를 일관되게 정렬.

    정렬 순서:
    1. repo_full_path (사전순)
    2. branch_or_mr에서 "!" 유무 (브랜치 먼저)
    3. branch_or_mr (사전순)
    """
    return sorted(
        signals,
        key=lambda s: (s.repo_full_path, "!" in s.branch_or_mr, s.branch_or_mr),
    )


def commit_histogram_by_date(
    commits: tuple[CommitInfo, ...],
    days: int,
    end_date: date,
) -> tuple[tuple[str, int], ...]:
    """커밋을 날짜별 카운트로 집계 (머지 커밋 제외, 최근 days일 고정 창, 0 포함, 오름차순 정렬).

    Args:
        commits: CommitInfo 튜플
        days: 윈도우 일수 (기본 7)
        end_date: 윈도우 종료 날짜

    Returns:
        (ISO date, count) 튜플, 과거→최신 순서 정렬 (스파크라인 좌→우)
    """
    # 최근 days일 범위 정의
    start_date = end_date - timedelta(days=days - 1)

    # 머지 커밋 제외
    non_merge_commits = [c for c in commits if not _is_merge_commit(c.message)]

    # 날짜별 카운트
    counts: dict[date, int] = {}
    for d in range(days):
        current_date = start_date + timedelta(days=d)
        counts[current_date] = 0

    for commit in non_merge_commits:
        commit_date = commit.authored_at.date()
        if start_date <= commit_date <= end_date:
            counts[commit_date] = counts.get(commit_date, 0) + 1

    # 정렬 (과거→최신)
    sorted_items = sorted(counts.items())
    return tuple((d.isoformat(), c) for d, c in sorted_items)


def generate_new_work_signals(
    activities: tuple[RepoActivity, ...],
    now: datetime,
    lookback_hours: int,
) -> list[NewWorkSignal]:
    """신규 작업 신호를 생성한다.

    created_branches는 스냅샷 diff 결과를 그대로 신규로 취급.
    신규 MR: created_at이 lookback_hours 이내.
    """
    signals = []
    signals.extend(_create_new_work_from_branches(activities))
    signals.extend(_create_new_work_from_recent_mrs(activities, now, lookback_hours))
    return _sort_new_work_signals(signals)
