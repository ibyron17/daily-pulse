"""레포별 그룹 범위 지정 테스트 (신규 테스트 - test a)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.grouper import group_activities
from tests.conftest import (
    make_commit,
    make_repo_activity,
    make_repo_ref,
)

KST = ZoneInfo("Asia/Seoul")


def make_test_config(
    grouping_hints: GroupingHints | None = None,
) -> Config:
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
        grouping_hints=grouping_hints or GroupingHints(),
    )


class TestRepoScopedGroups:
    """레포별 그룹 범위 지정 테스트."""

    def test_same_group_name_different_repos_separate(self) -> None:
        """같은 이름 그룹이 다른 레포에서 생기면 분리되어야 함 (repo_full_path 기반)."""
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)

        # 레포 1: sample-group/sample-ui
        repo1 = make_repo_ref(
            namespace="sample-group",
            name="sample-ui",
        )
        # develop 브랜치 (branch-name이 됨)
        commit1 = make_commit(
            author_name="alice",
            branch="develop",
            message="some change",
        )
        activity1 = make_repo_activity(
            repo=repo1,
            commits=(commit1,),
        )

        # 레포 2: backend/api
        repo2 = make_repo_ref(
            namespace="backend",
            name="api",
        )
        # develop 브랜치 (branch-name이 됨, 다른 레포)
        commit2 = make_commit(
            author_name="bob",
            branch="develop",
            message="another change",
        )
        activity2 = make_repo_activity(
            repo=repo2,
            commits=(commit2,),
        )

        config = make_test_config()

        # Act
        groups, _, _, _ = group_activities((activity1, activity2), config, now)

        # Assert
        # develop 그룹을 찾기
        develop_groups = [g for g in groups if g.name == "develop"]

        # 정확히 2개 develop 그룹이 생겨야 함 (각 레포별로 분리)
        assert len(develop_groups) == 2, (
            f"Expected exactly 2 develop groups, got {len(develop_groups)}"
        )

        # repo_full_path가 다른지 확인 (같은 이름이라도 다른 레포면 분리)
        repo_paths = {g.repo_full_path for g in develop_groups}
        assert repo_paths == {"sample-group/sample-ui", "backend/api"}, (
            f"Expected groups from both repos, got {repo_paths}"
        )
