"""GitLab REST API v4 수집 구현체 테스트 (HTTP 모킹)."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from pulse.collector.gitlab import CollectionError, GitLab
from pulse.collector.http_client import _MAX_PAGES, GitLabClient, RateLimitStats
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
def sample_repo_ref() -> RepoRef:
    """테스트용 RepoRef."""
    return RepoRef(
        provider="gitlab",
        base_url="https://gitlab.example.com",
        namespace="sample-group",
        name="sample-repo",
        web_url="https://gitlab.example.com/sample-group/sample-repo",
    )


@pytest.fixture
def mock_gitlab_client() -> Mock:
    """모킹된 GitLabClient."""
    client = Mock(spec=GitLabClient)
    client.stats = RateLimitStats()
    return client


class TestGitLabClientInitialization:
    """GitLabClient 초기화 테스트."""

    def test_gitlab_client_init_with_defaults(self) -> None:
        """GitLabClient는 기본 설정으로 초기화된다."""
        client = GitLabClient(base_url="https://gitlab.example.com", token="test-token")
        assert client.base_url == "https://gitlab.example.com"
        assert client.token == "test-token"
        assert client.stats is not None


class TestGitLabImplementation:
    """GitLab 구현체 테스트."""

    def test_gitlab_init(self, sample_repo_ref: RepoRef) -> None:
        """GitLab 인스턴스 초기화."""
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        assert gitlab.base_url == sample_repo_ref.base_url
        assert gitlab.client is not None

    def test_get_repo_version(self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock) -> None:
        """get_repo_version은 GitLab 버전을 조회한다."""
        mock_gitlab_client.get_version.return_value = "16.7.0"

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        version = gitlab.get_repo_version(sample_repo_ref)
        assert version == "16.7.0"
        mock_gitlab_client.get_version.assert_called_once()

    def test_get_repo_version_failure(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """get_repo_version 실패 시 CollectionError."""
        mock_gitlab_client.get_version.side_effect = CollectionError("Connection failed")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        with pytest.raises(CollectionError, match="버전 확인 실패"):
            gitlab.get_repo_version(sample_repo_ref)

    def test_get_project_id(self, sample_repo_ref: RepoRef) -> None:
        """_get_project_id는 레포 경로를 URL-encoded 프로젝트 ID로 변환한다."""
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        project_id = gitlab._get_project_id(sample_repo_ref)
        # sample-group/sample-repo는 URL-encoded될 때 %2F로 슬래시 변환
        assert "sample-group" in project_id
        assert "sample-repo" in project_id

    def test_filter_active_branches_lookback_range(
        self, sample_repo_ref: RepoRef, load_fixture: FixtureLoader
    ) -> None:
        """_filter_active_branches는 lookback 시간 내의 브랜치만 선별한다."""
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        branches = load_fixture("gitlab_branches")

        # lookback_hours=24, fixture 최신 시각(2026-07-15 09:00)을 포함하려면
        # now는 2026-07-16 09:00 이후여야 함 (24시간 이내 조건: committed_dt >= (now - 24h))
        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        active = gitlab._filter_active_branches(branches, lookback_hours=24, now=now)

        # 두 개의 활동 브랜치만 포함되어야 함
        assert len(active) > 0
        assert any(b["name"] == "develop" for b in active)

    def test_collect_commits_for_branch(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """_collect_commits_for_branch는 커밋을 수집한다."""
        mock_gitlab_client.list_commits.return_value = load_fixture("gitlab_commits")
        mock_gitlab_client.get_commit_diff.return_value = load_fixture("gitlab_commit_diff")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        commits = gitlab._collect_commits_for_branch(
            project_id="sample-group%2Fsample-repo",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=("bot-service",),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
        )

        # 봇 제외, 2개 커밋만 반환
        assert len(commits) == 2
        assert commits[0].sha == "abc123def456"
        assert commits[0].author_name == "hong-gildong"
        assert len(commits[0].changed_files) > 0

    def test_collect_commits_excludes_bot_authors(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """_collect_commits_for_branch는 exclude_bot_authors 필터를 적용한다."""
        mock_gitlab_client.list_commits.return_value = load_fixture("gitlab_commits")
        mock_gitlab_client.get_commit_diff.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        commits = gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=("bot-service", "ci-bot"),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
        )

        # bot-service 커밋은 제외되어야 함
        assert not any(c.author_name == "bot-service" for c in commits)

    def test_collect_merge_requests(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """_collect_merge_requests는 MR을 수집한다."""
        mock_gitlab_client.list_merge_requests.return_value = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )

        assert len(mrs) == 3
        assert mrs[0].iid == 42
        assert mrs[0].state == "open"
        assert mrs[1].state == "merged"
        assert mrs[2].state == "closed"

    def test_collect_merge_requests_normalizes_state(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """_collect_merge_requests는 MR state를 정규화한다."""
        mock_gitlab_client.list_merge_requests.return_value = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )

        # "opened" → "open" 정규화 확인
        assert mrs[0].state == "open"
        assert mrs[1].state == "merged"
        assert mrs[2].state == "closed"

    def test_collect_merge_requests_includes_reviews(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """_collect_merge_requests는 MR 리뷰를 포함한다."""
        mock_gitlab_client.list_merge_requests.return_value = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )

        # 첫 번째 MR의 리뷰 확인 (system=True인 것 제외)
        reviews = mrs[0].reviews
        assert len(reviews) >= 2
        assert any(r.kind == "commented" for r in reviews)

    def test_collect_repo_activity_success(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """collect_repo_activity는 레포 활동을 수집한다."""
        mock_gitlab_client.list_branches.return_value = load_fixture("gitlab_branches")
        mock_gitlab_client.list_commits.return_value = load_fixture("gitlab_commits")
        mock_gitlab_client.get_commit_diff.return_value = load_fixture("gitlab_commit_diff")
        mock_gitlab_client.list_merge_requests.return_value = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.list_open_merge_requests.return_value = []
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")
        mock_gitlab_client.list_recent_merge_requests.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        # fixture 최신 시각(2026-07-15 09:00)을 포함하려면
        # now는 2026-07-16 09:00 이후여야 함
        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        activity = gitlab.collect_repo_activity(
            repo=sample_repo_ref,
            lookback_hours=24,
            exclude_bot_authors=("bot-service",),
            snapshot_dir=None,
            now=now,
        )

        assert activity.status == "ok"
        assert activity.failure_reason is None
        assert activity.repo == sample_repo_ref
        assert len(activity.commits) > 0
        assert len(activity.merge_requests) > 0
        assert len(activity.active_branches) > 0

    def test_collect_repo_activity_failure_returns_failed_status(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """collect_repo_activity는 실패 시 status='failed'로 반환한다."""
        mock_gitlab_client.list_branches.side_effect = CollectionError("API error")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        activity = gitlab.collect_repo_activity(
            repo=sample_repo_ref,
            lookback_hours=24,
            exclude_bot_authors=(),
            snapshot_dir=None,
            now=now,
        )

        assert activity.status == "failed"
        assert activity.failure_reason is not None
        assert activity.commits == ()
        assert activity.merge_requests == ()

    def test_collect_repo_activity_with_snapshot_dir(
        self,
        sample_repo_ref: RepoRef,
        mock_gitlab_client: Mock,
        load_fixture: FixtureLoader,
        tmp_path: Path,
    ) -> None:
        """collect_repo_activity는 snapshot_dir이 지정되면 스냅샷을 저장한다."""
        mock_gitlab_client.list_branches.return_value = load_fixture("gitlab_branches")
        mock_gitlab_client.list_commits.return_value = []
        mock_gitlab_client.list_merge_requests.return_value = []
        mock_gitlab_client.list_open_merge_requests.return_value = []
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []
        mock_gitlab_client.list_recent_merge_requests.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        snapshot_dir = tmp_path / "snapshots"

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        activity = gitlab.collect_repo_activity(
            repo=sample_repo_ref,
            lookback_hours=24,
            exclude_bot_authors=(),
            snapshot_dir=snapshot_dir,
            now=now,
        )

        assert activity.status == "ok"
        # 스냅샷 파일이 생성되었는지 확인
        snapshot_file = snapshot_dir / "2026-07-16" / f"{sample_repo_ref.slug}.json"
        assert snapshot_file.exists()


class TestStaleBranches:
    """정체 브랜치 수집 테스트."""

    def test_stale_branches_excludes_merged(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """merged=true 브랜치는 제외된다."""
        branches_data = [
            {
                "name": "feature/old-merged",
                "merged": True,
                "default": False,
                "commit": {"id": "xyz", "committed_date": "2026-06-01T00:00:00Z"},
                "web_url": "http://example.com/branch1",
            },
            {
                "name": "feature/old-active",
                "merged": False,
                "default": False,
                "commit": {"id": "abc", "committed_date": "2026-06-01T00:00:00Z"},
                "web_url": "http://example.com/branch2",
            },
        ]
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)

        stale = gitlab._collect_stale_branches(
            branches_data, stale_branch_days=10, now=now, repo_web_url="http://example.com/repo"
        )

        # merged=true인 브랜치는 제외
        assert len(stale) == 1
        assert stale[0].name == "feature/old-active"

    def test_stale_branches_excludes_default(self, sample_repo_ref: RepoRef) -> None:
        """default=true 브랜치는 제외된다."""
        branches_data = [
            {
                "name": "main",
                "merged": False,
                "default": True,
                "commit": {"id": "xyz", "committed_date": "2026-06-01T00:00:00Z"},
                "web_url": "http://example.com/main",
            },
            {
                "name": "develop",
                "merged": False,
                "default": False,
                "commit": {"id": "abc", "committed_date": "2026-06-01T00:00:00Z"},
                "web_url": "http://example.com/develop",
            },
        ]
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)

        stale = gitlab._collect_stale_branches(
            branches_data, stale_branch_days=10, now=now, repo_web_url="http://example.com/repo"
        )

        # default=true인 브랜치는 제외
        assert len(stale) == 1
        assert stale[0].name == "develop"

    def test_stale_branches_boundary_exact_days(self) -> None:
        """stale_branch_days 경계값: 10일 이상 경과."""
        branches_data = [
            {
                "name": "feature/over",
                "merged": False,
                "default": False,
                # 10일 초과 (포함)
                "commit": {"id": "abc", "committed_date": "2026-07-05T23:59:59Z"},
                "web_url": "http://example.com/over",
            },
            {
                "name": "feature/exactly",
                "merged": False,
                "default": False,
                # 정확히 10일 (미포함: 미만이 아님)
                "commit": {"id": "def", "committed_date": "2026-07-06T00:00:00Z"},
                "web_url": "http://example.com/exactly",
            },
        ]
        gitlab = GitLab(base_url="http://test", token="test")
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)

        stale = gitlab._collect_stale_branches(
            branches_data, stale_branch_days=10, now=now, repo_web_url="http://example.com/repo"
        )

        # 10일을 초과한 것만 포함
        assert len(stale) == 1
        assert stale[0].name == "feature/over"

    def test_stale_branches_branch_info_fields(self) -> None:
        """BranchInfo 필드가 정확히 설정된다."""
        branches_data = [
            {
                "name": "feature/stale",
                "merged": False,
                "default": False,
                "commit": {"id": "abc123", "committed_date": "2026-06-01T10:30:45Z"},
                "web_url": "http://example.com/feature/stale",
            }
        ]
        gitlab = GitLab(base_url="http://test", token="test")
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)

        stale = gitlab._collect_stale_branches(
            branches_data, stale_branch_days=10, now=now, repo_web_url="http://example.com/repo"
        )

        assert len(stale) == 1
        br = stale[0]
        assert br.name == "feature/stale"
        assert br.last_commit_sha == "abc123"
        assert br.web_url == "http://example.com/feature/stale"
        assert br.last_pushed_at == datetime(2026, 6, 1, 10, 30, 45, tzinfo=timezone.utc)

    def test_stale_branches_less_than_threshold(self) -> None:
        """stale_branch_days 미만의 브랜치는 포함되지 않는다."""
        branches_data = [
            {
                "name": "feature/recent",
                "merged": False,
                "default": False,
                "commit": {"id": "abc", "committed_date": "2026-07-10T00:00:00Z"},
                "web_url": "http://example.com/recent",
            }
        ]
        gitlab = GitLab(base_url="http://test", token="test")
        now = datetime(2026, 7, 16, tzinfo=timezone.utc)

        stale = gitlab._collect_stale_branches(
            branches_data, stale_branch_days=10, now=now, repo_web_url="http://example.com/repo"
        )

        # 6일만 지났으므로 포함 안 됨
        assert len(stale) == 0


class TestOpenMRMerging:
    """오픈 MR 병합 (윈도+전체) 테스트."""

    def test_collect_all_open_mrs_uses_open_state_query(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """전체 오픈 MR 조회는 open 상태 전용 쿼리를 쓴다 (전체 MR 조회 금지)."""
        # Arrange
        mock_gitlab_client.list_open_merge_requests.return_value = []
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        # Act
        mrs = gitlab._collect_all_open_mrs("test_id", ())

        # Assert — state=all인 윈도 쿼리(list_merge_requests)를 재사용하면 안 된다
        assert mrs == ()
        mock_gitlab_client.list_open_merge_requests.assert_called_once_with("test_id")
        mock_gitlab_client.list_merge_requests.assert_not_called()

    def test_merge_window_and_all_mrs_dedup_same_iid(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """같은 iid가 윈도와 전체 조회에 있으면 1건만 포함 (윈도 우선)."""
        # 윈도 조회: MR 42 (리뷰 있음)
        window_mrs_data = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.list_merge_requests.return_value = window_mrs_data
        mock_gitlab_client.list_open_merge_requests.return_value = window_mrs_data
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        window_mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )
        merged = gitlab._merge_window_and_all_mrs(
            window_mrs, project_id="test_id", exclude_bot_authors=()
        )

        # 전체 조회는 윈도와 같으므로, 최종은 3개 (중복 없음)
        assert len(merged) == 3
        iids = [mr.iid for mr in merged]
        assert len(iids) == len(set(iids))  # 모두 unique

    def test_merge_window_and_all_mrs_includes_outside_window(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """윈도 밖의 오픈 MR이 최종 merge_requests에 포함된다."""
        # 윈도 조회: MR 1, 2
        window_data = [
            {
                "iid": 1,
                "title": "Window MR 1",
                "state": "opened",
                "author": {"username": "user1"},
                "source_branch": "feature/1",
                "target_branch": "main",
                "created_at": "2026-07-15T00:00:00Z",
                "updated_at": "2026-07-15T12:00:00Z",
                "merged_at": None,
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://example.com/mr/1",
                "source_project_id": 1,
                "target_project_id": 1,
            },
            {
                "iid": 2,
                "title": "Window MR 2",
                "state": "opened",
                "author": {"username": "user2"},
                "source_branch": "feature/2",
                "target_branch": "main",
                "created_at": "2026-07-14T00:00:00Z",
                "updated_at": "2026-07-14T12:00:00Z",
                "merged_at": None,
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://example.com/mr/2",
                "source_project_id": 1,
                "target_project_id": 1,
            },
        ]
        # 전체 오픈 MR: MR 1, 2, 3 (3은 윈도 밖)
        all_data = window_data + [
            {
                "iid": 3,
                "title": "Old Open MR",
                "state": "opened",
                "author": {"username": "user3"},
                "source_branch": "feature/3",
                "target_branch": "main",
                "created_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-01T12:00:00Z",
                "merged_at": None,
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://example.com/mr/3",
                "source_project_id": 1,
                "target_project_id": 1,
            }
        ]
        mock_gitlab_client.list_merge_requests.return_value = window_data
        mock_gitlab_client.list_open_merge_requests.return_value = all_data
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        window_mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )
        merged = gitlab._merge_window_and_all_mrs(
            window_mrs, project_id="test_id", exclude_bot_authors=()
        )

        # 최종은 3개 (윈도 2 + 밖의 1)
        assert len(merged) == 3
        iids = [mr.iid for mr in merged]
        assert 3 in iids  # 윈도 밖의 MR도 포함

    def test_merge_open_mr_reviews_collected(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """윈도 밖 오픈 MR의 리뷰(노트)도 수집된다."""
        window_data: list[dict[str, Any]] = []
        all_data = [
            {
                "iid": 100,
                "title": "Old Open MR with notes",
                "state": "opened",
                "author": {"username": "user1"},
                "source_branch": "feature/old",
                "target_branch": "main",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T12:00:00Z",
                "merged_at": None,
                "draft": False,
                "work_in_progress": False,
                "labels": [],
                "web_url": "http://example.com/mr/100",
                "source_project_id": 1,
                "target_project_id": 1,
            }
        ]
        notes_data = [
            {
                "id": 1,
                "author": {"username": "reviewer1", "name": "Reviewer One"},
                "created_at": "2026-05-10T10:00:00Z",
                "system": False,
            }
        ]
        mock_gitlab_client.list_merge_requests.return_value = window_data
        mock_gitlab_client.list_open_merge_requests.return_value = all_data
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = notes_data

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        window_mrs = gitlab._collect_merge_requests(
            project_id="test_id", lookback_hours=24, exclude_bot_authors=(), now=now
        )
        merged = gitlab._merge_window_and_all_mrs(
            window_mrs, project_id="test_id", exclude_bot_authors=()
        )

        # MR 100이 포함되고, 리뷰도 있어야 함
        assert len(merged) == 1
        assert merged[0].iid == 100
        assert len(merged[0].reviews) >= 1
        assert any(r.kind == "commented" for r in merged[0].reviews)


class TestSubtreeScopingCommits:
    """서브트리 스코핑 — 커밋 경로 필터 (3.3(b))."""

    def test_subtree_path_passed_to_list_commits(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """subtree_path 설정 시 list_commits가 path 키워드로 호출된다."""
        mock_gitlab_client.list_commits.return_value = []
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
            subtree_path="sample-model",
        )

        assert mock_gitlab_client.list_commits.call_args.kwargs["path"] == "sample-model"

    def test_subtree_path_omitted_when_not_set(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """subtree_path 미설정 시 list_commits 호출 인자에 path 키가 없다 (회귀 고정)."""
        mock_gitlab_client.list_commits.return_value = []
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
        )

        assert "path" not in mock_gitlab_client.list_commits.call_args.kwargs

    def test_client_side_recheck_filters_when_server_ignores_path(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """서버가 path를 무시해 섞어 줘도 클라이언트 재확인으로 서브트리 밖 커밋을 걸러낸다."""
        mock_gitlab_client.list_commits.return_value = [
            {
                "id": "in-tree-sha",
                "author_name": "hong-gildong",
                "authored_date": "2026-07-16T08:00:00Z",
                "message": "feat: 서브트리 안",
            },
            {
                "id": "out-of-tree-sha",
                "author_name": "hong-gildong",
                "authored_date": "2026-07-16T08:10:00Z",
                "message": "feat: 서브트리 밖",
            },
        ]

        def fake_diff(project_id: str, sha: str) -> list[dict[str, Any]]:
            if sha == "in-tree-sha":
                return [
                    {
                        "new_path": "sample-model/src/a.ts",
                        "old_path": "sample-model/src/a.ts",
                    }
                ]
            return [{"new_path": "other-lib/src/b.ts", "old_path": "other-lib/src/b.ts"}]

        mock_gitlab_client.get_commit_diff.side_effect = fake_diff

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        commits = gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
            subtree_path="sample-model",
        )

        assert len(commits) == 1
        assert commits[0].sha == "in-tree-sha"

    def test_mixed_commit_included_with_full_changed_files(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """서브트리 파일과 밖 파일을 함께 건드린 커밋은 포함되고 changed_files가 안 잘린다."""
        mock_gitlab_client.list_commits.return_value = [
            {
                "id": "mixed-sha",
                "author_name": "hong-gildong",
                "authored_date": "2026-07-16T08:00:00Z",
                "message": "feat: 혼합 변경",
            }
        ]
        mock_gitlab_client.get_commit_diff.return_value = [
            {"new_path": "sample-model/src/a.ts", "old_path": "sample-model/src/a.ts"},
            {"new_path": "other-lib/src/b.ts", "old_path": "other-lib/src/b.ts"},
        ]

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        commits = gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            repo_web_url=sample_repo_ref.web_url,
            subtree_path="sample-model",
        )

        assert len(commits) == 1
        assert set(commits[0].changed_files) == {
            "sample-model/src/a.ts",
            "other-lib/src/b.ts",
        }


class TestSubtreeScopingMergeRequests:
    """서브트리 스코핑 — MR 게이트 (3.3(c))."""

    @staticmethod
    def _mr_data(iid: int) -> dict[str, Any]:
        return {
            "iid": iid,
            "title": f"MR {iid}",
            "state": "opened",
            "source_branch": "feature/x",
            "target_branch": "develop",
            "created_at": "2026-07-15T00:00:00Z",
            "updated_at": "2026-07-15T12:00:00Z",
            "merged_at": None,
            "author": {"username": "alice", "name": "Alice"},
            "draft": False,
            "work_in_progress": False,
            "labels": [],
            "web_url": f"http://test/mr/{iid}",
            "source_project_id": 1,
            "target_project_id": 1,
        }

    def test_mr_outside_subtree_excluded_without_review_calls(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """서브트리 밖 MR은 제외되고, notes·approvals 조회가 아예 일어나지 않는다."""
        mock_gitlab_client.list_merge_requests.return_value = [self._mr_data(1)]
        mock_gitlab_client.get_merge_request_changes.return_value = [
            {"new_path": "other-lib/src/x.ts", "old_path": "other-lib/src/x.ts"}
        ]

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            subtree_path="sample-model",
        )

        assert mrs == ()
        mock_gitlab_client.get_merge_request_notes.assert_not_called()
        mock_gitlab_client.get_merge_request_approvals.assert_not_called()

    def test_mr_inside_subtree_included_with_reviews(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """서브트리 안 MR은 포함되고 리뷰가 붙는다."""
        mock_gitlab_client.list_merge_requests.return_value = [self._mr_data(1)]
        mock_gitlab_client.get_merge_request_changes.return_value = [
            {"new_path": "sample-model/src/x.ts", "old_path": "sample-model/src/x.ts"}
        ]
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            subtree_path="sample-model",
        )

        assert len(mrs) == 1
        assert len(mrs[0].reviews) > 0

    def test_mr_changes_lookup_failure_fails_open(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """get_merge_request_changes가 실패하면 MR은 포함된다 (fail-open)."""
        mock_gitlab_client.list_merge_requests.return_value = [self._mr_data(1)]
        mock_gitlab_client.get_merge_request_changes.side_effect = CollectionError("서버 오류")
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        mrs = gitlab._collect_merge_requests(
            project_id="test_id",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
            subtree_path="sample-model",
        )

        assert len(mrs) == 1

    def test_all_open_mrs_applies_same_filter(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """_collect_all_open_mrs에도 같은 서브트리 필터가 적용된다."""
        mock_gitlab_client.list_open_merge_requests.return_value = [
            self._mr_data(1),
            self._mr_data(2),
        ]

        def fake_changes(project_id: str, mr_iid: int) -> list[dict[str, Any]]:
            if mr_iid == 1:
                return [{"new_path": "sample-model/a.ts", "old_path": "sample-model/a.ts"}]
            return [{"new_path": "other-lib/b.ts", "old_path": "other-lib/b.ts"}]

        mock_gitlab_client.get_merge_request_changes.side_effect = fake_changes
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        mrs = gitlab._collect_all_open_mrs(
            "test_id", exclude_bot_authors=(), subtree_path="sample-model"
        )

        assert len(mrs) == 1
        assert mrs[0].iid == 1

    def test_recent_merge_requests_never_calls_get_merge_request_changes(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """릴리스 열차용 최근 MR 조회는 서브트리 필터를 적용하지 않는다."""
        mock_gitlab_client.list_recent_merge_requests.return_value = [self._mr_data(1)]
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = []

        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        recent = gitlab._collect_recent_merge_requests(
            project_id="test_id", limit=50, exclude_bot_authors=()
        )

        assert len(recent) == 1
        mock_gitlab_client.get_merge_request_changes.assert_not_called()


class TestSubtreeScopingRegression:
    """미설정(subtree_path=None) 시 기존 동작이 완전히 동일함을 보증한다."""

    def test_unset_subtree_path_never_calls_get_merge_request_changes(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock, load_fixture: FixtureLoader
    ) -> None:
        """subtree_path가 None인 RepoRef는 전체 파이프라인에서 changes API를 호출하지 않는다."""
        mock_gitlab_client.list_branches.return_value = load_fixture("gitlab_branches")
        mock_gitlab_client.list_commits.return_value = load_fixture("gitlab_commits")
        mock_gitlab_client.get_commit_diff.return_value = load_fixture("gitlab_commit_diff")
        mock_gitlab_client.list_merge_requests.return_value = load_fixture("gitlab_merge_requests")
        mock_gitlab_client.list_open_merge_requests.return_value = load_fixture(
            "gitlab_merge_requests"
        )
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        mock_gitlab_client.get_merge_request_notes.return_value = load_fixture("gitlab_mr_notes")
        mock_gitlab_client.list_recent_merge_requests.return_value = []

        assert sample_repo_ref.subtree_path is None
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
        activity = gitlab.collect_repo_activity(
            repo=sample_repo_ref,
            lookback_hours=24,
            exclude_bot_authors=(),
            now=now,
        )

        assert activity.status == "ok"
        mock_gitlab_client.get_merge_request_changes.assert_not_called()
        mock_gitlab_client.list_commits.assert_called()
        for call in mock_gitlab_client.list_commits.call_args_list:
            assert "path" not in call.kwargs


class TestLegacyGitLabCompat:
    """구버전 GitLab 응답 호환성 — web_url·merged_at 필드가 없어도 수집된다."""

    REPO_WEB_URL = "https://gitlab.example.com/sample-group/sample-repo"

    def test_commit_without_web_url_gets_fallback(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """커밋 응답에 web_url이 없으면 레포 web_url 기반 폴백 URL을 생성한다."""
        # Arrange — 구버전 GitLab 커밋 목록 응답에는 web_url이 없다
        mock_gitlab_client.list_commits.return_value = [
            {
                "id": "abc123def456",
                "author_name": "hong-gildong",
                "authored_date": "2026-07-16T08:00:00Z",
                "message": "feat: 로그인 개선",
            }
        ]
        mock_gitlab_client.get_commit_diff.return_value = []
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        # Act
        commits = gitlab._collect_commits_for_branch(
            project_id="test_id",
            branch_name="develop",
            lookback_hours=24,
            exclude_bot_authors=(),
            now=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            repo_web_url=self.REPO_WEB_URL,
        )

        # Assert
        assert commits[0].web_url == f"{self.REPO_WEB_URL}/commit/abc123def456"

    def test_active_branch_without_web_url_gets_fallback(self, sample_repo_ref: RepoRef) -> None:
        """브랜치 응답에 web_url이 없으면 tree 경로 폴백 URL을 생성한다."""
        # Arrange — 구버전 GitLab 브랜치 목록 응답에는 web_url이 없다
        branch_data = {
            "name": "feature/login",
            "commit": {"id": "sha1", "committed_date": "2026-07-16T08:00:00Z"},
        }
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")

        # Act
        branches = gitlab._build_active_branch_objs([branch_data], repo_web_url=self.REPO_WEB_URL)

        # Assert
        assert branches[0].web_url == f"{self.REPO_WEB_URL}/tree/feature/login"

    def test_stale_branch_without_web_url_gets_fallback(self, sample_repo_ref: RepoRef) -> None:
        """stale 브랜치 응답에 web_url이 없어도 폴백 URL로 수집된다."""
        # Arrange
        branch_data = {
            "name": "feature/old-work",
            "merged": False,
            "default": False,
            "commit": {"id": "sha2", "committed_date": "2026-06-01T08:00:00Z"},
        }
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")

        # Act
        stale = gitlab._collect_stale_branches(
            [branch_data],
            stale_branch_days=7,
            now=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            repo_web_url=self.REPO_WEB_URL,
        )

        # Assert
        assert stale[0].web_url == f"{self.REPO_WEB_URL}/tree/feature/old-work"

    def test_branch_url_fallback_provided_web_url_wins(self, sample_repo_ref: RepoRef) -> None:
        """응답에 web_url이 있으면 폴백 대신 그 값을 그대로 쓴다."""
        # Arrange
        branch_data = {
            "name": "develop",
            "commit": {"id": "sha3", "committed_date": "2026-07-16T08:00:00Z"},
            "web_url": "http://example.com/-/tree/develop",
        }
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")

        # Act
        branches = gitlab._build_active_branch_objs([branch_data], repo_web_url=self.REPO_WEB_URL)

        # Assert
        assert branches[0].web_url == "http://example.com/-/tree/develop"

    def _make_mr_data(self, state: str) -> dict[str, Any]:
        """구버전 GitLab 스타일 MR 응답 (merged_at·draft 없음, work_in_progress만 존재)."""
        return {
            "iid": 42,
            "title": "feat: 결제 모듈",
            "state": state,
            "work_in_progress": False,
            "labels": [],
            "source_branch": "feature/payment",
            "target_branch": "develop",
            "author": {"username": "hong-gildong"},
            "created_at": "2026-07-15T02:00:00Z",
            "updated_at": "2026-07-16T05:00:00Z",
            "source_project_id": 1,
            "target_project_id": 1,
            "web_url": "https://gitlab.example.com/sample-group/repo/merge_requests/42",
        }

    def test_merged_mr_without_merged_at_falls_back_to_updated_at(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """merged 상태인데 merged_at 필드가 없으면 updated_at로 근사한다."""
        # Arrange
        mock_gitlab_client.get_merge_request_notes.return_value = []
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        # Act
        mr = gitlab._process_single_mr("test_id", self._make_mr_data("merged"), ())

        # Assert
        assert mr is not None
        assert mr.merged_at == datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc)

    def test_open_mr_without_merged_at_stays_none(
        self, sample_repo_ref: RepoRef, mock_gitlab_client: Mock
    ) -> None:
        """open 상태 MR은 merged_at 폴백을 적용하지 않는다."""
        # Arrange
        mock_gitlab_client.get_merge_request_notes.return_value = []
        mock_gitlab_client.get_merge_request_approvals.return_value = {}
        gitlab = GitLab(base_url=sample_repo_ref.base_url, token="test-token")
        gitlab.client = mock_gitlab_client

        # Act
        mr = gitlab._process_single_mr("test_id", self._make_mr_data("opened"), ())

        # Assert
        assert mr is not None
        assert mr.merged_at is None


class TestPageLimitWarning:
    """페이지 상한 경고 — 절단을 침묵시키지 않는다.

    7차부터 목록 조회는 페이지를 순회한다(과거에는 첫 100건만 받고 버렸다).
    따라서 경고는 "100건 도달"이 아니라 "안전 상한(_MAX_PAGES) 도달" 시점에 나온다.
    """

    def test_list_open_merge_requests_warns_at_page_ceiling(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """모든 페이지가 꽉 차 있으면 안전 상한까지 순회하고 경고를 남긴다."""
        # Arrange
        client = GitLabClient(base_url="http://test", token="test-token")
        full_page = [{"iid": i} for i in range(100)]
        monkeypatch.setattr(client, "_request", lambda *args, **kwargs: full_page)

        # Act
        with caplog.at_level("WARNING", logger="pulse.collector.http_client"):
            result = client.list_open_merge_requests("test_id")

        # Assert
        assert len(result) == _MAX_PAGES * 100
        assert any("페이지 상한" in record.message for record in caplog.records)

    def test_multi_page_collection_is_complete(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """100건을 넘는 목록도 끝까지 수집한다 (과거에는 100건에서 잘렸다)."""
        # Arrange
        client = GitLabClient(base_url="http://test", token="test-token")
        pages = [[{"iid": i} for i in range(100)], [{"iid": 100 + i} for i in range(23)]]

        def fake_request(
            method: str, endpoint: str, params: dict[str, Any] | None = None, **kwargs: Any
        ) -> list[dict[str, int]]:
            page = int((params or {}).get("page", 1))
            return pages[page - 1] if page <= len(pages) else []

        monkeypatch.setattr(client, "_request", fake_request)

        # Act
        with caplog.at_level("WARNING", logger="pulse.collector.http_client"):
            result = client.list_open_merge_requests("test_id")

        # Assert
        assert len(result) == 123
        assert not any("페이지 상한" in record.message for record in caplog.records)

    def test_list_branches_no_warning_under_limit(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """상한 미만이면 경고가 없다."""
        # Arrange
        client = GitLabClient(base_url="http://test", token="test-token")
        monkeypatch.setattr(client, "_request", lambda *args, **kwargs: [{"name": "develop"}])

        # Act
        with caplog.at_level("WARNING", logger="pulse.collector.http_client"):
            result = client.list_branches("test_id")

        # Assert
        assert len(result) == 1
        assert not any("페이지 상한" in record.message for record in caplog.records)


class TestListCommitsPathParam:
    """list_commits의 path 파라미터 — 3.3(b) 회귀 고정.

    기존 레포(subtree_path 미설정)의 요청 쿼리스트링이 바이트 단위로 동일해야
    회귀가 없다. path를 주면 서버 사이드 필터로 그대로 전달된다.
    """

    def test_path_omitted_from_query_when_not_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """path를 안 주면 쿼리 파라미터에 path 키가 없다 (기존 레포 회귀 방지)."""
        client = GitLabClient(base_url="http://test", token="test-token")
        captured_params: dict[str, Any] = {}

        def fake_request_list(
            method: str, endpoint: str, params: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            captured_params.update(params or {})
            return []

        monkeypatch.setattr(client, "_request_list", fake_request_list)

        client.list_commits("test_id", "develop", "2026-07-01T00:00:00+00:00")

        assert "path" not in captured_params
        assert captured_params["ref_name"] == "develop"

    def test_path_included_in_query_when_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """path를 주면 쿼리 파라미터에 그대로 전달된다."""
        client = GitLabClient(base_url="http://test", token="test-token")
        captured_params: dict[str, Any] = {}

        def fake_request_list(
            method: str, endpoint: str, params: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            captured_params.update(params or {})
            return []

        monkeypatch.setattr(client, "_request_list", fake_request_list)

        client.list_commits("test_id", "develop", "2026-07-01T00:00:00+00:00", path="sample-model")

        assert captured_params["path"] == "sample-model"


class TestGetMergeRequestChanges:
    """get_merge_request_changes — 구버전에도 있는 /changes 엔드포인트 (신버전 /diffs 아님)."""

    def test_returns_changes_array_only(
        self, monkeypatch: pytest.MonkeyPatch, load_fixture: FixtureLoader
    ) -> None:
        """응답 dict에서 changes 배열만 추출해 반환한다."""
        client = GitLabClient(base_url="http://test", token="test-token")
        fixture = load_fixture("gitlab_mr_changes")
        captured_endpoint: dict[str, str] = {}

        def fake_request_dict(
            method: str, endpoint: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            captured_endpoint["endpoint"] = endpoint
            return dict(fixture)

        monkeypatch.setattr(client, "_request_dict", fake_request_dict)

        changes = client.get_merge_request_changes("test_id", 42)

        assert changes == fixture["changes"]
        assert captured_endpoint["endpoint"] == "projects/test_id/merge_requests/42/changes"

    def test_missing_changes_key_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """changes 키가 없는 응답이면 빈 리스트를 반환한다."""
        client = GitLabClient(base_url="http://test", token="test-token")
        monkeypatch.setattr(client, "_request_dict", lambda *a, **k: {"iid": 42})

        changes = client.get_merge_request_changes("test_id", 42)

        assert changes == []


class TestRateLimitStats:
    """RateLimitStats 테스트."""

    def test_rate_limit_stats_init(self) -> None:
        """RateLimitStats는 초기값으로 초기화된다."""
        stats = RateLimitStats()
        assert stats.total_requests == 0
        assert stats.rate_limited_count == 0
        assert stats.total_wait_time == 0.0

    def test_add_request(self) -> None:
        """add_request는 요청 횟수를 증가시킨다."""
        stats = RateLimitStats()
        stats.add_request()
        stats.add_request()
        assert stats.total_requests == 2

    def test_add_rate_limited(self) -> None:
        """add_rate_limited는 rate limit 통계를 기록한다."""
        stats = RateLimitStats()
        stats.add_rate_limited(1.0)
        stats.add_rate_limited(2.0)
        assert stats.rate_limited_count == 2


class TestGitLabMRAuthorName:
    """GitLab MR author name 추출 (name 우선, username 폴백)."""

    def test_get_mr_author_name_with_name_field(self) -> None:
        """author.name이 있으면 name을 반환 (username 무시)."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        mr_data: dict[str, Any] = {
            "author": {
                "name": "[DEV]홍길동",
                "username": "hong-gildong",
            }
        }

        # Act
        result = gitlab._get_mr_author_name(mr_data)

        # Assert
        assert result == "[DEV]홍길동"

    def test_get_mr_author_name_with_username_only(self) -> None:
        """author.name이 없으면 username으로 폴백."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        mr_data: dict[str, Any] = {
            "author": {
                "username": "hong-gildong",
            }
        }

        # Act
        result = gitlab._get_mr_author_name(mr_data)

        # Assert
        assert result == "hong-gildong"

    def test_get_mr_author_name_with_empty_name_falls_back_to_username(self) -> None:
        """author.name이 빈 문자열이면 username으로 폴백."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        mr_data: dict[str, Any] = {
            "author": {
                "name": "",
                "username": "hong-gildong",
            }
        }

        # Act
        result = gitlab._get_mr_author_name(mr_data)

        # Assert
        assert result == "hong-gildong"

    def test_get_mr_author_name_with_empty_author_object(self) -> None:
        """author가 빈 객체면 "unknown" 반환."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        mr_data: dict[str, Any] = {
            "author": {},
        }

        # Act
        result = gitlab._get_mr_author_name(mr_data)

        # Assert
        assert result == "unknown"

    def test_get_mr_author_name_with_no_author_field(self) -> None:
        """author 필드가 없으면 "unknown" 반환."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        mr_data: dict[str, Any] = {}

        # Act
        result = gitlab._get_mr_author_name(mr_data)

        # Assert
        assert result == "unknown"

    def test_mr_bot_filter_with_display_name(self) -> None:
        """MR 봇 필터가 표시 이름으로 동작 — "Renovate Bot"가 ["Renovate"] 제외 규칙과 매칭."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        # MR 데이터: GitLab API author.name은 표시 이름 반환
        mr_data: dict[str, Any] = {
            "author": {
                "name": "Renovate Bot",
                "username": "renovate-bot",
            }
        }

        # Act: _get_mr_author_name은 표시 이름 "Renovate Bot" 반환
        author_name = gitlab._get_mr_author_name(mr_data)
        # _should_include_commit는 표시 이름을 substring 매칭
        should_include = gitlab._should_include_commit(author_name, ("Renovate",))

        # Assert: "Renovate Bot"이 "Renovate" 제외 규칙과 매칭되어 False(제외됨)
        assert author_name == "Renovate Bot"
        assert should_include is False

    def test_mr_bot_filter_with_username_not_matched(self) -> None:
        """MR 봇 필터는 로그인 ID 기준이 아니라 표시 이름 기준 — 로그인 ID는 매칭 안 됨."""
        # Arrange
        gitlab = GitLab(base_url="http://gitlab.example.com", token="test-token")
        # MR 데이터: 표시 이름이 "Renovate Bot", 로그인 ID가 "renovate-bot"
        mr_data: dict[str, Any] = {
            "author": {
                "name": "Renovate Bot",
                "username": "renovate-bot",
            }
        }

        # Act
        author_name = gitlab._get_mr_author_name(mr_data)
        # 로그인 ID 형태의 제외 규칙은 표시 이름 기준에서는 매칭되지 않음
        should_include = gitlab._should_include_commit(author_name, ("renovate-bot",))

        # Assert: "renovate-bot"은 "Renovate Bot"과 부분 문자열 매칭되지 않으므로 True(미제외)
        assert author_name == "Renovate Bot"
        assert should_include is True
