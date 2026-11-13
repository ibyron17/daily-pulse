"""필터링이 수집 시맨틱과 동등함을 검증 (일간 뷰 회귀 방지)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pulse.grouper.core import filter_activities_to_window
from tests.conftest import (
    make_branch,
    make_commit,
    make_merge_request,
    make_repo_activity,
)

KST = ZoneInfo("Asia/Seoul")


def test_filter_activities_to_window_commits_by_authored_at() -> None:
    """커밋 필터: authored_at 기준."""
    now = datetime(2026, 7, 20, 12, 0, tzinfo=KST)

    # 24h 내 커밋
    recent_commit = make_commit(
        author_name="Alice",
        authored_at=now - timedelta(hours=1),
        branch="main",
        message="recent change",
    )

    # 24h 외 커밋 (168h 내)
    old_commit = make_commit(
        author_name="Bob",
        authored_at=now - timedelta(hours=48),
        branch="develop",
        message="old change",
    )

    activity = make_repo_activity(commits=(recent_commit, old_commit))

    # 168h 범위 픽스처에 24h 필터 적용
    filtered = filter_activities_to_window((activity,), 24, now)

    # 24h 내 커밋만 남아야 함
    assert len(filtered) == 1
    assert len(filtered[0].commits) == 1
    assert filtered[0].commits[0].author_name == "Alice"


def test_filter_activities_to_window_mrs_by_updated_at() -> None:
    """MR 필터: updated_at 기준 (수집 업데이트_후 의미와 일치)."""
    now = datetime(2026, 7, 20, 12, 0, tzinfo=KST)

    # 최근 업데이트 MR (24h 내)
    recent_mr = make_merge_request(
        iid=1,
        title="Recent MR",
        source_branch="feature/quick",
        created_at=now - timedelta(hours=48),  # 생성은 오래됐지만
        updated_at=now - timedelta(hours=1),  # 업데이트는 최근
    )

    # 오래된 업데이트 MR (24h 외)
    old_mr = make_merge_request(
        iid=2,
        title="Old MR",
        source_branch="feature/stale",
        created_at=now - timedelta(hours=72),
        updated_at=now - timedelta(hours=48),
    )

    activity = make_repo_activity(merge_requests=(recent_mr, old_mr))

    # 24h 필터 적용
    filtered = filter_activities_to_window((activity,), 24, now)

    # updated_at이 24h 내인 MR만 남아야 함 (생성 시점 무관)
    assert len(filtered[0].merge_requests) == 1
    assert filtered[0].merge_requests[0].iid == 1


def test_filter_activities_to_window_active_branches_by_last_pushed() -> None:
    """active_branches 필터: last_pushed_at 기준."""
    now = datetime(2026, 7, 20, 12, 0, tzinfo=KST)

    recent_branch = make_branch(
        name="feature/active",
        last_pushed_at=now - timedelta(hours=1),
    )
    old_branch = make_branch(
        name="feature/stale",
        last_pushed_at=now - timedelta(hours=48),
    )

    activity = make_repo_activity(active_branches=(recent_branch, old_branch))

    # 24h 필터 적용
    filtered = filter_activities_to_window((activity,), 24, now)

    # last_pushed_at이 24h 내인 브랜치만 남아야 함
    assert len(filtered[0].active_branches) == 1
    assert filtered[0].active_branches[0].name == "feature/active"


def test_filter_activities_excludes_created_branches_always() -> None:
    """created_branches는 항상 전체 유지 (신규 브랜치 신호용)."""
    now = datetime(2026, 7, 20, 12, 0, tzinfo=KST)

    activity = make_repo_activity(created_branches=("feature/new1", "feature/new2"))

    # 24h 필터 적용해도
    filtered = filter_activities_to_window((activity,), 24, now)

    # created_branches는 유지되어야 함
    assert filtered[0].created_branches == ("feature/new1", "feature/new2")


def test_filter_activities_excludes_stale_branches_always() -> None:
    """stale_branches는 항상 전체 유지 (정체 감지용)."""
    now = datetime(2026, 7, 20, 12, 0, tzinfo=KST)

    stale = (
        make_branch(name="old-feature", last_pushed_at=now - timedelta(days=10)),
        make_branch(name="abandoned", last_pushed_at=now - timedelta(days=20)),
    )

    activity = make_repo_activity(stale_branches=stale)

    # 24h 필터 적용해도
    filtered = filter_activities_to_window((activity,), 24, now)

    # stale_branches는 유지되어야 함
    assert len(filtered[0].stale_branches) == 2
