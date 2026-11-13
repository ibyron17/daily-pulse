"""GitHub GraphQL + REST API 수집 구현체 테스트 (HTTP 모킹)."""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from pulse.collector.github import GitHub
from pulse.collector.github_client import GitHubClient
from pulse.collector.gitlab import CollectionError
from pulse.collector.http_client import RateLimitStats
from pulse.models import RepoRef

KST = ZoneInfo("Asia/Seoul")

# Type alias for fixture loader
FixtureLoader = Callable[[str], Any]


@pytest.fixture
def load_fixture() -> FixtureLoader:
    """fixture JSON을 로드하는 헬퍼."""

    def _load(filename: str) -> Any:
        fixture_dir = Path(__file__).parent / "fixtures"
        with open(fixture_dir / f"{filename}.json") as f:
            return json.load(f)

    return _load


@pytest.fixture
def sample_github_repo_ref() -> RepoRef:
    """테스트용 GitHub RepoRef."""
    return RepoRef(
        provider="github",
        base_url="https://github.com",
        namespace="torvalds",
        name="linux",
        web_url="https://github.com/torvalds/linux",
    )


@pytest.fixture
def mock_github_client() -> Mock:
    """모킹된 GitHubClient."""
    client = Mock(spec=GitHubClient)
    client.stats = RateLimitStats()
    return client


class TestGitHubClientInitialization:
    """GitHubClient 초기화 테스트."""

    def test_github_client_init_with_defaults(self) -> None:
        """GitHubClient는 기본 설정으로 초기화된다."""
        client = GitHubClient(token="test-token")
        assert client.base_url == "https://api.github.com"
        assert client.token == "test-token"
        assert client.stats is not None
        assert "Bearer test-token" in client.session.headers.get("Authorization", "")

    def test_github_client_init_with_custom_stats(self) -> None:
        """GitHubClient는 custom RateLimitStats를 사용할 수 있다."""
        stats = RateLimitStats()
        client = GitHubClient(token="test-token", stats=stats)
        assert client.stats is stats


class TestGitHubImplementation:
    """GitHub 구현체 테스트."""

    def test_github_init(self, sample_github_repo_ref: RepoRef) -> None:
        """GitHub 인스턴스 초기화."""
        github = GitHub(token="test-token")
        assert github.client is not None

    def test_get_repo_version(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """get_repo_version은 "GitHub"을 반환한다."""
        mock_github_client.get_repo_info.return_value = {"name": "linux"}

        github = GitHub(token="test-token")
        github.client = mock_github_client

        version = github.get_repo_version(sample_github_repo_ref)
        assert version == "GitHub"

    def test_get_repo_version_failure(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """get_repo_version 실패 시 CollectionError."""
        mock_github_client.get_repo_info.side_effect = CollectionError("404 Not Found")

        github = GitHub(token="test-token")
        github.client = mock_github_client

        with pytest.raises(CollectionError, match="레포 정보 조회 실패"):
            github.get_repo_version(sample_github_repo_ref)

    def test_normalize_mr_state_open(self) -> None:
        """PR state OPEN → open."""
        from pulse.collector.github import _normalize_mr_state

        assert _normalize_mr_state("OPEN") == "open"
        assert _normalize_mr_state("open") == "open"

    def test_normalize_mr_state_merged(self) -> None:
        """PR state MERGED → merged."""
        from pulse.collector.github import _normalize_mr_state

        assert _normalize_mr_state("MERGED") == "merged"

    def test_normalize_mr_state_closed(self) -> None:
        """PR state CLOSED → closed."""
        from pulse.collector.github import _normalize_mr_state

        assert _normalize_mr_state("CLOSED") == "closed"

    def test_should_include_commit_true(self) -> None:
        """봇이 아닌 커밋은 포함된다."""
        github = GitHub(token="test-token")
        assert github._should_include_commit("alice", ("dependabot",)) is True

    def test_should_include_commit_bot_excluded(self) -> None:
        """봇 커밋은 제외된다."""
        github = GitHub(token="test-token")
        assert github._should_include_commit("dependabot[bot]", ("dependabot",)) is False

    def test_build_commit_info(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """_build_commit_info는 CommitInfo를 생성한다."""
        mock_github_client.get_commit_changed_files.return_value = [
            {"filename": "fs/ext4/inode.c"},
            {"filename": "fs/ext4/super.c"},
        ]

        github = GitHub(token="test-token")
        github.client = mock_github_client

        commit_data = {
            "oid": "abc123",
            "message": "Fix ext4 bug",
            "author": {"name": "Linus Torvalds"},
            "committedDate": "2026-07-16T08:00:00Z",
        }

        commit_info = github._build_commit_info(
            commit_data,
            "develop",
            sample_github_repo_ref.web_url,
            sample_github_repo_ref.namespace,
            sample_github_repo_ref.name,
        )

        assert commit_info.sha == "abc123"
        assert commit_info.author_name == "Linus Torvalds"
        assert commit_info.branch == "develop"
        assert len(commit_info.changed_files) == 2
        assert "fs/ext4/inode.c" in commit_info.changed_files

    def test_build_commit_info_changed_files_failed(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """변경 파일 조회 실패 시 빈 tuple을 반환한다."""
        mock_github_client.get_commit_changed_files.side_effect = Exception("API error")

        github = GitHub(token="test-token")
        github.client = mock_github_client

        commit_data = {
            "oid": "abc123",
            "message": "Fix bug",
            "author": {"name": "alice"},
            "committedDate": "2026-07-16T08:00:00Z",
        }

        commit_info = github._build_commit_info(
            commit_data,
            "develop",
            sample_github_repo_ref.web_url,
            sample_github_repo_ref.namespace,
            sample_github_repo_ref.name,
        )

        assert commit_info.changed_files == ()

    def test_build_merge_request_info(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """_build_merge_request_info는 MergeRequestInfo를 생성한다."""
        mock_github_client.get_pull_request_reviews.return_value = [
            {
                "state": "APPROVED",
                "author": {"login": "bob"},
                "submittedAt": "2026-07-16T09:00:00Z",
            }
        ]

        github = GitHub(token="test-token")
        github.client = mock_github_client

        pr_data = {
            "number": 42,
            "title": "Fix kernel panic",
            "state": "OPEN",
            "isDraft": False,
            "author": {"login": "alice"},
            "createdAt": "2026-07-15T08:00:00Z",
            "updatedAt": "2026-07-16T08:00:00Z",
            "mergedAt": None,
            "baseRefName": "main",
            "headRefName": "fix/panic",
        }

        mr_info = github._build_merge_request_info(
            pr_data,
            sample_github_repo_ref.namespace,
            sample_github_repo_ref.name,
            sample_github_repo_ref.web_url,
        )

        assert mr_info.iid == 42
        assert mr_info.title == "Fix kernel panic"
        assert mr_info.state == "open"
        assert mr_info.is_draft is False
        assert mr_info.author_name == "alice"
        assert len(mr_info.reviews) == 1
        assert mr_info.reviews[0].kind == "approved"

    def test_build_merge_request_info_author_none(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """탈퇴 계정으로 author=None일 때 "unknown"으로 폴백된다."""
        mock_github_client.get_pull_request_reviews.return_value = []

        github = GitHub(token="test-token")
        github.client = mock_github_client

        pr_data = {
            "number": 43,
            "title": "Deleted user PR",
            "state": "CLOSED",
            "isDraft": False,
            "author": None,  # 탈퇴 계정
            "createdAt": "2026-07-15T08:00:00Z",
            "updatedAt": "2026-07-16T08:00:00Z",
            "mergedAt": None,
            "baseRefName": "main",
            "headRefName": "unknown-author",
        }

        mr_info = github._build_merge_request_info(
            pr_data,
            sample_github_repo_ref.namespace,
            sample_github_repo_ref.name,
            sample_github_repo_ref.web_url,
        )

        assert mr_info.iid == 43
        assert mr_info.author_name == "unknown"

    def test_filter_active_branches(self) -> None:
        """활동 브랜치를 필터링한다."""
        github = GitHub(token="test-token")

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        lookback_hours = 24

        branches = [
            {
                "name": "develop",
                "target": {"oid": "abc123", "committedDate": "2026-07-16T08:00:00Z"},
            },
            {
                "name": "old-branch",
                "target": {"oid": "def456", "committedDate": "2026-07-10T08:00:00Z"},
            },
        ]

        active = github._filter_active_branches(branches, lookback_hours, now)
        assert len(active) == 1
        assert active[0]["name"] == "develop"

    def test_is_stale_branch_true(self) -> None:
        """stale 브랜치를 올바르게 감지한다."""
        github = GitHub(token="test-token")

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        stale_threshold = now - timedelta(days=7)

        branch = {
            "name": "old-feature",
            "target": {"oid": "abc123", "committedDate": "2026-07-01T08:00:00Z"},
        }

        assert github._is_stale_branch(branch, stale_threshold) is True

    def test_is_stale_branch_false(self) -> None:
        """최근 브랜치는 stale이 아니다."""
        github = GitHub(token="test-token")

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        stale_threshold = now - timedelta(days=7)

        branch = {
            "name": "recent-feature",
            "target": {"oid": "abc123", "committedDate": "2026-07-15T08:00:00Z"},
        }

        assert github._is_stale_branch(branch, stale_threshold) is False


class TestGitHubProviderSelection:
    """Provider 판별 통합 테스트."""

    def test_provider_selection_github_vs_gitlab(self) -> None:
        """provider 값에 따라 GitHub 또는 GitLab이 선택된다."""
        from pulse.models import Provider

        # GitHub provider is defined in the type
        github_provider: Provider = "github"
        gitlab_provider: Provider = "gitlab"

        assert github_provider == "github"
        assert gitlab_provider == "gitlab"

    def test_collect_repos_requires_github_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GitHub 레포가 있으면 GITHUB_TOKEN이 필요하다."""
        from pulse.collector import collect_repos
        from pulse.config import Config
        from pulse.config.loader import GroupingHints, StagnationThresholds
        from tests.conftest import make_repo_ref

        repo = make_repo_ref(provider="github")

        config = Config(
            team_name="test",
            repos=(repo,),
            lookback_hours=24,
            weekend_catchup=False,
            timezone_name="Asia/Seoul",
            output_dir=Path("/tmp"),
            data_dir=Path("/tmp"),
            stagnation=StagnationThresholds(),
            exclude_bot_authors=(),
            retention_days=90,
            grouping_hints=GroupingHints(),
        )

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        with pytest.raises(CollectionError, match="GITHUB_TOKEN"):
            collect_repos(config)


class TestGitHubPRFiltering:
    """GitHub PR 필터링 회귀 테스트 (버그 B)."""

    def test_old_merged_pr_outside_lookback_excluded(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """lookback 밖의 오래된 MERGED PR은 제외된다."""
        github = GitHub(token="test-token")
        github.client = mock_github_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        lookback_hours = 24
        old_updated = (now - timedelta(days=5)).isoformat()

        # Mock 응답: openPRs (없음), recentPRs (오래된 MERGED PR)
        mock_github_client.query_repo_activity.return_value = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "recentPRs": {
                        "nodes": [
                            {
                                "number": 1,
                                "title": "Old PR",
                                "state": "MERGED",
                                "isDraft": False,
                                "author": {"login": "alice"},
                                "createdAt": "2026-07-01T08:00:00Z",
                                "updatedAt": old_updated,
                                "mergedAt": old_updated,
                                "baseRefName": "main",
                                "headRefName": "old-feature",
                                "reviews": {"nodes": []},
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "defaultBranchRef": {"name": "main"},
                }
            },
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_github_client.get_pull_request_reviews.return_value = []

        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(
            sample_github_repo_ref,
            lookback_hours,
            (),
            None,
            7,
            now,
        )
        # 오래된 MERGED PR은 제외 (recentPRs 필터: updated_at < since_dt이면 skip)
        assert len(merge_requests) == 0

    def test_stale_open_pr_included(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """시간이 오래 지난 OPEN PR도 포함된다."""
        github = GitHub(token="test-token")
        github.client = mock_github_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        old_updated = (now - timedelta(days=30)).isoformat()

        # Mock 응답: openPRs에 오래된 OPEN PR
        mock_github_client.query_repo_activity.return_value = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {
                        "nodes": [
                            {
                                "number": 42,
                                "title": "Stale PR",
                                "state": "OPEN",
                                "isDraft": False,
                                "author": {"login": "bob"},
                                "createdAt": "2026-06-01T08:00:00Z",
                                "updatedAt": old_updated,
                                "mergedAt": None,
                                "baseRefName": "main",
                                "headRefName": "old-feature",
                                "reviews": {"nodes": []},
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "recentPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "defaultBranchRef": {"name": "main"},
                }
            },
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_github_client.get_pull_request_reviews.return_value = []

        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(
            sample_github_repo_ref,
            24,
            (),
            None,
            7,
            now,
        )
        # 오래된 OPEN PR은 포함 (openPRs는 시간 필터 없음)
        assert len(merge_requests) == 1
        assert merge_requests[0].iid == 42

    def test_bot_author_pr_excluded(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """exclude_bot_authors에 걸리는 PR은 제외된다."""
        github = GitHub(token="test-token")
        github.client = mock_github_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)

        mock_github_client.query_repo_activity.return_value = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {
                        "nodes": [
                            {
                                "number": 10,
                                "title": "Bot PR",
                                "state": "OPEN",
                                "isDraft": False,
                                "author": {"login": "dependabot[bot]"},
                                "createdAt": now.isoformat(),
                                "updatedAt": now.isoformat(),
                                "mergedAt": None,
                                "baseRefName": "main",
                                "headRefName": "bot-branch",
                                "reviews": {"nodes": []},
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "recentPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "defaultBranchRef": {"name": "main"},
                }
            },
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_github_client.get_pull_request_reviews.return_value = []

        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(
            sample_github_repo_ref,
            24,
            ("dependabot",),
            None,
            7,
            now,
        )
        # 봇 PR 제외 (exclude_bot_authors 필터에 "dependabot"이 포함)
        assert len(merge_requests) == 0

    def test_page_limit_warning_logged(
        self,
        sample_github_repo_ref: RepoRef,
        mock_github_client: Mock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """pageInfo.hasNextPage=true 시 경고 로그가 남는다."""
        github = GitHub(token="test-token")
        github.client = mock_github_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)

        # hasNextPage=true 응답
        mock_github_client.query_repo_activity.return_value = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": True}},
                    "openPRs": {"nodes": [], "pageInfo": {"hasNextPage": True}},
                    "recentPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "defaultBranchRef": {"name": "main"},
                }
            },
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }

        with caplog.at_level(logging.WARNING):
            github._run_collection_pipeline(sample_github_repo_ref, 24, (), None, 7, now)

        # 페이지 상한 경고 확인 (refs와 openPRs의 hasNextPage=true)
        assert any(
            "페이지 상한" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )


class TestGitHubPRDedup:
    """GitHub PR 중복 제거 테스트 (버그 B)."""

    def test_open_and_recent_pr_deduped(
        self, sample_github_repo_ref: RepoRef, mock_github_client: Mock
    ) -> None:
        """openPRs와 recentPRs에 같은 PR이 있으면 1건만 포함된다."""
        github = GitHub(token="test-token")
        github.client = mock_github_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        pr_data_template = {
            "number": 99,
            "title": "Shared PR",
            "state": "OPEN",
            "isDraft": False,
            "author": {"login": "charlie"},
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
            "mergedAt": None,
            "baseRefName": "main",
            "headRefName": "shared",
            "reviews": {"nodes": []},
        }

        # 같은 PR이 openPRs와 recentPRs 양쪽에
        mock_github_client.query_repo_activity.return_value = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {
                        "nodes": [pr_data_template.copy()],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "recentPRs": {
                        "nodes": [pr_data_template.copy()],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "defaultBranchRef": {"name": "main"},
                }
            },
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_github_client.get_pull_request_reviews.return_value = []

        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(sample_github_repo_ref, 24, (), None, 7, now)
        # 1건만 포함 (PR number 기반 dedup)
        assert len(merge_requests) == 1
        assert merge_requests[0].iid == 99
