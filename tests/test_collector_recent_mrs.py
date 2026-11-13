"""최근 MR 수집 기능 테스트 (GitLab, GitHub, 직렬화)."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from pulse.collector.github import GitHub
from pulse.collector.gitlab import CollectionError, GitLab
from pulse.collector.http_client import GitLabClient, RateLimitStats
from pulse.models import RepoRef


@pytest.fixture
def sample_gitlab_repo() -> RepoRef:
    """GitLab 레포 참조."""
    return RepoRef(
        provider="gitlab",
        base_url="https://gitlab.example.com",
        namespace="sample-group",
        name="sample-repo",
        web_url="https://gitlab.example.com/org/repo",
    )


@pytest.fixture
def sample_github_repo() -> RepoRef:
    """GitHub 레포 참조."""
    return RepoRef(
        provider="github",
        base_url="https://github.com",
        namespace="owner",
        name="repo",
        web_url="https://github.com/owner/repo",
    )


@pytest.fixture
def mock_gitlab_client() -> Mock:
    """모킹된 GitLabClient."""
    client = Mock(spec=GitLabClient)
    client.stats = RateLimitStats()
    return client


class TestGitLabRecentMRCollection:
    """GitLab 최근 MR 수집 테스트."""

    def test_collect_recent_merge_requests_basic(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """_collect_recent_merge_requests는 최근 N개 MR을 수집한다."""
        # 최근 MR 3개 응답
        recent_mrs_data = [
            {
                "iid": 100,
                "title": "최근 MR 1",
                "state": "opened",
                "source_branch": "feature/x",
                "target_branch": "develop",
                "created_at": "2026-07-24T10:00:00Z",
                "updated_at": "2026-07-25T14:00:00Z",
                "merged_at": None,
                "author": {"username": "alice", "name": "Alice"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/100",
            },
            {
                "iid": 99,
                "title": "최근 MR 2 (머지됨)",
                "state": "merged",
                "source_branch": "develop",
                "target_branch": "devqa",
                "created_at": "2026-07-23T10:00:00Z",
                "updated_at": "2026-07-24T12:00:00Z",
                "merged_at": "2026-07-24T12:05:00Z",
                "author": {"username": "bob", "name": "Bob"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/99",
            },
            {
                "iid": 98,
                "title": "최근 MR 3",
                "state": "closed",
                "source_branch": "hotfix/y",
                "target_branch": "master",
                "created_at": "2026-07-22T10:00:00Z",
                "updated_at": "2026-07-23T09:00:00Z",
                "merged_at": None,
                "author": {"username": "charlie", "name": "Charlie"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/98",
            },
        ]
        mock_gitlab_client.list_recent_merge_requests.return_value = recent_mrs_data
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        recent_mrs = gitlab._collect_recent_merge_requests(
            project_id="test_id", limit=50, exclude_bot_authors=()
        )

        assert len(recent_mrs) == 3
        assert recent_mrs[0].iid == 100
        assert recent_mrs[0].state == "open"
        assert recent_mrs[1].iid == 99
        assert recent_mrs[1].state == "merged"
        assert recent_mrs[2].iid == 98
        assert recent_mrs[2].state == "closed"

    def test_collect_recent_merge_requests_respects_limit(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """list_recent_merge_requests 호출 시 limit 파라미터가 전달된다."""
        mock_gitlab_client.list_recent_merge_requests.return_value = []

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        gitlab._collect_recent_merge_requests(
            project_id="test_id", limit=25, exclude_bot_authors=()
        )

        # 호출 검증: limit=25가 전달되었는지 확인
        mock_gitlab_client.list_recent_merge_requests.assert_called_once_with("test_id", 25)

    def test_collect_recent_merge_requests_failure_returns_empty(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """호출 실패 시 빈 튜플 반환 + 경고 로그."""
        mock_gitlab_client.list_recent_merge_requests.side_effect = CollectionError("API 에러")

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        recent_mrs = gitlab._collect_recent_merge_requests(
            project_id="test_id", limit=50, exclude_bot_authors=()
        )

        # 빈 튜플 반환
        assert recent_mrs == ()

    def test_collect_recent_merge_requests_excludes_bots(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """봇 작성자(name 필드에 "bot-service" 포함)는 제외된다."""
        recent_mrs_data = [
            {
                "iid": 100,
                "title": "Human MR",
                "state": "opened",
                "source_branch": "feature/x",
                "target_branch": "develop",
                "created_at": "2026-07-24T10:00:00Z",
                "updated_at": "2026-07-25T14:00:00Z",
                "merged_at": None,
                "author": {"username": "alice", "name": "Alice"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/100",
            },
            {
                "iid": 99,
                "title": "Bot MR",
                "state": "merged",
                "source_branch": "develop",
                "target_branch": "devqa",
                "created_at": "2026-07-23T10:00:00Z",
                "updated_at": "2026-07-24T12:00:00Z",
                "merged_at": "2026-07-24T12:05:00Z",
                "author": {"username": "ci", "name": "bot-service automation"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/99",
            },
        ]
        mock_gitlab_client.list_recent_merge_requests.return_value = recent_mrs_data
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        recent_mrs = gitlab._collect_recent_merge_requests(
            project_id="test_id",
            limit=50,
            exclude_bot_authors=("bot-service",),
        )

        # bot-service는 제외, alice만 포함
        assert len(recent_mrs) == 1
        assert recent_mrs[0].iid == 100

    def test_repo_activity_with_recent_merge_requests(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """RepoActivity에 recent_merge_requests가 포함된다."""
        mock_gitlab_client.list_branches.return_value = [
            {
                "name": "develop",
                "commit": {"id": "abc123", "committed_date": "2026-07-25T10:00:00Z"},
            }
        ]
        mock_gitlab_client.list_commits.return_value = []
        mock_gitlab_client.get_commit_diff.return_value = []
        mock_gitlab_client.list_merge_requests.return_value = []
        mock_gitlab_client.list_open_merge_requests.return_value = []
        mock_gitlab_client.list_recent_merge_requests.return_value = [
            {
                "iid": 100,
                "title": "최근 MR",
                "state": "opened",
                "source_branch": "feature/x",
                "target_branch": "develop",
                "created_at": "2026-07-24T10:00:00Z",
                "updated_at": "2026-07-25T14:00:00Z",
                "merged_at": None,
                "author": {"username": "alice", "name": "Alice"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/100",
            }
        ]
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
        activity = gitlab.collect_repo_activity(
            sample_gitlab_repo,
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            recent_mr_limit=50,
        )

        assert activity.status == "ok"
        assert len(activity.recent_merge_requests) == 1
        assert activity.recent_merge_requests[0].iid == 100


class TestGitHubRecentMRCollection:
    """GitHub 최근 MR 수집 테스트 (추가 호출 0회)."""

    def test_github_recent_mrs_from_graphql_response(self, sample_github_repo: RepoRef) -> None:
        """GitHub는 GraphQL recentPRs 데이터를 재사용한다 (추가 호출 0회)."""
        # GraphQL 응답에 recentPRs가 포함됨
        graphql_response = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "recentPRs": {
                        "nodes": [
                            {
                                "number": 100,
                                "title": "최근 PR 1",
                                "state": "OPEN",
                                "isDraft": False,
                                "author": {"login": "alice"},
                                "createdAt": "2026-07-24T10:00:00Z",
                                "updatedAt": "2026-07-25T14:00:00Z",
                                "mergedAt": None,
                                "baseRefName": "develop",
                                "headRefName": "feature/x",
                                "body": None,
                                "reviews": {"nodes": []},
                            },
                            {
                                "number": 99,
                                "title": "최근 PR 2",
                                "state": "MERGED",
                                "isDraft": False,
                                "author": {"login": "bob"},
                                "createdAt": "2026-07-23T10:00:00Z",
                                "updatedAt": "2026-07-24T12:00:00Z",
                                "mergedAt": "2026-07-24T12:05:00Z",
                                "baseRefName": "devqa",
                                "headRefName": "develop",
                                "body": None,
                                "reviews": {"nodes": []},
                            },
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "defaultBranchRef": {"name": "main"},
                },
                "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
            }
        }

        mock_client = Mock()
        mock_client.query_repo_activity.return_value = graphql_response
        mock_client.query_branch_commits.return_value = {
            "data": {"repository": {"ref": {"target": {"history": {"nodes": []}}}}},
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_client.get_pull_request_reviews.return_value = []

        github = GitHub(token="test-token")
        github.client = mock_client

        now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(
            sample_github_repo,
            lookback_hours=24,
            exclude_bot_authors=(),
            snapshot_dir=None,
            stale_branch_days=7,
            now=now,
            recent_mr_limit=50,
        )

        # recent_merge_requests는 recentPRs에서 slice된 데이터
        assert len(recent_merge_requests) == 2
        assert recent_merge_requests[0].iid == 100
        assert recent_merge_requests[1].iid == 99
        # GraphQL 호출은 1회만 (추가 호출 0회)
        mock_client.query_repo_activity.assert_called_once()

    def test_github_recent_mrs_respects_limit(self, sample_github_repo: RepoRef) -> None:
        """GitHub recent_mrs는 limit을 준수한다."""
        graphql_response = {
            "data": {
                "repository": {
                    "refs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "openPRs": {"nodes": [], "pageInfo": {"hasNextPage": False}},
                    "recentPRs": {
                        "nodes": [
                            {
                                "number": 110,
                                "title": f"PR {i}",
                                "state": "OPEN",
                                "isDraft": False,
                                "author": {"login": "alice"},
                                "createdAt": "2026-07-25T10:00:00Z",
                                "updatedAt": "2026-07-25T14:00:00Z",
                                "mergedAt": None,
                                "baseRefName": "develop",
                                "headRefName": f"feature/{i}",
                                "body": None,
                                "reviews": {"nodes": []},
                            }
                            for i in range(100, 110)
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                    "defaultBranchRef": {"name": "main"},
                },
                "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
            }
        }

        mock_client = Mock()
        mock_client.query_repo_activity.return_value = graphql_response
        mock_client.query_branch_commits.return_value = {
            "data": {"repository": {"ref": {"target": {"history": {"nodes": []}}}}},
            "rateLimit": {"remaining": 4999, "resetAt": 9999999999},
        }
        mock_client.get_pull_request_reviews.return_value = []

        github = GitHub(token="test-token")
        github.client = mock_client

        now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
        (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            recent_merge_requests,
        ) = github._run_collection_pipeline(
            sample_github_repo,
            lookback_hours=24,
            exclude_bot_authors=(),
            snapshot_dir=None,
            stale_branch_days=7,
            now=now,
            recent_mr_limit=3,
        )

        # limit=3이므로 최대 3개까지만 포함
        assert len(recent_merge_requests) <= 3


class TestRepoActivityRecentMRSerialization:
    """RepoActivity recent_merge_requests 직렬화 테스트."""

    def test_recent_mrs_serialization_roundtrip(
        self, sample_gitlab_repo: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """RepoActivity를 직렬화/역직렬화하면 recent_merge_requests가 보존된다."""
        from pulse.models import activity_from_dict, activity_to_dict

        mock_gitlab_client.list_branches.return_value = []
        mock_gitlab_client.list_commits.return_value = []
        mock_gitlab_client.get_commit_diff.return_value = []
        mock_gitlab_client.list_merge_requests.return_value = []
        mock_gitlab_client.list_open_merge_requests.return_value = []
        mock_gitlab_client.list_recent_merge_requests.return_value = [
            {
                "iid": 50,
                "title": "최근 MR",
                "state": "opened",
                "source_branch": "feature/x",
                "target_branch": "develop",
                "created_at": "2026-07-24T10:00:00Z",
                "updated_at": "2026-07-25T14:00:00Z",
                "merged_at": None,
                "author": {"username": "alice", "name": "Alice"},
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://test/mr/50",
            }
        ]
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_gitlab_repo.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
        original = gitlab.collect_repo_activity(
            sample_gitlab_repo,
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            recent_mr_limit=50,
        )

        # 직렬화
        data = activity_to_dict(original)
        # 역직렬화
        restored = activity_from_dict(data)

        assert len(restored.recent_merge_requests) == 1
        assert restored.recent_merge_requests[0].iid == 50

    def test_recent_mrs_missing_in_old_raw_data(self, sample_gitlab_repo: RepoRef) -> None:
        """구버전 raw 데이터(recent_merge_requests 필드 없음)는 폴백으로 빈 튜플을 생성한다."""
        from typing import Any

        from pulse.models import activity_from_dict

        # 구버전 raw 데이터 (recent_merge_requests 필드 없음)
        old_raw: dict[str, Any] = {
            "repo": {
                "provider": "gitlab",
                "base_url": "https://gitlab.example.com",
                "namespace": "sample-group",
                "name": "sample-repo",
                "web_url": "https://gitlab.example.com/org/repo",
                "nickname": None,
            },
            "status": "ok",
            "failure_reason": None,
            "commits": [],
            "active_branches": [],
            "created_branches": [],
            "deleted_branches": [],
            "merge_requests": [],
            "stale_branches": [],
            "collected_at": "2026-07-25T15:00:00+00:00",
        }

        restored = activity_from_dict(old_raw)

        # recent_merge_requests 필드가 없으므로 기본값 빈 튜플
        assert restored.recent_merge_requests == ()
