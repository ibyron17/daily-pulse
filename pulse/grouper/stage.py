"""진행 단계 추정 (merged/reviewing/developing/other)."""

from datetime import datetime
from typing import Literal

from pulse.models import FeatureGroup, MergeRequestInfo

MERGE_WINDOW_SECONDS = 48 * 3600
REVIEW_WAIT_HOURS = 24
ACTIVE_BRANCH_DAYS = 7


def has_review_activity(mr: MergeRequestInfo) -> bool:
    """MR에 리뷰 활동(approved, changes_requested, commented) 있는지 판정."""
    return any(
        review.kind in ("approved", "changes_requested", "commented") for review in mr.reviews
    )


def _is_merged_stage(
    group: FeatureGroup,
    now: datetime,
) -> bool:
    """가장 최근 merged MR이 48시간 이내인지 판정."""
    merged_mrs = [mr for mr in group.merge_requests if mr.state == "merged" and mr.merged_at]
    if not merged_mrs:
        return False

    most_recent_merged = max(merged_mrs, key=lambda mr: mr.merged_at or datetime.min)
    return bool(
        most_recent_merged.merged_at
        and (now - most_recent_merged.merged_at).total_seconds() < MERGE_WINDOW_SECONDS
    )


def _is_reviewing_stage(
    group: FeatureGroup,
    now: datetime,
) -> bool:
    """open non-draft MR이 리뷰 활동이 있거나 24시간 이상인지 판정."""
    open_nondraft_mrs = [
        mr for mr in group.merge_requests if mr.state == "open" and not mr.is_draft
    ]
    if not open_nondraft_mrs:
        return False

    for mr in open_nondraft_mrs:
        has_review = has_review_activity(mr)
        is_old = (now - mr.created_at).total_seconds() >= REVIEW_WAIT_HOURS * 3600
        if has_review or is_old:
            return True

    return False


def _is_developing_stage(
    group: FeatureGroup,
    now: datetime,
) -> bool:
    """draft MR, open MR, 또는 활성 브랜치 (7일 이내 push)가 있는지 판정."""
    # draft MR
    for mr in group.merge_requests:
        if mr.is_draft:
            return True

    # open MR
    open_nondraft_mrs = [
        mr for mr in group.merge_requests if mr.state == "open" and not mr.is_draft
    ]
    if open_nondraft_mrs:
        return True

    # 활성 브랜치 판정 (last_pushed_at이 7일 이내면 활성)
    for branch in group.branches:
        if branch.last_pushed_at and (now - branch.last_pushed_at).days < ACTIVE_BRANCH_DAYS:
            return True

    return False


def estimate_stage(
    group: FeatureGroup,
    now: datetime,
) -> Literal["merged", "reviewing", "developing", "other"]:
    """그룹의 진행 단계를 추정한다. (merged > reviewing > developing > other)."""
    if _is_merged_stage(group, now):
        return "merged"

    if _is_reviewing_stage(group, now):
        return "reviewing"

    if _is_developing_stage(group, now):
        return "developing"

    return "other"
