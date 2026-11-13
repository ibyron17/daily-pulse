"""브랜치 히스토리 수집 테스트 — GitLab/GitHub 각 경로 (HTTP 모킹).

두 provider는 API 특성이 달라 경로가 다르다:
  GitLab — merge_base + commits?since + 역방향 compare(behind)
  GitHub — compare 1회로 분기점·behind·총계, 250건 초과분만 page 순회
정규화 모델(BranchHistoryFetch)은 동일해야 한다.
"""

from typing import Any
from unittest.mock import Mock

from pulse.collector.github_client import GitHubClient
from pulse.collector.github_history import collect_branch_history as github_collect
from pulse.collector.gitlab import CollectionError
from pulse.collector.gitlab_history import collect_branch_history as gitlab_collect
from pulse.collector.http_client import GitLabClient
from pulse.models import BranchHistoryRequest

REQUEST = (BranchHistoryRequest(branch_name="feature/x", head_sha="head1"),)


def gitlab_commit(sha: str, day: str, message: str) -> dict[str, Any]:
    """GitLab 커밋 응답 형태."""
    return {"id": sha, "committed_date": f"{day}T12:00:00.000+09:00", "message": message}


def github_commit(sha: str, day: str, message: str) -> dict[str, Any]:
    """GitHub 커밋 응답 형태."""
    return {"sha": sha, "commit": {"message": message, "committer": {"date": f"{day}T12:00:00Z"}}}


class TestGitLabHistory:
    """GitLab 경로 — merge_base로 base를 고르고 compare로 커밋을 받는다.

    회귀 방지: 한때 merge_base 날짜로 `commits?since=`를 걸었는데, merge_base는
    "처음 갈라진 지점"이 아니라 "마지막으로 base를 머지한 지점"이어서 그 이전 작업이
    전부 누락됐다(실측: 211건 중 130건 손실). compare의 commits를 써야 한다.
    """

    def _client(self) -> Mock:
        client = Mock(spec=GitLabClient)
        client.list_branches.return_value = [
            {"name": "develop"},
            {"name": "master"},
            {"name": "feature/x"},
        ]
        client.get_project.return_value = {"default_branch": "master"}
        client.get_merge_base.side_effect = lambda _pid, candidate, _branch: {
            "develop": {"id": "mb_dev", "committed_date": "2026-07-09T00:00:00.000+09:00"},
            "master": {"id": "mb_mst", "committed_date": "2026-01-10T00:00:00.000+09:00"},
        }[candidate]
        return client

    def _with_compare(
        self,
        client: Mock,
        forward: list[dict[str, Any]],
        behind: int = 2,
    ) -> None:
        """정방향(base→branch)과 역방향(branch→base) compare 응답을 설정한다."""

        def compare(_pid: str, from_ref: str, to_ref: str) -> dict[str, Any]:
            if to_ref == "feature/x":  # 정방향 — 브랜치 고유 커밋
                return {"commits": forward, "compare_timeout": True}
            return {"commits": [{"id": f"b{index}"} for index in range(behind)]}

        client.compare_refs.side_effect = compare

    def test_history_reaches_before_last_base_merge(self) -> None:
        """merge_base(07-09)보다 이전 커밋(05-27)도 히스토리에 포함되어야 한다."""
        client = self._client()
        self._with_compare(
            client,
            [
                gitlab_commit("mb_dev", "2026-07-09", "[chore] 동기화 지점"),
                gitlab_commit("c1", "2026-05-27", "[feat] 시작"),
                gitlab_commit("c2", "2026-07-27", "[fix] 최근"),
            ],
        )

        fetches = gitlab_collect(client, "pid", REQUEST, base_hint=None, max_commits=1000)

        fetch = fetches[0]
        # 분기점이 더 최근인 develop이 선택된다 (default_branch master가 아니라)
        assert fetch.base_branch == "develop"
        assert fetch.merge_base_sha == "mb_dev"
        # merge_base 커밋 자체는 제외하되, 그보다 이전 커밋은 남는다
        assert [commit.sha for commit in fetch.commits] == ["c1", "c2"]
        earliest = min(commit.worked_at.date().isoformat() for commit in fetch.commits)
        assert earliest == "2026-05-27"
        assert fetch.total_commits == 2
        assert fetch.truncated is False
        assert fetch.behind_count == 2
        assert fetch.head_sha == "head1"

    def test_compare_timeout_does_not_discard_commits(self) -> None:
        """compare_timeout은 diffs만 자른다 — commits는 그대로 쓴다."""
        client = self._client()
        self._with_compare(
            client, [gitlab_commit(f"c{index}", "2026-06-01", "[feat] x") for index in range(50)]
        )
        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)
        assert fetches[0].total_commits == 50

    def test_base_hint_skips_candidate_search(self) -> None:
        client = self._client()
        self._with_compare(client, [gitlab_commit("c1", "2026-06-01", "[feat] x")])

        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)

        assert fetches[0].base_branch == "develop"
        # hint가 있으면 merge_base를 1회만 조회한다
        assert client.get_merge_base.call_count == 1
        # default_branch 조회도 생략된다
        client.get_project.assert_not_called()

    def test_over_limit_keeps_recent_and_reports_real_total(self) -> None:
        client = self._client()
        commits = [
            gitlab_commit(f"c{index}", f"2026-06-{1 + index:02d}", "[feat] x")
            for index in range(10)
        ]
        self._with_compare(client, commits)

        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=4)

        fetch = fetches[0]
        # 총계는 정확히 보고하고, 집계는 최근 구간만 남긴다
        assert fetch.total_commits == 10
        assert fetch.truncated is True
        assert len(fetch.commits) == 4
        kept = sorted(commit.worked_at.date().isoformat() for commit in fetch.commits)
        assert kept[0] == "2026-06-07"

    def test_prefers_authored_date_over_committed(self) -> None:
        """리베이스는 committed만 리셋한다 — authored가 있으면 그쪽이 작업 시각이다."""
        client = self._client()
        rebased = {
            "id": "c1",
            "authored_date": "2026-07-07T12:00:00.000+09:00",
            "committed_date": "2026-07-24T12:00:00.000+09:00",
            "message": "[feat] 시작",
        }
        self._with_compare(client, [rebased])

        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)

        assert fetches[0].commits[0].worked_at.date().isoformat() == "2026-07-07"

    def test_branch_point_failure_skips_only_that_branch(self) -> None:
        client = self._client()
        client.get_merge_base.side_effect = CollectionError("merge_base 미지원")
        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)
        assert fetches == ()

    def test_compare_failure_skips_only_that_branch(self) -> None:
        client = self._client()
        client.compare_refs.side_effect = CollectionError("timeout")
        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)
        assert fetches == ()

    def test_behind_failure_leaves_none(self) -> None:
        client = self._client()

        def compare(_pid: str, from_ref: str, to_ref: str) -> dict[str, Any]:
            if to_ref == "feature/x":
                return {"commits": [gitlab_commit("c1", "2026-06-01", "[feat] x")]}
            raise CollectionError("역방향 compare 실패")

        client.compare_refs.side_effect = compare
        fetches = gitlab_collect(client, "pid", REQUEST, base_hint="develop", max_commits=1000)
        assert fetches[0].behind_count is None

    def test_branch_list_failure_returns_empty(self) -> None:
        client = self._client()
        client.list_branches.side_effect = CollectionError("접근 불가")
        assert gitlab_collect(client, "pid", REQUEST, base_hint=None, max_commits=1000) == ()

    def test_empty_requests_makes_no_calls(self) -> None:
        client = self._client()
        assert gitlab_collect(client, "pid", (), base_hint=None, max_commits=1000) == ()
        client.list_branches.assert_not_called()

    def test_single_branch_repo_yields_nothing(self) -> None:
        """브랜치가 하나뿐이면 base 후보가 없어 조회하지 않는다 (실측: sample-docs)."""
        client = Mock(spec=GitLabClient)
        client.list_branches.return_value = [{"name": "main"}]
        client.get_project.return_value = {"default_branch": "main"}
        fetches = gitlab_collect(
            client,
            "pid",
            (BranchHistoryRequest(branch_name="main", head_sha="h"),),
            base_hint=None,
            max_commits=1000,
        )
        assert fetches == ()
        client.get_merge_base.assert_not_called()


class TestGitHubHistory:
    def _client(self) -> Mock:
        client = Mock(spec=GitHubClient)
        client.list_branches.return_value = [
            {"name": "develop"},
            {"name": "master"},
            {"name": "feature/x"},
        ]
        client.get_repo_info.return_value = {"default_branch": "master"}
        return client

    def test_single_compare_yields_base_behind_and_commits(self) -> None:
        """GitHub은 compare 1회로 분기점·behind·총계를 함께 준다."""
        client = self._client()
        client.compare_refs.return_value = {
            "merge_base_commit": {
                "sha": "mb",
                "commit": {"committer": {"date": "2026-05-27T00:00:00Z"}},
            },
            "ahead_by": 2,
            "behind_by": 7,
            "total_commits": 2,
            "commits": [
                github_commit("c1", "2026-05-27", "feat: start"),
                github_commit("c2", "2026-07-27", "fix: latest"),
            ],
        }

        fetches = github_collect(
            client, "owner", "repo", REQUEST, base_hint="develop", max_commits=1000
        )

        fetch = fetches[0]
        assert fetch.base_branch == "develop"
        assert fetch.merge_base_sha == "mb"
        assert [commit.sha for commit in fetch.commits] == ["c1", "c2"]
        assert fetch.behind_count == 7
        assert fetch.truncated is False
        # behind를 위한 추가 호출이 없다 (GitLab과 달리 역방향 compare 불필요)
        assert client.compare_refs.call_count == 1

    def test_paginates_beyond_commit_ceiling(self) -> None:
        """250건 상한을 넘으면 page로 순회한다 (실측: cpython 4591건 중 250건)."""
        client = self._client()
        first_page = [github_commit(f"c{i}", "2026-06-01", "feat: x") for i in range(100)]
        second_page = [github_commit(f"d{i}", "2026-06-02", "fix: y") for i in range(50)]

        def compare(
            _owner: str, _repo: str, _base: str, _head: str, page: int = 1
        ) -> dict[str, Any]:
            commits = {1: first_page, 2: second_page}.get(page, [])
            return {
                "merge_base_commit": {
                    "sha": "mb",
                    "commit": {"committer": {"date": "2026-05-27T00:00:00Z"}},
                },
                "behind_by": 0,
                "total_commits": 150,
                "commits": commits,
            }

        client.compare_refs.side_effect = compare
        fetches = github_collect(
            client, "owner", "repo", REQUEST, base_hint="develop", max_commits=1000
        )

        assert len(fetches[0].commits) == 150
        assert fetches[0].total_commits == 150
        assert fetches[0].truncated is False

    def test_max_commits_truncates_and_reports_real_total(self) -> None:
        client = self._client()
        client.compare_refs.return_value = {
            "merge_base_commit": {
                "sha": "mb",
                "commit": {"committer": {"date": "2026-05-27T00:00:00Z"}},
            },
            "behind_by": 0,
            "total_commits": 4591,
            "commits": [github_commit(f"c{i}", "2026-06-01", "feat: x") for i in range(100)],
        }

        fetches = github_collect(
            client, "owner", "repo", REQUEST, base_hint="develop", max_commits=50
        )

        fetch = fetches[0]
        assert len(fetch.commits) == 50
        # 실제 총계는 그대로 보고해 "N건 이상"을 표시할 수 있게 한다
        assert fetch.total_commits == 4591
        assert fetch.truncated is True

    def test_picks_closest_branch_point_between_candidates(self) -> None:
        client = self._client()

        def compare(
            _owner: str, _repo: str, base: str, _head: str, page: int = 1
        ) -> dict[str, Any]:
            dates = {"develop": "2026-07-01T00:00:00Z", "master": "2026-01-10T00:00:00Z"}
            return {
                "merge_base_commit": {
                    "sha": f"mb_{base}",
                    "commit": {"committer": {"date": dates[base]}},
                },
                "behind_by": 1,
                "total_commits": 1,
                "commits": [github_commit("c1", "2026-07-02", "feat: x")],
            }

        client.compare_refs.side_effect = compare
        fetches = github_collect(client, "owner", "repo", REQUEST, base_hint=None, max_commits=1000)
        assert fetches[0].base_branch == "develop"

    def test_prefers_author_date_over_committer(self) -> None:
        """리베이스는 committer만 리셋한다 — author가 있으면 그쪽이 작업 시각이다."""
        client = self._client()
        rebased = {
            "sha": "c1",
            "commit": {
                "message": "feat: start",
                "author": {"date": "2026-07-07T12:00:00Z"},
                "committer": {"date": "2026-07-24T12:00:00Z"},
            },
        }
        client.compare_refs.return_value = {
            "merge_base_commit": {
                "sha": "mb",
                "commit": {"committer": {"date": "2026-05-27T00:00:00Z"}},
            },
            "behind_by": 0,
            "total_commits": 1,
            "commits": [rebased],
        }

        fetches = github_collect(
            client, "owner", "repo", REQUEST, base_hint="develop", max_commits=1000
        )

        assert fetches[0].commits[0].worked_at.date().isoformat() == "2026-07-07"

    def test_compare_failure_skips_branch(self) -> None:
        client = self._client()
        client.compare_refs.side_effect = CollectionError("404")
        assert (
            github_collect(client, "owner", "repo", REQUEST, base_hint="develop", max_commits=1000)
            == ()
        )

    def test_branch_list_failure_returns_empty(self) -> None:
        client = self._client()
        client.list_branches.side_effect = CollectionError("접근 불가")
        assert (
            github_collect(client, "owner", "repo", REQUEST, base_hint=None, max_commits=1000) == ()
        )
