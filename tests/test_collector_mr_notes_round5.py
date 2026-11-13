"""Collector MR notes 테스트: 기존 함수 동작 검증."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

from pulse.collector.github import _GITHUB_REPO_ACTIVITY_QUERY, GitHub
from pulse.collector.github_client import GitHubClient
from pulse.collector.gitlab import CollectionError, GitLab
from pulse.collector.http_client import GitLabClient, RateLimitStats
from pulse.models import MergeRequestInfo


def _make_gitlab_with_mock_client() -> tuple[GitLab, Mock]:
    """모킹된 client를 가진 GitLab 인스턴스를 만든다."""
    gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
    mock_client = Mock(spec=GitLabClient)
    mock_client.stats = RateLimitStats()
    gitlab.client = mock_client
    return gitlab, mock_client


def _gitlab_mr_data(iid: int) -> dict[str, Any]:
    """GitLab MR 목록 응답 항목 픽스처."""
    return {
        "iid": iid,
        "title": f"MR {iid}",
        "state": "merged",
        "author": {"username": f"user{iid}"},
        "created_at": "2026-07-21T09:00:00Z",
        "updated_at": "2026-07-21T10:00:00Z",
        "source_branch": f"feature/x{iid}",
        "target_branch": "develop",
        "labels": [],
        "web_url": f"http://gitlab.example.com/mr/{iid}",
        "source_project_id": 1,
        "target_project_id": 1,
        "description": "본문",
    }


class TestBuildMergeRequestInfo:
    """MergeRequestInfo 생성 테스트."""

    def test_build_merge_request_info_description_present(self) -> None:
        """description 필드 포함."""
        mr = MergeRequestInfo(
            iid=1,
            title="PR",
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
            description="Test description",
        )
        assert mr.description == "Test description"

    def test_merge_request_info_from_dict_legacy(self) -> None:
        """구 JSON 폴백 (description 없음)."""
        from pulse.models import _merge_request_from_dict

        data = {
            "iid": 1,
            "title": "PR",
            "state": "open",
            "is_draft": False,
            "labels": [],
            "source_branch": "feature/x",
            "target_branch": "main",
            "author_name": "user",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "merged_at": None,
            "is_external": False,
            "web_url": "",
        }
        mr = _merge_request_from_dict(data)
        assert mr.description is None


class TestCollectMrNotes:
    """GitLab MR notes 수집 동작 테스트."""

    def test_collect_mr_notes_parses_user_comments(self) -> None:
        """사용자 note를 ReviewEvent(kind=commented)로 변환한다."""
        gitlab, mock_client = _make_gitlab_with_mock_client()
        mock_client.get_merge_request_notes.return_value = [
            {
                "system": False,
                "author": {"username": "user1"},
                "created_at": "2026-07-20T10:00:00Z",
            }
        ]

        events = gitlab._collect_mr_notes("proj%2Fid", 1)

        assert len(events) == 1
        assert events[0].kind == "commented"
        assert events[0].actor_name == "user1"
        assert events[0].occurred_at == datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    def test_collect_mr_notes_filters_system_notes(self) -> None:
        """system note는 제외한다 (응답 필드 기반 클라이언트 측 필터)."""
        gitlab, mock_client = _make_gitlab_with_mock_client()
        mock_client.get_merge_request_notes.return_value = [
            {
                "system": True,
                "author": {"username": "user1"},
                "created_at": "2026-07-20T09:00:00Z",
            },
            {
                "system": False,
                "author": {"username": "user2"},
                "created_at": "2026-07-20T10:00:00Z",
            },
        ]

        events = gitlab._collect_mr_notes("proj%2Fid", 1)

        assert len(events) == 1
        assert events[0].actor_name == "user2"

    def test_collect_mr_notes_only_recent_mrs(self) -> None:
        """notes 조회는 lookback 내 MR 목록(list_merge_requests 결과)에 대해서만 발생한다."""
        gitlab, mock_client = _make_gitlab_with_mock_client()
        mock_client.list_merge_requests.return_value = [
            _gitlab_mr_data(1),
            _gitlab_mr_data(2),
        ]
        mock_client.get_merge_request_approvals.return_value = {"approved_by": []}
        mock_client.get_merge_request_notes.return_value = []

        now = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            "proj%2Fid", lookback_hours=24, exclude_bot_authors=(), now=now
        )

        assert len(mrs) == 2
        # 목록 조회는 since 파라미터와 함께 1회
        mock_client.list_merge_requests.assert_called_once()
        since_argument = mock_client.list_merge_requests.call_args[0][1]
        assert "T" in since_argument  # ISO 타임스탬프
        # notes 조회는 반환된 MR 2건에 대해서만
        assert mock_client.get_merge_request_notes.call_count == 2
        called_iids = {call.args[1] for call in mock_client.get_merge_request_notes.call_args_list}
        assert called_iids == {1, 2}

    def test_collect_mr_notes_failure_returns_empty(self) -> None:
        """notes 조회 실패 시 빈 튜플을 반환한다 (우아한 저하)."""
        gitlab, mock_client = _make_gitlab_with_mock_client()
        mock_client.get_merge_request_notes.side_effect = CollectionError("HTTP 500")

        events = gitlab._collect_mr_notes("proj%2Fid", 1)

        assert events == ()


class TestGitHubDescription:
    """GitHub PR description 매핑 테스트."""

    def test_github_pr_description_mapped(self) -> None:
        """GraphQL 쿼리가 body를 요청하고, body가 description으로 매핑된다."""
        # 쿼리 필드 가드: openPRs·recentPRs 두 블록 모두 body를 선택해야 한다
        assert _GITHUB_REPO_ACTIVITY_QUERY.count("body") >= 2

        github = GitHub(token="test-token")
        mock_client = Mock(spec=GitHubClient)
        mock_client.stats = RateLimitStats()
        mock_client.get_pull_request_reviews.return_value = []
        github.client = mock_client

        pr_data = {
            "number": 5,
            "title": "PR",
            "body": "PR 본문",
            "state": "OPEN",
            "isDraft": False,
            "author": {"login": "user1"},
            "createdAt": "2026-07-21T09:00:00Z",
            "updatedAt": "2026-07-21T10:00:00Z",
            "mergedAt": None,
            "baseRefName": "main",
            "headRefName": "feature/x",
        }

        mr = github._build_merge_request_info(pr_data, "owner", "repo", "https://gh.example/r")

        assert mr.description == "PR 본문"
        assert mr.iid == 5
