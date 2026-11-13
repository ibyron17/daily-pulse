"""GitHub GraphQL + REST API를 통한 활동 수집."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from pulse.collector.diff_summary import DiffFileStat, summarize_diff
from pulse.collector.github_client import GitHubClient
from pulse.collector.http_client import RateLimitStats
from pulse.collector.snapshot import load_or_create
from pulse.models import (
    BranchHistoryFetch,
    BranchHistoryRequest,
    BranchInfo,
    CommitInfo,
    MergeRequestInfo,
    MRState,
    RepoActivity,
    RepoRef,
    ReviewEvent,
    ReviewKind,
)

logger = logging.getLogger(__name__)

# GraphQL 쿼리: 브랜치, PR, 기본 브랜치 정보 조회
_GITHUB_REPO_ACTIVITY_QUERY = """
query FetchRepoActivity($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    refs(first: $first, refPrefix: "refs/heads/") {
      nodes {
        name
        target {
          oid
          ... on Commit {
            committedDate
          }
        }
      }
      pageInfo {
        hasNextPage
      }
    }
    openPRs: pullRequests(states: OPEN, first: 100) {
      nodes {
        number
        title
        body
        state
        isDraft
        author {
          login
        }
        createdAt
        updatedAt
        mergedAt
        baseRefName
        headRefName
        reviews(first: 100) {
          nodes {
            state
            submittedAt
            author {
              login
            }
          }
        }
      }
      pageInfo {
        hasNextPage
      }
    }
    recentPRs: pullRequests(first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        title
        body
        state
        isDraft
        author {
          login
        }
        createdAt
        updatedAt
        mergedAt
        baseRefName
        headRefName
        reviews(first: 100) {
          nodes {
            state
            submittedAt
            author {
              login
            }
          }
        }
      }
      pageInfo {
        hasNextPage
      }
    }
    defaultBranchRef {
      name
    }
  }
  rateLimit {
    remaining
    resetAt
  }
}
"""

# GraphQL 쿼리: 단일 브랜치의 커밋 조회
_GITHUB_BRANCH_COMMITS_QUERY = """
query FetchBranchCommits($owner: String!, $name: String!, $refName: String!,
    $after_date: GitTimestamp) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $refName) {
      target {
        ... on Commit {
          history(first: 100, since: $after_date) {
            nodes {
              oid
              message
              author {
                name
                date
              }
              committedDate
            }
            pageInfo {
              hasNextPage
            }
          }
        }
      }
    }
  }
  rateLimit {
    remaining
    resetAt
  }
}
"""


def _normalize_mr_state(github_state: str) -> MRState:
    """
    GitHub API 상태값을 모델 타입으로 정규화한다.
    GitHub: "OPEN", "MERGED", "CLOSED"
    모델: "open", "merged", "closed"
    알 수 없는 값 → CollectionError 발생 (수집 중단)
    """
    from pulse.collector.gitlab import CollectionError

    state_lower = github_state.lower()
    if state_lower == "open":
        return "open"
    if state_lower == "merged":
        return "merged"
    if state_lower == "closed":
        return "closed"
    raise CollectionError(f"알 수 없는 PR 상태: {github_state}")


def _fallback_commit_url(repo_web_url: str, sha: str) -> str:
    """web_url 미제공 커밋의 폴백 URL을 만든다."""
    return f"{repo_web_url}/commit/{sha}"


def _fallback_branch_url(repo_web_url: str, branch_name: str) -> str:
    """web_url 미제공 브랜치의 폴백 URL을 만든다."""
    return f"{repo_web_url}/tree/{quote(branch_name, safe='/')}"


class GitHub:
    """GitHub GraphQL + REST API 기반 수집 구현체."""

    def __init__(
        self,
        token: str,
        stats: RateLimitStats | None = None,
    ) -> None:
        """GitHub 서버 연결 초기화."""
        self.client = GitHubClient(token, stats)

    def get_repo_version(self, repo: RepoRef) -> str:
        """GitHub 레포 정보를 확인한다."""
        from pulse.collector.gitlab import CollectionError

        try:
            _repo_info = self.client.get_repo_info(repo.namespace, repo.name)
            logger.info("GitHub 레포: %s/%s", repo.namespace, repo.name)
            return "GitHub"
        except CollectionError as error:
            raise CollectionError(f"레포 정보 조회 실패: {error}") from error

    def _should_include_commit(
        self,
        author_name: str,
        exclude_bot_authors: tuple[str, ...],
    ) -> bool:
        """봇 작성자 제외 필터 적용."""
        return not any(excluded in author_name for excluded in exclude_bot_authors)

    def _build_commit_info(
        self,
        commit_data: dict[str, Any],
        branch_name: str,
        repo_web_url: str,
        owner: str,
        repo: str,
    ) -> CommitInfo:
        """커밋 데이터로부터 CommitInfo 객체 생성."""
        from pulse.collector.gitlab import CollectionError

        sha = commit_data.get("oid", "unknown")
        changed_files, changed_files_summary = self._get_commit_changed_files(owner, repo, sha)
        author_data = commit_data.get("author", {})
        author_name = author_data.get("name", "unknown") if author_data else "unknown"

        authored_at_str = commit_data.get("committedDate", "")
        try:
            authored_at = datetime.fromisoformat(authored_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            raise CollectionError(f"잘못된 datetime 형식: {authored_at_str}") from e

        return CommitInfo(
            sha=sha,
            author_name=author_name,
            authored_at=authored_at,
            message=commit_data.get("message", ""),
            branch=branch_name,
            changed_files=changed_files,
            web_url=_fallback_commit_url(repo_web_url, sha),
            changed_files_summary=changed_files_summary,
        )

    def _get_commit_changed_files(
        self, owner: str, repo: str, sha: str
    ) -> tuple[tuple[str, ...], str | None]:
        """
        커밋의 변경 파일 경로와 발췌를 조회한다.
        GitHub REST API 응답의 files[]{filename, additions, deletions, patch} 사용.

        Returns:
            (changed_files 경로 튜플, changed_files_summary 발췌 문자열)
        """
        try:
            files_data = self.client.get_commit_changed_files(owner, repo, sha)
            filenames = []
            diff_file_stats = []

            for file_data in files_data:
                filename = file_data.get("filename", "")
                if filename:
                    filenames.append(filename)

                    # additions/deletions과 patch(diff 텍스트) 사용
                    additions = file_data.get("additions", 0)
                    deletions = file_data.get("deletions", 0)
                    patch_text = file_data.get("patch", "")

                    from pulse.collector.diff_summary import _extract_hunk_headers

                    headers = _extract_hunk_headers(patch_text)
                    diff_file_stats.append(
                        DiffFileStat(
                            path=filename,
                            added_lines=additions,
                            deleted_lines=deletions,
                            hunk_headers=headers,
                        )
                    )

            changed_files = tuple(filenames)
            changed_files_summary = (
                summarize_diff(tuple(diff_file_stats)) if diff_file_stats else None
            )
            return changed_files, changed_files_summary

        except Exception as error:
            logger.debug("변경 파일 조회 실패 (%s): %s", sha[:8], error)
            return (), None

    def _normalize_review_kind(self, github_state: str) -> str:
        """GitHub review state를 ReviewKind로 정규화한다."""
        state = github_state.upper()
        if state == "APPROVED":
            return "approved"
        if state == "CHANGES_REQUESTED":
            return "changes_requested"
        return "commented"

    def _collect_pr_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> tuple[ReviewEvent, ...]:
        """
        PR의 reviews를 조회한다.
        GitHub REST API: /repos/{owner}/{repo}/pulls/{number}/reviews
        """
        try:
            reviews_data = self.client.get_pull_request_reviews(owner, repo, pull_number)
            reviews: list[ReviewEvent] = []
            for review in reviews_data:
                state = review.get("state", "COMMENTED")
                kind_str = self._normalize_review_kind(state)
                kind = cast("ReviewKind", kind_str)
                author_name = review.get("author", {}).get("login", "unknown")
                submitted_at_str = review.get("submittedAt", "")
                try:
                    occurred_at = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    logger.debug("잘못된 review submitted_at: %s", submitted_at_str)
                    continue
                reviews.append(
                    ReviewEvent(
                        kind=kind,
                        actor_name=author_name,
                        occurred_at=occurred_at,
                    )
                )
            return tuple(reviews)
        except Exception as error:
            logger.debug("PR reviews 조회 실패 #%d: %s", pull_number, error)
            return ()

    def _build_merge_request_info(
        self,
        pr_data: dict[str, Any],
        owner: str,
        repo: str,
        repo_web_url: str,
    ) -> MergeRequestInfo:
        """PR 데이터로부터 MergeRequestInfo 객체 생성."""
        from pulse.collector.gitlab import CollectionError

        iid = pr_data.get("number", 0)
        reviews = self._collect_pr_reviews(owner, repo, iid)

        created_at_str = pr_data.get("createdAt", "")
        updated_at_str = pr_data.get("updatedAt", "")
        merged_at_str = pr_data.get("mergedAt")

        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            merged_at = (
                datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
                if merged_at_str
                else None
            )
        except (ValueError, AttributeError) as e:
            raise CollectionError(f"PR datetime 파싱 실패: {e}") from e

        state = _normalize_mr_state(pr_data.get("state", "OPEN"))
        author_data = pr_data.get("author", {})
        author_name = author_data.get("login", "unknown") if author_data else "unknown"

        return MergeRequestInfo(
            iid=iid,
            title=pr_data.get("title", ""),
            state=state,
            is_draft=pr_data.get("isDraft", False),
            labels=(),  # GitHub GraphQL에서 labels 미포함 (REST로 별도 조회 필요, v1.1에서 개선)
            source_branch=pr_data.get("headRefName", ""),
            target_branch=pr_data.get("baseRefName", ""),
            author_name=author_name,
            created_at=created_at,
            updated_at=updated_at,
            merged_at=merged_at,
            reviews=reviews,
            is_external=False,  # GitHub는 항상 external=False (구분 불필요)
            web_url=f"{repo_web_url}/pull/{iid}",
            description=pr_data.get("body"),
        )

    def _filter_active_branches(
        self,
        branches: list[dict[str, Any]],
        lookback_hours: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """
        lookback 시간 내에 push가 있었던 브랜치만 선별.
        각 브랜치의 target.committedDate를 기준.
        """
        since_dt = now - timedelta(hours=lookback_hours)
        active = []
        for branch in branches:
            target = branch.get("target", {})
            committed_date_str = target.get("committedDate")
            if not committed_date_str:
                continue
            try:
                committed_dt = datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
                if committed_dt >= since_dt:
                    active.append(branch)
            except (ValueError, AttributeError):
                logger.debug("잘못된 committedDate: %s", committed_date_str)
                continue
        return active

    def _is_stale_branch(self, branch: dict[str, Any], stale_threshold: datetime) -> bool:
        """
        branchが stale인지 판별한다.
        merged, default 브랜치 제외.
        target.committedDate < stale_threshold이면 True.
        """
        target = branch.get("target", {})
        committed_date_str = target.get("committedDate")
        if not committed_date_str:
            return False
        try:
            committed_dt = datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
            return committed_dt < stale_threshold
        except (ValueError, AttributeError):
            return False

    def _make_stale_branch_info(
        self,
        branch: dict[str, Any],
        repo_web_url: str,
    ) -> BranchInfo:
        """stale 브랜치를 BranchInfo로 변환."""
        target = branch.get("target", {})
        name = branch.get("name", "unknown")
        oid = target.get("oid", "unknown")
        committed_date_str = target.get("committedDate")
        try:
            last_pushed_at = (
                datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
                if committed_date_str
                else None
            )
        except (ValueError, AttributeError):
            last_pushed_at = None

        return BranchInfo(
            name=name,
            last_commit_sha=oid,
            last_pushed_at=last_pushed_at,
            web_url=_fallback_branch_url(repo_web_url, name),
        )

    def _collect_stale_branches(
        self,
        branches: list[dict[str, Any]],
        stale_branch_days: int,
        now: datetime,
        repo_web_url: str,
        default_branch_name: str | None = None,
    ) -> tuple[BranchInfo, ...]:
        """stale 브랜치를 수집한다 (lookback 무관)."""
        stale_threshold = now - timedelta(days=stale_branch_days)
        stale_list = []
        for branch in branches:
            name = branch.get("name", "")
            # default 브랜치 제외
            if default_branch_name and name == default_branch_name:
                continue
            if self._is_stale_branch(branch, stale_threshold):
                stale_list.append(self._make_stale_branch_info(branch, repo_web_url))
        return tuple(stale_list)

    def _build_branch_snapshots(
        self,
        repo: RepoRef,
        branches: list[dict[str, Any]],
        snapshot_dir: Path | None,
        now: datetime,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """스냅샷을 저장하고 created/deleted 브랜치 diff를 계산한다.

        첫 수집 시 created/deleted는 빈값.
        """
        branch_names = {b.get("name", "") for b in branches if b.get("name")}
        snapshot_date = now.date().isoformat()

        if snapshot_dir is None:
            return tuple(branch_names), ()

        # 첫 수집 여부 확인
        snapshot, is_first_collection, previous = load_or_create(
            snapshot_dir, repo.slug, branch_names, snapshot_date
        )

        # 첫 수집이면 created/deleted 모두 빈값
        if is_first_collection:
            logger.info("첫 수집 레포: %s (생성 브랜치 신호 제외)", repo.full_path)
            return (), ()

        # 이후 수집이면 diff 계산
        if previous is None:
            return (), ()

        created, deleted = snapshot.diff_against(previous)
        return tuple(created), tuple(deleted)

    def _run_collection_pipeline(
        self,
        repo: RepoRef,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        snapshot_dir: Path | None,
        stale_branch_days: int,
        now: datetime,
        recent_mr_limit: int = 50,
    ) -> tuple[
        tuple[CommitInfo, ...],
        tuple[BranchInfo, ...],
        tuple[MergeRequestInfo, ...],
        tuple[BranchInfo, ...],
        list[dict[str, Any]],
        tuple[MergeRequestInfo, ...],
    ]:
        """수집 파이프라인 실행 (GraphQL + REST)."""
        from pulse.collector.gitlab import CollectionError

        # GraphQL: 브랜치, PR 조회
        response = self.client.query_repo_activity(repo.namespace, repo.name, 100)
        repo_data = response.get("data", {}).get("repository", {})

        # 브랜치 필터링 (lookback)
        all_branches = repo_data.get("refs", {}).get("nodes", [])
        active_branches_data = self._filter_active_branches(all_branches, lookback_hours, now)

        # 각 활동 브랜치의 커밋 수집
        all_commits = []
        commit_shas = set()
        for branch_data in active_branches_data:
            branch_name = branch_data.get("name", "")
            try:
                since_dt = now - timedelta(hours=lookback_hours)
                commits_data = self.client.query_branch_commits(
                    repo.namespace,
                    repo.name,
                    f"refs/heads/{branch_name}",
                    since_dt.isoformat(),
                )
                ref_data = commits_data.get("data", {}).get("repository", {}).get("ref", {})
                target = ref_data.get("target", {})
                history = target.get("history", {}).get("nodes", [])

                for commit_data in history:
                    sha = commit_data.get("oid", "")
                    if sha in commit_shas:
                        continue
                    commit_shas.add(sha)

                    author_data = commit_data.get("author", {})
                    author_name = author_data.get("name", "unknown") if author_data else "unknown"
                    if not self._should_include_commit(author_name, exclude_bot_authors):
                        continue

                    commit_info = self._build_commit_info(
                        commit_data,
                        branch_name,
                        repo.web_url,
                        repo.namespace,
                        repo.name,
                    )
                    all_commits.append(commit_info)
            except CollectionError as error:
                logger.warning("브랜치 %s 커밋 조회 실패: %s", branch_name, error)
                continue

        commits = tuple(all_commits)

        # 활동 브랜치 정보
        active_branches = tuple(
            BranchInfo(
                name=b.get("name", ""),
                last_commit_sha=b.get("target", {}).get("oid", ""),
                last_pushed_at=datetime.fromisoformat(
                    b.get("target", {}).get("committedDate", "").replace("Z", "+00:00")
                )
                if b.get("target", {}).get("committedDate")
                else None,
                web_url=_fallback_branch_url(repo.web_url, b.get("name", "")),
            )
            for b in active_branches_data
        )

        # PR 조회: openPRs (모두) + recentPRs (lookback 내)의 union
        merge_requests_dict: dict[int, MergeRequestInfo] = {}
        since_dt = now - timedelta(hours=lookback_hours)

        # OPEN PR은 시간 무관
        open_prs_data = repo_data.get("openPRs", {}).get("nodes", [])
        open_page_info = repo_data.get("openPRs", {}).get("pageInfo", {})
        if open_page_info.get("hasNextPage"):
            logger.warning("OpenPR 페이지 상한 도달 — 초과분 미수집 가능 (%s)", repo.full_path)

        for pr_data in open_prs_data:
            author_name = pr_data.get("author", {}).get("login", "unknown")
            if not self._should_include_commit(author_name, exclude_bot_authors):
                continue
            mr_info = self._build_merge_request_info(
                pr_data, repo.namespace, repo.name, repo.web_url
            )
            merge_requests_dict[pr_data.get("number", 0)] = mr_info

        # Recent PR은 lookback 내 갱신분
        recent_prs_data = repo_data.get("recentPRs", {}).get("nodes", [])
        recent_page_info = repo_data.get("recentPRs", {}).get("pageInfo", {})
        if recent_page_info.get("hasNextPage"):
            logger.warning("RecentPR 페이지 상한 도달 — 초과분 미수집 가능 (%s)", repo.full_path)

        for pr_data in recent_prs_data:
            pr_number = pr_data.get("number", 0)
            if pr_number in merge_requests_dict:
                # 이미 openPRs에 포함
                continue
            updated_at_str = pr_data.get("updatedAt", "")
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    # 경계값(updated_at == since_dt)은 포함; lookback 이전은 제외
                    if updated_at < since_dt:
                        # lookback 범위 밖
                        continue
                except (ValueError, AttributeError):
                    pass
            author_name = pr_data.get("author", {}).get("login", "unknown")
            if not self._should_include_commit(author_name, exclude_bot_authors):
                continue
            mr_info = self._build_merge_request_info(
                pr_data, repo.namespace, repo.name, repo.web_url
            )
            merge_requests_dict[pr_number] = mr_info

        merge_requests: tuple[MergeRequestInfo, ...] = tuple(merge_requests_dict.values())

        # pageInfo 체크: branches
        refs_page_info = repo_data.get("refs", {}).get("pageInfo", {})
        if refs_page_info.get("hasNextPage"):
            logger.warning("refs 페이지 상한 도달 — 초과분 미수집 가능 (%s)", repo.full_path)

        # stale 브랜치 감지
        default_branch = repo_data.get("defaultBranchRef", {}).get("name")
        stale_branches = self._collect_stale_branches(
            all_branches, stale_branch_days, now, repo.web_url, default_branch
        )

        # 최근 MR 추출 (recentPRs 데이터 재사용, 추가 API 호출 0회)
        recent_mrs = []
        for pr_data in recent_prs_data[:recent_mr_limit]:
            author_name = pr_data.get("author", {}).get("login", "unknown")
            if not self._should_include_commit(author_name, exclude_bot_authors):
                continue
            mr_info = self._build_merge_request_info(
                pr_data, repo.namespace, repo.name, repo.web_url
            )
            recent_mrs.append(mr_info)

        return (
            commits,
            active_branches,
            merge_requests,
            stale_branches,
            all_branches,
            tuple(recent_mrs),
        )

    def _build_successful_activity(
        self,
        repo: RepoRef,
        commits: tuple[CommitInfo, ...],
        active_branches: tuple[BranchInfo, ...],
        merge_requests: tuple[MergeRequestInfo, ...],
        stale_branches: tuple[BranchInfo, ...],
        created_branches: tuple[str, ...],
        deleted_branches: tuple[str, ...],
        now: datetime,
        recent_merge_requests: tuple[MergeRequestInfo, ...] = (),
    ) -> RepoActivity:
        """성공한 RepoActivity 구성."""
        return RepoActivity(
            repo=repo,
            status="ok",
            failure_reason=None,
            commits=commits,
            active_branches=active_branches,
            created_branches=created_branches,
            deleted_branches=deleted_branches,
            merge_requests=merge_requests,
            recent_merge_requests=recent_merge_requests,
            collected_at=now,
            stale_branches=stale_branches,
        )

    def _build_failed_repo_activity(
        self,
        repo: RepoRef,
        error: Exception,
        now: datetime,
    ) -> RepoActivity:
        """실패한 RepoActivity 구성."""
        return RepoActivity(
            repo=repo,
            status="failed",
            failure_reason=str(error),
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now,
        )

    def collect_repo_activity(
        self,
        repo: RepoRef,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        snapshot_dir: Path | None = None,
        stale_branch_days: int = 7,
        now: datetime | None = None,
        recent_mr_limit: int = 50,
    ) -> RepoActivity:
        """
        GitHub 레포의 활동을 수집한다.

        Args:
            repo: 레포 참조 (provider="github")
            lookback_hours: 조회 범위 (시간 단위)
            exclude_bot_authors: 제외할 봇 author 목록
            snapshot_dir: 브랜치 스냅샷 저장 디렉토리
            stale_branch_days: 정체 브랜치 판별 일 수 (기본 7일)
            now: 기준 시각 (UTC aware datetime)
            recent_mr_limit: 최근 MR 조회 건수 (기본값 50)

        Returns:
            RepoActivity (status="ok" 또는 "failed")
        """

        if now is None:
            now = datetime.now(tz=timezone.utc)

        try:
            (
                commits,
                active_branches,
                merge_requests,
                stale_branches,
                all_branches,
                recent_merge_requests,
            ) = self._run_collection_pipeline(
                repo,
                lookback_hours,
                exclude_bot_authors,
                snapshot_dir,
                stale_branch_days,
                now,
                recent_mr_limit=recent_mr_limit,
            )

            created_branches, deleted_branches = self._build_branch_snapshots(
                repo, all_branches, snapshot_dir, now
            )

            return self._build_successful_activity(
                repo,
                commits,
                active_branches,
                merge_requests,
                stale_branches,
                created_branches,
                deleted_branches,
                now,
                recent_merge_requests=recent_merge_requests,
            )
        except Exception as error:
            logger.exception("GitHub 수집 실패: %s", repo.full_path)
            return self._build_failed_repo_activity(repo, error, now)

    def collect_branch_history(
        self,
        repo: RepoRef,
        branches: tuple[BranchHistoryRequest, ...],
        base_branch_hint: str | None,
        max_commits: int,
    ) -> tuple[BranchHistoryFetch, ...]:
        """분기점부터의 브랜치 히스토리를 수집한다 (github_history 모듈에 위임)."""
        from pulse.collector.github_history import collect_branch_history

        return collect_branch_history(
            self.client,
            repo.namespace,
            repo.name,
            branches,
            base_branch_hint,
            max_commits,
        )
