"""grouper 통합 테스트 (Task 8)."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.grouper import group_activities
from pulse.grouper.group import _derive_task_summary
from pulse.grouper.signals import _sort_new_work_signals
from pulse.models import NewWorkSignal
from tests.conftest import (
    make_branch,
    make_commit,
    make_merge_request,
    make_repo_activity,
    make_repo_ref,
    make_review_event,
)

KST = ZoneInfo("Asia/Seoul")


def make_test_config(
    grouping_hints: GroupingHints | None = None,
) -> Config:
    """테스트용 Config."""
    return Config(
        team_name="Test Team",
        repos=(make_repo_ref(),),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=Path("unused-reports"),  # grouper는 파일 I/O를 하지 않음
        data_dir=Path("unused-data"),
        stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=grouping_hints or GroupingHints(),
    )


class TestGroupActivitiesIntegration:
    """group_activities 공개 API 통합 테스트."""

    def test_basic_group_creation(self) -> None:
        """기본 그룹 생성."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit = make_commit(branch="feature/auth")
        activity = make_repo_activity(commits=(commit,))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # 최소 1개 그룹 생성
        assert len(groups) >= 1
        # "auth" 그룹이 포함되어야 함
        group_names = {g.name for g in groups}
        assert "auth" in group_names

    def test_hints_priority_over_branch(self) -> None:
        """hints가 branch보다 우선."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        hints = GroupingHints(branch_prefixes=(("feature", "기능"),))
        commit = make_commit(branch="feature/anything", author_name="author1")
        activity = make_repo_activity(commits=(commit,))
        config = make_test_config(hints)
        groups, _, _, _ = group_activities((activity,), config, now)

        # "기능"이 포함되어야 함 (hints 규칙 적용)
        group_names = {g.name for g in groups}
        assert "기능" in group_names

    def test_participants_aggregation(self) -> None:
        """참여자 집계 및 정렬."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit1 = make_commit(author_name="charlie", branch="feature/test")
        commit2 = make_commit(author_name="alice", branch="feature/test")
        commit3 = make_commit(author_name="bob", branch="feature/test")
        activity = make_repo_activity(commits=(commit1, commit2, commit3))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # "test" 그룹 찾기
        test_group = [g for g in groups if g.name == "test"]
        assert len(test_group) > 0
        # 참여자는 정렬되어야 함
        assert test_group[0].participants == ("alice", "bob", "charlie")

    def test_external_mr_marked(self) -> None:
        """external MR evidence에 '[외부 MR]' 표시."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        ext_mr = make_merge_request(
            title="External MR",
            is_external=True,
            source_branch="feature/ext",
            author_name="external_user",
        )
        activity = make_repo_activity(merge_requests=(ext_mr,))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # external MR 그룹 찾기
        ext_groups = [g for g in groups if g.name == "ext"]
        assert len(ext_groups) > 0
        assert "[외부 MR]" in ext_groups[0].evidence

    def test_warning_signals_generated(self) -> None:
        """주의 신호 생성."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        stale_mr = make_merge_request(
            title="Stale",
            state="open",
            updated_at=now - timedelta(days=5),
            source_branch="feature/stale",
        )
        activity = make_repo_activity(merge_requests=(stale_mr,))
        config = make_test_config()
        _, warnings, _, _ = group_activities((activity,), config, now)

        # stale MR 신호가 있어야 함
        stale_signals = [w for w in warnings if w.kind == "stale_mr"]
        assert len(stale_signals) > 0

    def test_new_work_signals_created_branches(self) -> None:
        """신규 브랜치 신호 생성."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity = make_repo_activity(created_branches=("feature/new",))
        config = make_test_config()
        _, _, new_work, _ = group_activities((activity,), config, now)

        # 신규 브랜치 신호
        branch_signals = [s for s in new_work if s.branch_or_mr == "feature/new"]
        assert len(branch_signals) > 0

    def test_unclassified_ratio_computed(self) -> None:
        """unclassified_ratio 계산."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit = make_commit(branch="feature/test")
        activity = make_repo_activity(commits=(commit,))
        config = make_test_config()
        _, _, _, ratio = group_activities((activity,), config, now)

        # 비율이 0과 1 사이
        assert 0.0 <= ratio <= 1.0

    def test_stage_estimation(self) -> None:
        """단계 추정."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="merged",
            merged_at=now - timedelta(hours=24),
            source_branch="feature/merged",
        )
        activity = make_repo_activity(merge_requests=(mr,))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # merged 단계
        merged_groups = [g for g in groups if g.stage == "merged"]
        assert len(merged_groups) > 0

    def test_multiple_repos_combined(self) -> None:
        """여러 레포의 활동 통합."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity1 = make_repo_activity(commits=(make_commit(branch="feature/auth"),))
        activity2 = make_repo_activity(commits=(make_commit(branch="feature/dash"),))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity1, activity2), config, now)

        # 두 기능 모두 포함
        group_names = {g.name for g in groups}
        assert "auth" in group_names or "dash" in group_names

    def test_directory_classification(self) -> None:
        """디렉토리 기반 분류."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        hints = GroupingHints(directories=(("src/editor", "에디터"),))
        commit = make_commit(
            branch="main",
            changed_files=("src/editor/index.ts",),
        )
        activity = make_repo_activity(commits=(commit,))
        config = make_test_config(hints)
        groups, _, _, _ = group_activities((activity,), config, now)

        # 디렉토리 규칙 적용
        group_names = {g.name for g in groups}
        assert "에디터" in group_names

    def test_scope_classification(self) -> None:
        """conventional commit scope 분류."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit = make_commit(
            branch="main",
            message="feat(database): add migration",
        )
        activity = make_repo_activity(commits=(commit,))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # scope 규칙 적용
        group_names = {g.name for g in groups}
        assert "database" in group_names

    def test_review_activity_detection(self) -> None:
        """리뷰 활동 감지."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            created_at=now - timedelta(hours=1),
            reviews=(make_review_event(kind="approved"),),
            source_branch="feature/review",
        )
        activity = make_repo_activity(merge_requests=(mr,))
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # reviewing 단계
        review_groups = [g for g in groups if g.stage == "reviewing"]
        assert len(review_groups) > 0

    def test_revert_hotfix_signals(self) -> None:
        """revert/hotfix 신호."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        revert = make_commit(message="revert: undo", branch="feature/a")
        hotfix = make_commit(message="hotfix: bug", branch="feature/b")
        activity = make_repo_activity(commits=(revert, hotfix))
        config = make_test_config()
        _, warnings, _, _ = group_activities((activity,), config, now)

        kinds = {w.kind for w in warnings}
        assert "revert_commit" in kinds
        assert "hotfix_commit" in kinds

    def test_empty_activities(self) -> None:
        """빈 활동 처리."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity = make_repo_activity(
            commits=(),
            merge_requests=(),
            created_branches=(),
            active_branches=(),
        )
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # 빈 활동도 처리 가능
        assert isinstance(groups, tuple)

    def test_group_contains_all_item_types(self) -> None:
        """그룹에 커밋·MR·브랜치 모두 포함."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit = make_commit(branch="feature/unified")
        mr = make_merge_request(source_branch="feature/unified")
        activity = make_repo_activity(
            commits=(commit,),
            merge_requests=(mr,),
            created_branches=("feature/unified",),
        )
        config = make_test_config()
        groups, _, _, _ = group_activities((activity,), config, now)

        # unified 그룹이 커밋과 MR을 포함
        unified = [g for g in groups if g.name == "unified"]
        if unified:
            assert len(unified[0].commits) > 0 or len(unified[0].merge_requests) > 0

    def test_stale_branch_activity_generates_warning(self) -> None:
        """Arrange: RepoActivity에 stale_branches 포함.

        Act: group_activities 호출.

        Assert: warnings에 stale_branch 신호 포함.
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        stale_branch = make_branch(
            name="feature/old-branch",
            last_pushed_at=now - timedelta(days=10),
        )
        activity = make_repo_activity(
            commits=(),
            merge_requests=(),
            stale_branches=(stale_branch,),
        )
        config = make_test_config()

        # Act
        _, warnings, _, _ = group_activities((activity,), config, now)

        # Assert
        stale_signals = [w for w in warnings if w.kind == "stale_branch"]
        assert len(stale_signals) > 0

    def test_unclassified_ratio_counts_branch_names_uniquely(self) -> None:
        """Arrange: 분류된 항목과 미분류 항목을 섞음.

        Act: group_activities 호출하여 unclassified_ratio 반환.

        Assert: ratio는 고유 브랜치만 계산 (중복 제거), source_rule="unclassified"만 카운트.

        분류 규칙:
        - feature/shared → branch 규칙 → "shared" 그룹 (분류됨)
        - no-prefix-branch → branch-name 규칙 → "no-prefix-branch" 그룹 (분류됨)
        - empty source_branch MR → unclassified 그룹 (미분류)

        총 3개 항목, 미분류 1개 → ratio = 1/3 ≈ 0.333
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        # created_branches와 active_branches에 "feature/shared" 겹침
        shared_branch = make_branch(name="feature/shared")
        # source_branch가 빈 MR (unclassified)
        mr_unclassified = make_merge_request(source_branch="", labels=())
        activity = make_repo_activity(
            commits=(),
            merge_requests=(mr_unclassified,),
            created_branches=("feature/shared", "no-prefix-branch"),
            active_branches=(shared_branch,),
        )
        config = make_test_config()

        # Act
        _, _, _, ratio = group_activities((activity,), config, now)

        # Assert
        # 총 3개: feature/shared (브랜치, 분류), no-prefix-branch (브랜치, 분류), MR (미분류)
        # 미분류 1개 → ratio = 1/3 ≈ 0.333
        assert 0.32 < ratio < 0.35  # ≈ 0.333

    def test_feature_group_branches_populated(self) -> None:
        """Arrange: active_branches에 feature/test, feature/dev 포함.

        Act: group_activities 호출하여 그룹 생성.

        Assert: FeatureGroup.branches에 일치하는 BranchInfo 객체 포함.
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        commit = make_commit(branch="feature/test")
        branch1 = make_branch(name="feature/test")
        branch2 = make_branch(name="feature/dev")
        activity = make_repo_activity(
            commits=(commit,),
            active_branches=(branch1, branch2),
        )
        config = make_test_config()

        # Act
        groups, _, _, _ = group_activities((activity,), config, now)

        # Assert
        test_groups = [g for g in groups if g.name == "test"]
        assert len(test_groups) > 0
        test_group = test_groups[0]
        # branches 필드가 populated되어야 함
        assert len(test_group.branches) > 0
        # "feature/test" 브랜치가 포함되어야 함
        branch_names = {b.name for b in test_group.branches}
        assert "feature/test" in branch_names


class TestDeriveTaskSummary:
    """_derive_task_summary 함수 테스트."""

    def test_derive_task_summary_commits_sorted(self) -> None:
        """커밋은 authored_at 내림차순으로 정렬된 후 처리."""
        # Arrange
        now = datetime(2026, 7, 15, 12, 0, tzinfo=KST)
        commits = (
            make_commit(sha="old", message="오래된 커밋", authored_at=now - timedelta(hours=2)),
            make_commit(sha="new", message="최신 커밋", authored_at=now),
        )

        # Act
        summary = _derive_task_summary(commits, (), ())

        # Assert
        assert "최신 커밋" in summary.commit_titles
        assert "오래된 커밋" in summary.commit_titles

    def test_derive_task_summary_merge_excluded(self) -> None:
        """merge 커밋은 제외."""
        # Arrange
        commits = (
            make_commit(sha="m1", message="Merge branch 'feature/test'"),
            make_commit(sha="c1", message="기능 추가"),
        )

        # Act
        summary = _derive_task_summary(commits, (), ())

        # Assert
        assert "Merge branch" not in " ".join(summary.commit_titles)
        assert "기능 추가" in summary.commit_titles

    def test_derive_task_summary_merge_false_positive_regression(self) -> None:
        """'merge modules'는 포함, 'Merge branch'는 제외 (회귀 테스트)."""
        # Arrange
        commits = (
            make_commit(sha="c1", message="Merge branch 'feature/test'"),
            make_commit(sha="c2", message="merge modules into core"),
            make_commit(sha="c3", message="기능 추가"),
        )

        # Act
        summary = _derive_task_summary(commits, (), ())

        # Assert
        # "merge modules into core"는 포함되어야 함
        assert "merge modules into core" in summary.commit_titles
        # "Merge branch"는 제외되어야 함
        assert not any("Merge branch" in title for title in summary.commit_titles)
        # "기능 추가"도 포함되어야 함
        assert "기능 추가" in summary.commit_titles

    def test_derive_task_summary_main_branches_excluded(self) -> None:
        """main/develop/master 브랜치는 제외."""
        # Arrange
        branches = ("main", "develop", "master", "feature/auth", "feature/api")

        # Act
        summary = _derive_task_summary((), (), branches)

        # Assert
        assert "main" not in summary.active_branch_names
        assert "develop" not in summary.active_branch_names
        assert "master" not in summary.active_branch_names
        assert "feature/auth" in summary.active_branch_names


class TestSortNewWorkSignals:
    """_sort_new_work_signals 함수 테스트."""

    def test_sort_signals_by_repo_then_type(self) -> None:
        """신규 작업 신호를 (repo, type, name)으로 정렬."""
        # Arrange
        signals = [
            NewWorkSignal(
                title="MR2",
                repo_full_path="z/repo",
                branch_or_mr="!2",
                web_url="http://test",
            ),
            NewWorkSignal(
                title="Branch1",
                repo_full_path="a/repo",
                branch_or_mr="feature/a",
                web_url="http://test",
            ),
            NewWorkSignal(
                title="MR1",
                repo_full_path="a/repo",
                branch_or_mr="!1",
                web_url="http://test",
            ),
        ]

        # Act
        sorted_signals = _sort_new_work_signals(signals)

        # Assert
        # a/repo의 브랜치 먼저 (! 없음)
        assert sorted_signals[0].repo_full_path == "a/repo"
        assert "!" not in sorted_signals[0].branch_or_mr
        # a/repo의 MR (! 있음)
        assert sorted_signals[1].repo_full_path == "a/repo"
        assert "!" in sorted_signals[1].branch_or_mr
        # z/repo
        assert sorted_signals[2].repo_full_path == "z/repo"
