"""경고 신호의 repo_full_path 귀속 테스트 (신규 테스트 - test b)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.grouper import group_activities
from tests.conftest import (
    make_branch,
    make_commit,
    make_merge_request,
    make_repo_activity,
    make_repo_ref,
)

KST = ZoneInfo("Asia/Seoul")


def make_test_config() -> Config:
    """테스트용 Config."""
    return Config(
        team_name="Test Team",
        repos=(),
        lookback_hours=24,
        weekend_catchup=False,
        timezone_name="Asia/Seoul",
        output_dir=Path("unused-reports"),
        data_dir=Path("unused-data"),
        stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


class TestWarningSignalRepo:
    """경고 신호의 repo_full_path 귀속 테스트."""

    def test_stale_mr_includes_repo(self) -> None:
        """stale_mr 경고에 repo_full_path가 설정되어야 함."""
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        # 3일 이상 업데이트 없는 MR (threshold=3일)
        old_date = datetime(2026, 7, 12, 12, 0, tzinfo=KST)  # 4일 전

        repo = make_repo_ref()
        mr = make_merge_request(
            title="Stale MR",
            source_branch="feature/old",
            author_name="alice",
            created_at=old_date,
            updated_at=old_date,
            state="open",
        )
        activity = make_repo_activity(
            repo=repo,
            merge_requests=(mr,),
            commits=(),  # MR만 있고 커밋은 없음
        )

        config = make_test_config()

        # Act
        groups, warnings, new_work, unclassified_ratio = group_activities((activity,), config, now)

        # Assert
        stale_mr_warnings = [w for w in warnings if w.kind == "stale_mr"]

        # 최소 1개 stale_mr 경고가 생겨야 함
        assert len(stale_mr_warnings) >= 1, (
            f"Expected stale_mr warning, got {len(stale_mr_warnings)}"
        )

        # repo_full_path가 설정되어야 함
        stale_mr = stale_mr_warnings[0]
        assert stale_mr.repo_full_path is not None, "stale_mr warning should have repo_full_path"
        assert stale_mr.repo_full_path == "sample-group/sample-repo"

    def test_stale_branch_includes_repo(self) -> None:
        """stale_branch 경고에 repo_full_path가 설정되어야 함."""
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        # 7일 이상 push 없는 브랜치 (threshold=7일)
        old_date = datetime(2026, 7, 8, 12, 0, tzinfo=KST)  # 8일 전

        repo = make_repo_ref()
        stale_branch = make_branch(
            name="feature/old-branch",
            last_pushed_at=old_date,
        )
        activity = make_repo_activity(
            repo=repo,
            stale_branches=(stale_branch,),
            commits=(),  # stale_branch만 있음
        )

        config = make_test_config()

        # Act
        groups, warnings, new_work, unclassified_ratio = group_activities((activity,), config, now)

        # Assert
        stale_branch_warnings = [w for w in warnings if w.kind == "stale_branch"]

        # 최소 1개 stale_branch 경고가 생겨야 함
        assert len(stale_branch_warnings) >= 1, (
            f"Expected stale_branch warning, got {len(stale_branch_warnings)}"
        )

        # repo_full_path가 설정되어야 함
        stale_warning = stale_branch_warnings[0]
        assert stale_warning.repo_full_path is not None, (
            "stale_branch warning should have repo_full_path"
        )
        assert stale_warning.repo_full_path == "sample-group/sample-repo"

    def test_revert_hotfix_includes_repo(self) -> None:
        """revert/hotfix 경고에 repo_full_path가 설정되어야 함."""
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)

        repo = make_repo_ref()
        # revert 커밋 (메시지에 "revert"가 있어야 감지됨)
        revert_commit = make_commit(
            author_name="alice",
            message="Revert 'something went wrong'",
            branch="hotfix/revert",
        )
        # revert 커밋은 그룹에 포함되어야 경고 신호가 생성됨
        activity = make_repo_activity(
            repo=repo,
            commits=(revert_commit,),
            merge_requests=(),
        )

        config = make_test_config()

        # Act
        groups, warnings, new_work, unclassified_ratio = group_activities((activity,), config, now)

        # Assert
        revert_warnings = [w for w in warnings if w.kind == "revert_commit"]

        # 최소 1개 revert 경고가 생겨야 함
        assert len(revert_warnings) >= 1, (
            f"Expected revert_commit warning, got {len(revert_warnings)}"
        )

        # repo_full_path가 설정되어야 함
        revert_warning = revert_warnings[0]
        assert revert_warning.repo_full_path is not None, (
            "revert_commit warning should have repo_full_path"
        )
        assert revert_warning.repo_full_path == "sample-group/sample-repo"
