"""파이프라인의 브랜치 히스토리 증분 판정·그룹 조인 테스트."""

from datetime import date, datetime, timezone

from pulse.branch_history import BranchHistoryStore, build_entry, history_key
from pulse.models import (
    BranchHistoryFetch,
    BranchInfo,
    FeatureGroup,
    GroupLifecycleView,
    HistoryCommit,
    RepoActivity,
    RepoRef,
)
from pulse.pipeline import _history_requests, _join_branch_history

TODAY = date(2026, 7, 27)
REPO = RepoRef(
    provider="gitlab",
    base_url="http://gitlab.test",
    namespace="org",
    name="repo",
    web_url="http://gitlab.test/org/repo",
)


def branch(name: str, sha: str) -> BranchInfo:
    """활동 브랜치 정보."""
    return BranchInfo(
        name=name,
        last_commit_sha=sha,
        last_pushed_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        web_url=f"http://gitlab.test/org/repo/tree/{name}",
    )


def activity(*branches: BranchInfo, status: str = "ok") -> RepoActivity:
    """레포 활동 (히스토리 판정에 필요한 부분만 채운다)."""
    return RepoActivity(
        repo=REPO,
        status=status,  # type: ignore[arg-type]
        failure_reason=None,
        commits=(),
        active_branches=branches,
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )


def store_with(branch_name: str, head_sha: str) -> BranchHistoryStore:
    """해당 브랜치의 히스토리가 캐시된 저장소."""
    fetch = BranchHistoryFetch(
        branch_name=branch_name,
        base_branch="develop",
        merge_base_sha="mb",
        head_sha=head_sha,
        commits=(
            HistoryCommit(
                sha="c1",
                worked_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
                title="[feat] 시작",
            ),
        ),
        total_commits=1,
        truncated=False,
        behind_count=3,
    )
    return BranchHistoryStore(
        schema_version=1,
        updated_at=datetime.now(timezone.utc),
        entries=((history_key("org/repo", branch_name), build_entry(None, fetch, TODAY)),),
    )


def group(
    name: str,
    branches: tuple[str, ...],
    kind: str = "feature",
    lifecycle: GroupLifecycleView | None = None,
) -> FeatureGroup:
    """기능/라인 그룹."""
    return FeatureGroup(
        name=name,
        source_rule="branch",
        evidence=name,
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=branches,
        participants=(),
        group_kind=kind,  # type: ignore[arg-type]
        lifecycle=lifecycle,
    )


def lifecycle_view(first_seen: str, total_days: int) -> GroupLifecycleView:
    """등록부 조인 뷰 (보정 대상 필드만 의미 있게 채운다)."""
    return GroupLifecycleView(
        first_seen=first_seen,
        total_days=total_days,
        current_stage="developing",
        current_stage_days=2,
        active_days=1,
        cumulative_commits=5,
    )


class TestHistoryRequests:
    def test_unchanged_head_is_skipped(self) -> None:
        """캐시된 SHA와 같으면 조회하지 않는다 — 과거는 변하지 않는다."""
        store = store_with("feature/x", "head1")
        requests = _history_requests((activity(branch("feature/x", "head1")),), store)
        assert requests == {}

    def test_changed_head_is_requested(self) -> None:
        store = store_with("feature/x", "head1")
        requests = _history_requests((activity(branch("feature/x", "head2")),), store)
        assert list(requests) == ["org/repo"]
        assert requests["org/repo"][0].branch_name == "feature/x"
        assert requests["org/repo"][0].head_sha == "head2"

    def test_unknown_branch_is_requested(self) -> None:
        empty = BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc))
        requests = _history_requests((activity(branch("feature/new", "h")),), empty)
        assert requests["org/repo"][0].branch_name == "feature/new"

    def test_only_changed_branches_are_requested(self) -> None:
        store = store_with("feature/x", "head1")
        requests = _history_requests(
            (activity(branch("feature/x", "head1"), branch("feature/y", "head9")),), store
        )
        assert [item.branch_name for item in requests["org/repo"]] == ["feature/y"]

    def test_failed_repo_is_excluded(self) -> None:
        empty = BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc))
        requests = _history_requests((activity(branch("feature/x", "h"), status="failed"),), empty)
        assert requests == {}

    def test_no_active_branches_yields_nothing(self) -> None:
        empty = BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc))
        assert _history_requests((activity(),), empty) == {}


class TestJoinBranchHistory:
    def test_feature_group_receives_view(self) -> None:
        store = store_with("feature/x", "head1")
        joined = _join_branch_history(
            (group("feature/x", ("feature/x",)),), store, TODAY, min_tag_coverage=0.5
        )
        view = joined[0].branch_history
        assert view is not None
        assert view.started_on == "2026-05-27"
        assert view.base_branch == "develop"
        assert view.behind_count == 3

    def test_line_group_is_not_joined(self) -> None:
        """라인은 상시 통로 — 누적 서사를 붙이지 않는다."""
        store = store_with("develop", "head1")
        joined = _join_branch_history(
            (group("develop", ("develop",), kind="line"),), store, TODAY, min_tag_coverage=0.5
        )
        assert joined[0].branch_history is None

    def test_group_without_stored_branch_stays_none(self) -> None:
        store = store_with("feature/x", "head1")
        joined = _join_branch_history(
            (group("feature/other", ("feature/other",)),), store, TODAY, min_tag_coverage=0.5
        )
        assert joined[0].branch_history is None

    def test_group_name_is_used_when_branch_names_empty(self) -> None:
        """branch_names가 빈 그룹이 흔하고, 그때 group.name이 브랜치명이다.

        실측: 주간 그룹 13개 중 대부분이 branch_names=[] 였고 그룹명이 브랜치명이었다.
        후보에 group.name을 넣지 않으면 가장 큰 그룹조차 히스토리가 붙지 않는다.
        """
        store = store_with("feature/oauth", "head1")
        joined = _join_branch_history(
            (group("feature/oauth", ()),), store, TODAY, min_tag_coverage=0.5
        )
        assert joined[0].branch_history is not None

    def test_first_stored_branch_is_used_as_representative(self) -> None:
        store = store_with("feature/x", "head1")
        joined = _join_branch_history(
            (group("묶음", ("feature/unknown", "feature/x")),), store, TODAY, min_tag_coverage=0.5
        )
        assert joined[0].branch_history is not None

    def test_high_coverage_threshold_hides_tags(self) -> None:
        store = store_with("feature/x", "head1")
        joined = _join_branch_history(
            (group("feature/x", ("feature/x",)),), store, TODAY, min_tag_coverage=1.1
        )
        assert joined[0].branch_history is not None
        assert joined[0].branch_history.tags is None

    def test_empty_groups(self) -> None:
        store = store_with("feature/x", "head1")
        assert _join_branch_history((), store, TODAY, min_tag_coverage=0.5) == ()


class TestLifecycleStartReconciliation:
    """관측 시작일이 개발 시작일로 잘못 읽히는 것을 막는 보정.

    실측: 7/7에 시작한 브랜치가 도구 도입일(7/20) 기준 "11일째"로 서술됐다.
    브랜치 이력이 더 이른 작업 시작을 알면 lifecycle 시작일·경과일을 그쪽으로 맞춘다.
    """

    def test_later_observation_is_corrected_to_history_start(self) -> None:
        store = store_with("feature/x", "head1")  # 이력 시작 2026-05-27
        observed = lifecycle_view(first_seen="2026-07-20", total_days=8)
        joined = _join_branch_history(
            (group("feature/x", ("feature/x",), lifecycle=observed),),
            store,
            TODAY,
            min_tag_coverage=0.5,
        )
        adjusted = joined[0].lifecycle
        assert adjusted is not None
        assert adjusted.first_seen == "2026-05-27"
        assert adjusted.total_days == 62  # 5/27 ~ 7/27 포함
        # 보정 대상 밖의 필드는 그대로다
        assert adjusted.current_stage == "developing"
        assert adjusted.current_stage_days == 2

    def test_earlier_observation_is_kept(self) -> None:
        """등록부가 이력보다 먼저 관측했다면 (예: 브랜치 재생성) 등록부가 진실이다."""
        store = store_with("feature/x", "head1")
        observed = lifecycle_view(first_seen="2026-05-01", total_days=88)
        joined = _join_branch_history(
            (group("feature/x", ("feature/x",), lifecycle=observed),),
            store,
            TODAY,
            min_tag_coverage=0.5,
        )
        assert joined[0].lifecycle == observed

    def test_group_without_lifecycle_stays_none(self) -> None:
        store = store_with("feature/x", "head1")
        joined = _join_branch_history(
            (group("feature/x", ("feature/x",)),), store, TODAY, min_tag_coverage=0.5
        )
        assert joined[0].lifecycle is None
        assert joined[0].branch_history is not None

    def test_group_without_history_keeps_lifecycle(self) -> None:
        store = store_with("feature/x", "head1")
        observed = lifecycle_view(first_seen="2026-07-20", total_days=8)
        joined = _join_branch_history(
            (group("feature/other", ("feature/other",), lifecycle=observed),),
            store,
            TODAY,
            min_tag_coverage=0.5,
        )
        assert joined[0].lifecycle == observed
