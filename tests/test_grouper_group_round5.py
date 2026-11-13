"""Phase 1 그룹 조립 테스트: group_kind, issue_keys, last_activity_at, normalize_commit_titles."""

from datetime import datetime, timezone

from pulse.config.loader import DEFAULT_RELEASE_LINE_PATTERNS, GroupingHints
from pulse.grouper.group import (
    _derive_group_metadata,
    _derive_task_summary,
    assemble_groups,
    normalize_commit_titles,
)
from pulse.models import CommitInfo, FeatureGroup, MergeRequestInfo, TaskSummary


class TestNormalizeCommitTitles:
    """normalize_commit_titles 테스트."""

    def test_normalize_commit_titles_no_cap(self) -> None:
        """상한 없음."""
        commits = (
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=datetime(2024, 1, i + 1),
                message=f"Commit {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(10)
        )
        titles = normalize_commit_titles(tuple(commits))
        assert len(titles) == 10

    def test_task_summary_still_capped_at_3(self) -> None:
        """TaskSummary는 여전히 3개 상한."""
        commits = (
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=datetime(2024, 1, i + 1),
                message=f"Commit {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(10)
        )
        mrs = ()
        branches = ()
        # 외부에서 _derive_task_summary를 직접 호출하지 않고,
        # normalize_commit_titles의 출력이 50개 상한만 가지는지 확인
        from pulse.grouper.group import _derive_task_summary

        task = _derive_task_summary(tuple(commits), mrs, branches)
        assert len(task.commit_titles) <= 3


class TestDeriveGroupMetadata:
    """_derive_group_metadata 테스트."""

    def test_assemble_groups_group_kind_feature(self) -> None:
        """기능 그룹."""
        commits = ()
        mrs = ()
        branch_names = ("feature/auth",)
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)
        issue_keys, group_kind, _ = _derive_group_metadata(
            "auth", commits, mrs, branch_names, hints
        )
        assert group_kind == "feature"

    def test_assemble_groups_group_kind_line(self) -> None:
        """라인 그룹."""
        commits = ()
        mrs = ()
        branch_names = ("main", "develop")
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)
        issue_keys, group_kind, _ = _derive_group_metadata(
            "main", commits, mrs, branch_names, hints
        )
        assert group_kind == "line"

    def test_assemble_groups_group_kind_line_by_name_when_no_branches(self) -> None:
        """branch_names가 빈 그룹(merged MR만 있는 SQA 등)은 그룹명으로 라인 판별한다."""
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)
        _, line_kind, _ = _derive_group_metadata("SQA", (), (), (), hints)
        assert line_kind == "line"
        _, feature_kind, _ = _derive_group_metadata("oauth-login", (), (), (), hints)
        assert feature_kind == "feature"

    def test_assemble_groups_issue_keys_populated(self) -> None:
        """이슈 키 추출."""
        commit = CommitInfo(
            sha="abc123",
            author_name="user",
            authored_at=datetime(2024, 1, 1),
            message="Fix DOCS-123",
            branch="feature/auth",
            changed_files=(),
            web_url="",
        )
        commits = (commit,)
        mrs = ()
        branch_names = ()
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)
        issue_keys, _, _ = _derive_group_metadata("feature-x", commits, mrs, branch_names, hints)
        assert "DOCS-123" in issue_keys

    def test_assemble_groups_last_activity_at_max_of_sources(self) -> None:
        """last_activity_at은 최대값."""
        commit = CommitInfo(
            sha="abc123",
            author_name="user",
            authored_at=datetime(2024, 1, 1),
            message="Fix",
            branch="main",
            changed_files=(),
            web_url="",
        )
        mr = MergeRequestInfo(
            iid=1,
            title="PR",
            state="merged",
            is_draft=False,
            labels=(),
            source_branch="feature/x",
            target_branch="main",
            author_name="user",
            created_at=datetime(2024, 1, 2),
            updated_at=datetime(2024, 1, 3),
            merged_at=datetime(2024, 1, 4),
            reviews=(),
            is_external=False,
            web_url="",
        )
        commits = (commit,)
        mrs = (mr,)
        branch_names = ()
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)
        _, _, last_activity = _derive_group_metadata("main", commits, mrs, branch_names, hints)
        assert last_activity == datetime(2024, 1, 4)


class TestFeatureGroupBackwardCompat:
    """FeatureGroup 역호환성 테스트."""

    def test_feature_group_creation_backward_compat(self) -> None:
        """신규 필드 생략 호출."""
        summary = TaskSummary((), (), ())
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="test",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            task_summary=summary,
        )
        # 신규 필드는 기본값으로 설정됨
        assert group.issue_keys == ()
        assert group.group_kind == "feature"
        assert group.daily_commit_counts == ()
        assert group.last_activity_at is None


class TestLineGroupMerging:
    """라벨 유래·브랜치 유래 라인 그룹 병합 (DEVQA/devqa 분리 회귀)."""

    def test_assemble_groups_merges_label_and_branch_line_variants(self) -> None:
        """라벨 'DEVQA'의 MR과 브랜치 'devqa'의 커밋이 한 그룹으로 합쳐진다."""
        from pulse.models import RepoActivity, RepoRef

        commit = CommitInfo(
            sha="abc123",
            author_name="user1",
            authored_at=datetime(2026, 7, 22, 9, 0),
            message="chore: 정기 배포",
            branch="devqa",
            changed_files=("a.txt",),
            web_url="",
        )
        labeled_mr = MergeRequestInfo(
            iid=1,
            title="0722 정기 배포",
            state="merged",
            is_draft=False,
            labels=("DEVQA", "정기 배포"),
            source_branch="develop",
            target_branch="devqa",
            author_name="user1",
            created_at=datetime(2026, 7, 22, 8, 0),
            updated_at=datetime(2026, 7, 22, 10, 0),
            merged_at=datetime(2026, 7, 22, 10, 0),
            reviews=(),
            is_external=False,
            web_url="",
        )
        repo = RepoRef(
            provider="gitlab",
            base_url="http://gitlab.example.com",
            namespace="org",
            name="repo",
            web_url="http://gitlab.example.com/org/repo",
        )
        activity = RepoActivity(
            repo=repo,
            status="ok",
            failure_reason=None,
            commits=(commit,),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(labeled_mr,),
            collected_at=datetime(2026, 7, 22, 12, 0),
        )
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)

        groups = assemble_groups((activity,), hints, datetime(2026, 7, 22, 12, 0))

        names = [g.name for g in groups]
        assert "DEVQA" not in names
        assert "devqa" in names
        merged_group = next(g for g in groups if g.name == "devqa")
        assert len(merged_group.commits) == 1
        assert len(merged_group.merge_requests) == 1
        assert merged_group.group_kind == "line"


class TestBranchListFallsBackToCommitBranches:
    """브랜치 목록은 커밋이 속한 브랜치로 메운다.

    활동 브랜치만 쓰면 조회 창 안에 커밋이 있어도 목록이 빌 수 있다 —
    창 필터가 브랜치의 마지막 push 한 시점만 보기 때문에, 창 이후에도 계속
    push된 브랜치가 상한을 넘겨 탈락한다(실측: feature/ai_assistant, 창 상한을 6분 초과).
    """

    def _commit(self, branch: str, sha: str = "abc") -> CommitInfo:
        return CommitInfo(
            sha=sha,
            author_name="tester",
            authored_at=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
            message="feat: 작업",
            branch=branch,
            changed_files=("src/a.ts",),
            web_url="http://example.com/c/1",
        )

    def test_commit_branch_appears_when_activity_branch_is_missing(self) -> None:
        summary = _derive_task_summary((self._commit("feature/ai_assistant"),), (), ())
        assert summary.active_branch_names == ("feature/ai_assistant",)

    def test_activity_branch_comes_first(self) -> None:
        """브랜치 목록 API에서 온 이름을 앞에 둔다."""
        summary = _derive_task_summary(
            (self._commit("feat/from-commit"),), (), ("feat/from-branch-api",)
        )
        assert summary.active_branch_names[0] == "feat/from-branch-api"

    def test_no_duplicates_when_both_sources_agree(self) -> None:
        summary = _derive_task_summary((self._commit("feat/tiptap"),), (), ("feat/tiptap",))
        assert summary.active_branch_names == ("feat/tiptap",)

    def test_main_branches_stay_excluded(self) -> None:
        """라인 그룹은 브랜치 목록을 갖지 않는다 — 커밋 쪽에서 와도 마찬가지."""
        summary = _derive_task_summary(
            (self._commit("develop"), self._commit("main", "def"), self._commit("master", "ghi")),
            (),
            (),
        )
        assert summary.active_branch_names == ()

    def test_cap_of_three_still_applies(self) -> None:
        commits = tuple(self._commit(f"feat/b{i}", sha=f"sha{i}") for i in range(5))
        summary = _derive_task_summary(commits, (), ())
        assert len(summary.active_branch_names) == 3

    def test_empty_commit_branch_is_ignored(self) -> None:
        summary = _derive_task_summary((self._commit(""),), (), ())
        assert summary.active_branch_names == ()

    def test_display_list_does_not_leak_into_group_kind(self) -> None:
        """표시용 브랜치 확장이 라인/기능 분류를 바꾸지 않는다.

        group_kind는 브랜치 목록 API에서 온 원본(+그룹명 폴백)으로 판별한다.
        표시용 목록에는 main/develop/master 제외와 상한 3개가 적용돼 있어,
        그것을 분류 근거로 쓰면 필터가 분류에까지 새어든다.
        """
        hints = GroupingHints(release_line_patterns=DEFAULT_RELEASE_LINE_PATTERNS)

        # 라인 브랜치가 창 필터로 탈락한 그룹: 브랜치 목록은 비어도 그룹명으로 line 판별
        _, kind_from_name, _ = _derive_group_metadata("sqa", (self._commit("sqa"),), (), (), hints)
        assert kind_from_name == "line"

        # 같은 입력의 표시용 목록은 main 계열 제외 규칙만 따른다
        summary = _derive_task_summary((self._commit("sqa"),), (), ())
        assert summary.active_branch_names == ("sqa",)
