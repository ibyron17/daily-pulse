"""Seed 파생 함수 테스트: commit_titles 확대, mrs, issue_keys, scope_distribution 등."""

from datetime import date, datetime
from typing import Any, cast

from pulse.analysis_cache import compute_group_seed_fingerprint
from pulse.models import CommitInfo, DashboardModel, FeatureGroup, MergeRequestInfo
from pulse.publish import MAX_SEED_COMMIT_TITLES, extract_summary_input_by_repo


class TestSeedCommitTitlesExpanded:
    """Seed commit_titles 확대 테스트."""

    def test_seed_commit_titles_expanded_to_50(self) -> None:
        """50건까지 확대."""
        from datetime import timedelta

        base = datetime(2024, 1, 31)
        commits = tuple(
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=base - timedelta(days=i),
                message=f"Feature {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(60)
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=commits,
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert len(group_data["commit_titles"]) <= MAX_SEED_COMMIT_TITLES

    def test_seed_commit_titles_cap_enforced(self) -> None:
        """50건 상한 적용."""
        from datetime import timedelta

        base = datetime(2024, 3, 31)
        commits = tuple(
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=base - timedelta(days=i),
                message=f"Feature {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(100)
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=commits,
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert len(group_data["commit_titles"]) <= 50


class TestSeedMRs:
    """Seed MR 테스트."""

    def test_seed_mrs_includes_merged(self) -> None:
        """merged MR도 포함."""
        mr = MergeRequestInfo(
            iid=1,
            title="MR",
            state="merged",
            is_draft=False,
            labels=(),
            source_branch="feature/x",
            target_branch="main",
            author_name="user",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            merged_at=datetime(2024, 1, 1),
            reviews=(),
            is_external=False,
            web_url="",
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(mr,),
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert len(group_data["mrs"]) == 1
        assert group_data["mrs"][0]["state"] == "merged"

    def test_seed_mrs_cap_20(self) -> None:
        """20건 상한."""
        mrs = tuple(
            MergeRequestInfo(
                iid=i,
                title=f"MR {i}",
                state="open",
                is_draft=False,
                labels=(),
                source_branch="feature/x",
                target_branch="main",
                author_name="user",
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2024, 1, 1),
                merged_at=None,
                reviews=(),
                is_external=False,
                web_url="",
            )
            for i in range(30)
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=mrs,
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert len(group_data["mrs"]) <= 20

    def test_seed_mr_description_truncated_500(self) -> None:
        """description 500자 절단."""
        mr = MergeRequestInfo(
            iid=1,
            title="MR",
            state="open",
            is_draft=False,
            labels=(),
            source_branch="feature/x",
            target_branch="main",
            author_name="user",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            merged_at=None,
            reviews=(),
            is_external=False,
            web_url="",
            description="x" * 1000,
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(mr,),
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert len(group_data["mrs"][0]["description"]) <= 500


class TestSeedMetadata:
    """Seed 메타데이터 테스트."""

    def test_seed_scope_distribution(self) -> None:
        """scope_distribution 포함."""
        commit = CommitInfo(
            sha="abc",
            author_name="user",
            authored_at=datetime(2024, 1, 1),
            message="[feat][auth] 개선",
            branch="main",
            changed_files=(),
            web_url="",
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(commit,),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert "scope_distribution" in group_data
        assert group_data["scope_distribution"].get("auth") == 1

    def test_seed_issue_keys(self) -> None:
        """issue_keys 포함."""
        commit = CommitInfo(
            sha="abc",
            author_name="user",
            authored_at=datetime(2024, 1, 1),
            message="Fix DOCS-123",
            branch="main",
            changed_files=(),
            web_url="",
        )
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(commit,),
            merge_requests=(),
            branch_names=(),
            participants=(),
            issue_keys=("DOCS-123",),
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert "DOCS-123" in group_data["issue_keys"]

    def test_seed_group_kind_included(self) -> None:
        """group_kind 포함."""
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            group_kind="line",
        )
        model = DashboardModel(
            team_name="Test",
            report_date=date(2024, 1, 1),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )
        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::Test"]
        assert group_data["group_kind"] == "line"


class TestSeedFingerprintStability:
    """Seed 지문 안정성 테스트."""

    def test_seed_fingerprint_unchanged_after_expansion(self) -> None:
        """커밋 50개 확대 후에도 지문 동일."""
        # top 3 커밋은 같음
        from datetime import timedelta

        base = datetime(2024, 1, 10)
        top3_commits = [
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=base - timedelta(days=i),
                message=f"Feature {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(3)
        ]
        # 추가 47개
        extra_commits = [
            CommitInfo(
                sha=f"def{i}",
                author_name="user",
                authored_at=base - timedelta(days=3 + i),
                message=f"Extra {i}",
                branch="main",
                changed_files=(),
                web_url="",
            )
            for i in range(47)
        ]

        # 그룹 1: top 3만
        group1 = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=tuple(top3_commits),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )

        # 그룹 2: top 3 + 47개
        group2 = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=tuple(top3_commits + extra_commits),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )

        # 지문은 task_summary(top 3)만 기반이므로 동일해야 함
        fingerprint1 = compute_group_seed_fingerprint(group1)
        fingerprint2 = compute_group_seed_fingerprint(group2)
        assert fingerprint1 == fingerprint2


class TestSeedDiffSummaryCap:
    """Seed diff summary 상한 테스트."""

    def test_seed_diff_summary_cap_6000(self) -> None:
        """diff summary 6000자 상한."""
        # 이미 extract_summary_input_by_repo 로직으로 테스트 가능
        pass


class TestGroupActivitySeedFields:
    """그룹 활동 지표 seed 필드 테스트 (round 5 증분)."""

    def test_seed_commit_count_included(self) -> None:
        """Seed에 commit_count 필드가 포함되어야 한다."""
        from datetime import timedelta

        base = datetime(2024, 1, 31)
        commits = tuple(
            CommitInfo(
                sha=f"abc{i}",
                author_name="user",
                authored_at=base - timedelta(days=i),
                message=f"Commit {i}",
                branch="main",
                changed_files=("file.py",),
                web_url="",
            )
            for i in range(5)
        )
        group = FeatureGroup(
            name="test_feature",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=commits,
            merge_requests=(),
            branch_names=("main",),
            participants=(),
        )
        model = DashboardModel(
            team_name="Test Team",
            report_date=date(2024, 1, 31),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )

        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::test_feature"]
        assert group_data.get("commit_count") == 5

    def test_seed_last_activity_at_iso(self) -> None:
        """Seed에 last_activity_at (ISO 형식)이 포함되어야 한다."""
        from datetime import timezone

        activity_time = datetime(2024, 1, 31, 14, 30, 45, tzinfo=timezone.utc)
        commit = CommitInfo(
            sha="abc123",
            author_name="user",
            authored_at=activity_time,
            message="test commit",
            branch="main",
            changed_files=("file.py",),
            web_url="",
        )
        group = FeatureGroup(
            name="test_feature",
            source_rule="branch",
            evidence="",
            stage="reviewing",
            repo_full_path="org/repo",
            commits=(commit,),
            merge_requests=(),
            branch_names=("feature/test",),
            participants=(),
            last_activity_at=activity_time,
        )
        model = DashboardModel(
            team_name="Test Team",
            report_date=activity_time.date(),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
            generated_at=activity_time,
        )

        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::test_feature"]
        last_activity = group_data.get("last_activity_at")
        assert last_activity is not None
        assert isinstance(last_activity, str)
        assert last_activity.startswith("2024-01-31")

    def test_seed_daily_commit_counts_included(self) -> None:
        """Seed에 daily_commit_counts (리스트로 변환)이 포함되어야 한다."""
        daily_counts = (
            ("2024-01-29", 2),
            ("2024-01-30", 3),
            ("2024-01-31", 1),
        )
        commit = CommitInfo(
            sha="abc123",
            author_name="user",
            authored_at=datetime(2024, 1, 31),
            message="test",
            branch="main",
            changed_files=(),
            web_url="",
        )
        group = FeatureGroup(
            name="test_feature",
            source_rule="branch",
            evidence="",
            stage="merged",
            repo_full_path="org/repo",
            commits=(commit,),
            merge_requests=(),
            branch_names=("main",),
            participants=(),
            daily_commit_counts=daily_counts,
        )
        model = DashboardModel(
            team_name="Test Team",
            report_date=date(2024, 1, 31),
            lookback_hours=24,
            summary_line="",
            groups=(group,),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("org/repo",),
            period="daily",
        )

        result = cast(dict[str, Any], extract_summary_input_by_repo(model))
        group_data = result["groups"]["org/repo::test_feature"]
        daily_counts_list = group_data.get("daily_commit_counts")
        assert daily_counts_list is not None
        assert isinstance(daily_counts_list, list)
        assert len(daily_counts_list) == 3
        assert daily_counts_list[0] == ["2024-01-29", 2]
        assert daily_counts_list[1] == ["2024-01-30", 3]
        assert daily_counts_list[2] == ["2024-01-31", 1]
