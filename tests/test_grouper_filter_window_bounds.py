"""grouper의 filter_activities_to_window 상한 필터 테스트."""

from datetime import datetime
from zoneinfo import ZoneInfo

from pulse.grouper.core import filter_activities_to_window
from pulse.models import BranchInfo, CommitInfo, MergeRequestInfo, RepoActivity, RepoRef

_TEST_REPO = RepoRef(
    provider="github",
    base_url="https://github.com",
    namespace="test",
    name="repo",
    web_url="https://github.com/test/repo",
)


def test_filter_activities_excludes_beyond_upper_bound() -> None:
    """상한보다 큰 시각의 활동은 제외된다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    commit_before = CommitInfo(
        sha="abc1",
        author_name="Alice",
        authored_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=tz),
        message="커밋 1",
        branch="main",
        changed_files=("file1.py",),
        web_url="https://example.com/commit1",
    )
    commit_at_now = CommitInfo(
        sha="abc2",
        author_name="Bob",
        authored_at=now,
        message="커밋 2 (상한)",
        branch="main",
        changed_files=("file2.py",),
        web_url="https://example.com/commit2",
    )
    commit_after = CommitInfo(
        sha="abc3",
        author_name="Charlie",
        authored_at=datetime(2026, 7, 24, 12, 0, 0, tzinfo=tz),
        message="커밋 3 (상한 초과)",
        branch="main",
        changed_files=("file3.py",),
        web_url="https://example.com/commit3",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(commit_before, commit_at_now, commit_after),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    # 24시간 필터, now = 2026-07-23 12:00
    filtered = filter_activities_to_window((activity,), 24, now)

    # 상한 이내(now 포함)는 2개, 상한 초과는 1개 제외
    assert len(filtered[0].commits) == 2
    assert filtered[0].commits[0].sha == "abc1"
    assert filtered[0].commits[1].sha == "abc2"


def test_filter_activities_upper_bound_inclusive() -> None:
    """정확히 상한 시각인 활동은 포함된다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    commit_at_now = CommitInfo(
        sha="abc",
        author_name="Alice",
        authored_at=now,
        message="상한 시각 커밋",
        branch="main",
        changed_files=("file.py",),
        web_url="https://example.com/commit",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(commit_at_now,),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    assert len(filtered[0].commits) == 1
    assert filtered[0].commits[0].sha == "abc"


def test_filter_activities_lower_bound_inclusive() -> None:
    """정확히 하한 시각인 활동은 포함된다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)
    cutoff = datetime(2026, 7, 22, 12, 0, 0, tzinfo=tz)

    commit_at_cutoff = CommitInfo(
        sha="abc",
        author_name="Alice",
        authored_at=cutoff,
        message="하한 시각 커밋",
        branch="main",
        changed_files=("file.py",),
        web_url="https://example.com/commit",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(commit_at_cutoff,),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    assert len(filtered[0].commits) == 1
    assert filtered[0].commits[0].sha == "abc"


def test_filter_activities_mrs_upper_bound() -> None:
    """MR updated_at도 상한 필터가 적용된다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    mr_before = MergeRequestInfo(
        iid=1,
        title="MR 1",
        state="open",
        is_draft=False,
        labels=(),
        source_branch="feature",
        target_branch="main",
        author_name="Alice",
        created_at=datetime(2026, 7, 22, 10, 0, 0, tzinfo=tz),
        updated_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=tz),
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url="https://example.com/mr1",
    )
    mr_at_now = MergeRequestInfo(
        iid=2,
        title="MR 2",
        state="merged",
        is_draft=False,
        labels=(),
        source_branch="feature",
        target_branch="main",
        author_name="Bob",
        created_at=datetime(2026, 7, 22, 10, 0, 0, tzinfo=tz),
        updated_at=now,
        merged_at=now,
        reviews=(),
        is_external=False,
        web_url="https://example.com/mr2",
    )
    mr_after = MergeRequestInfo(
        iid=3,
        title="MR 3",
        state="closed",
        is_draft=False,
        labels=(),
        source_branch="feature",
        target_branch="main",
        author_name="Charlie",
        created_at=datetime(2026, 7, 22, 10, 0, 0, tzinfo=tz),
        updated_at=datetime(2026, 7, 24, 12, 0, 0, tzinfo=tz),
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url="https://example.com/mr3",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(mr_before, mr_at_now, mr_after),
        collected_at=now,
        stale_branches=(),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    # 상한 이내(now 포함)는 2개, 상한 초과는 1개 제외
    assert len(filtered[0].merge_requests) == 2
    assert filtered[0].merge_requests[0].iid == 1
    assert filtered[0].merge_requests[1].iid == 2


def test_filter_activities_branches_upper_bound() -> None:
    """active_branches의 last_pushed_at도 상한 필터가 적용된다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    branch_before = BranchInfo(
        name="branch1",
        last_commit_sha="abc1",
        last_pushed_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=tz),
        web_url="https://example.com/branch1",
    )
    branch_at_now = BranchInfo(
        name="branch2",
        last_commit_sha="abc2",
        last_pushed_at=now,
        web_url="https://example.com/branch2",
    )
    branch_after = BranchInfo(
        name="branch3",
        last_commit_sha="abc3",
        last_pushed_at=datetime(2026, 7, 24, 12, 0, 0, tzinfo=tz),
        web_url="https://example.com/branch3",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(branch_before, branch_at_now, branch_after),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    # 상한 이내(now 포함)는 2개, 상한 초과는 1개 제외
    assert len(filtered[0].active_branches) == 2
    assert filtered[0].active_branches[0].name == "branch1"
    assert filtered[0].active_branches[1].name == "branch2"


def test_filter_activities_created_deleted_branches_not_filtered() -> None:
    """created_branches와 deleted_branches는 필터링되지 않는다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=("branch1", "branch2", "branch3"),
        deleted_branches=("old1", "old2"),
        merge_requests=(),
        collected_at=now,
        stale_branches=(),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    # 생성/삭제 브랜치는 전체 유지
    assert len(filtered[0].created_branches) == 3
    assert len(filtered[0].deleted_branches) == 2


def test_filter_activities_stale_branches_not_filtered() -> None:
    """stale_branches는 필터링되지 않는다."""
    tz = ZoneInfo("UTC")
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=tz)

    stale1 = BranchInfo(
        name="stale1",
        last_commit_sha="abc1",
        last_pushed_at=datetime(2026, 7, 20, 12, 0, 0, tzinfo=tz),
        web_url="https://example.com/stale1",
    )
    stale2 = BranchInfo(
        name="stale2",
        last_commit_sha="abc2",
        last_pushed_at=datetime(2026, 7, 19, 12, 0, 0, tzinfo=tz),
        web_url="https://example.com/stale2",
    )

    activity = RepoActivity(
        repo=_TEST_REPO,
        status="ok",
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=now,
        stale_branches=(stale1, stale2),
    )

    filtered = filter_activities_to_window((activity,), 24, now)

    # 정체 브랜치는 전체 유지
    assert len(filtered[0].stale_branches) == 2
