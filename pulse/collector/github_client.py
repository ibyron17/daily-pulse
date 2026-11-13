"""GitHub GraphQL + REST API HTTP 클라이언트 (재시도·rate limit 대응)."""

import logging
import time
from typing import Any, cast

import requests

from pulse.collector.http_client import _PAGE_SIZE, RateLimitStats, collect_pages

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub GraphQL + REST API HTTP 클라이언트 (재시도·rate limit 대응)."""

    def __init__(
        self,
        token: str,
        stats: RateLimitStats | None = None,
    ) -> None:
        """
        GitHub API 클라이언트 초기화.

        Args:
            token: GitHub 개인 액세스 토큰 (classic 또는 fine-grained)
            stats: 호출 통계 (선택, 로깅용). 스레드 안전성은 호출자가 보장.
        """
        self.base_url = "https://api.github.com"
        self.token = token
        self.stats = stats or RateLimitStats()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "daily-pulse/0.1",
            }
        )

    def _handle_rate_limit(
        self,
        attempt: int,
        max_retries: int,
        endpoint: str,
    ) -> None:
        """429 rate limit 응답을 처리한다."""
        wait_sec = 2 ** (attempt - 1)
        self.stats.add_rate_limited(wait_sec)
        logger.warning(
            "429 rate limit: %s초 대기 후 재시도 (%d/%d)",
            wait_sec,
            attempt,
            max_retries,
        )
        time.sleep(wait_sec)

    def _handle_rate_limit_graphql(self, remaining: int, reset_at_epoch: int) -> None:
        """GraphQL 응답의 rateLimit 필드(remaining, resetAt) 처리."""
        if remaining < 100:
            wait_sec = reset_at_epoch - int(time.time())
            if wait_sec > 0:
                self.stats.add_rate_limited(wait_sec)
                logger.warning(
                    "GraphQL rate limit 남은 포인트=%d, reset까지 %d초 대기",
                    remaining,
                    wait_sec,
                )
                time.sleep(wait_sec)

    def _handle_response_graphql(
        self,
        resp: requests.Response,
        attempt: int,
        max_retries: int,
    ) -> dict[str, Any] | None:
        """GraphQL 응답을 처리한다."""
        from pulse.collector.gitlab import CollectionError

        if resp.status_code == 200:
            data: dict[str, Any] = resp.json()
            # rate limit 정보 로깅
            if "data" in data and data["data"] is not None:
                repo_data = data.get("data", {})
                if isinstance(repo_data, dict):
                    rate_limit = repo_data.get("rateLimit", {})
                    if rate_limit:
                        remaining = rate_limit.get("remaining", 0)
                        reset_at = rate_limit.get("resetAt", "")
                        logger.debug(
                            "GraphQL rate limit: remaining=%d, resetAt=%s",
                            remaining,
                            reset_at,
                        )
            # errors 확인
            if "errors" in data and data["errors"]:
                raise CollectionError(f"GraphQL errors: {data['errors']}")
            return data
        if resp.status_code == 429:
            self._handle_rate_limit(attempt, max_retries, "GraphQL")
            return None
        msg = f"GraphQL: HTTP {resp.status_code}"
        raise CollectionError(msg)

    def _request_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        GraphQL 쿼리 요청.

        Args:
            query: GraphQL 쿼리 문자열
            variables: 쿼리 변수 (선택)
            max_retries: 재시도 최대 횟수

        Returns:
            응답 JSON dict (data + errors 키)

        Raises:
            CollectionError: 429, 400, 기타 HTTP 에러
        """
        from pulse.collector.gitlab import CollectionError

        url = f"{self.base_url}/graphql"
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=30)
                self.stats.add_request()
                result = self._handle_response_graphql(resp, attempt, max_retries)
                if result is not None:
                    return result
            except requests.RequestException as error:
                msg = f"GraphQL request failed: {error}"
                raise CollectionError(msg) from error

        raise CollectionError(f"GraphQL 최대 재시도 초과: {max_retries}회")

    def _handle_response_rest(
        self,
        resp: requests.Response,
        endpoint: str,
        attempt: int,
        max_retries: int,
    ) -> Any:
        """REST API 응답을 처리한다."""
        from pulse.collector.gitlab import CollectionError

        if resp.status_code in (200, 201):
            logger.debug("REST HTTP 200")
            return resp.json()

        if resp.status_code == 429:
            self._handle_rate_limit(attempt, max_retries, endpoint)
            return None

        msg = f"{endpoint}: HTTP {resp.status_code}"
        raise CollectionError(msg)

    def _request_rest(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Any:
        """
        REST API 요청 (GET/POST 등)을 동기적으로 실행하고 JSON 응답을 반환한다.
        429 응답은 exponential backoff 재시도, 최대 3회.
        X-RateLimit 헤더 로깅.
        실패 시 CollectionError 발생.
        """
        from pulse.collector.gitlab import CollectionError

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.request(method, url, params=params, timeout=30)
                # X-RateLimit 헤더 로깅
                remaining = resp.headers.get("X-RateLimit-Remaining", "N/A")
                reset_val = resp.headers.get("X-RateLimit-Reset", "N/A")
                logger.debug(
                    "REST rate limit: remaining=%s, reset=%s",
                    remaining,
                    reset_val,
                )
                self.stats.add_request()
                result = self._handle_response_rest(resp, endpoint, attempt, max_retries)
                if result is not None:
                    return result
            except requests.RequestException as error:
                msg = f"{endpoint}: {error}"
                raise CollectionError(msg) from error

        raise CollectionError(f"최대 재시도 초과: {endpoint}")

    def _request_dict(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HTTP 응답을 dict로 타입 캐스팅."""
        return cast(dict[str, Any], self._request_rest(method, endpoint, params))

    def _request_list(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """HTTP 응답을 list[dict]로 타입 캐스팅."""
        return cast(list[dict[str, Any]], self._request_rest(method, endpoint, params))

    def _paginate_rest(
        self,
        endpoint: str,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """REST 목록을 페이지 순회로 모은다 (GitLab 쪽과 같은 공통 로직 사용)."""

        def fetch_page(page: int) -> list[dict[str, Any]]:
            return self._request_list(
                "GET", endpoint, {**params, "per_page": _PAGE_SIZE, "page": page}
            )

        return collect_pages(fetch_page, endpoint, max_items)

    def get_repo_info(self, owner: str, repo: str) -> dict[str, Any]:
        """레포 정보 조회 (REST: GET /repos/{owner}/{repo})."""
        endpoint = f"repos/{owner}/{repo}"
        return self._request_dict("GET", endpoint)

    def list_branches(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """브랜치 목록 조회 (REST). 응답 필드: name, commit (sha, url), protected."""
        items, _ = self._paginate_rest(f"repos/{owner}/{repo}/branches", {})
        return items

    def compare_refs(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
        page: int = 1,
    ) -> dict[str, Any]:
        """두 ref를 비교한다 (REST: GET /repos/{o}/{r}/compare/{base}...{head}).

        응답 필드: merge_base_commit, ahead_by, behind_by, total_commits, commits, files.
        GitLab과 달리 분기점·ahead·behind를 **한 번에** 준다.

        주의(실측 확인): commits 배열에는 상한이 있다(per_page 미지정 시 250).
        total_commits가 실제 총계이므로 초과분은 page로 순회해야 한다.
        files도 300건 상한이 있어 파일 지표에는 쓰지 않는다.
        """
        endpoint = f"repos/{owner}/{repo}/compare/{base}...{head}"
        return self._request_dict("GET", endpoint, {"per_page": _PAGE_SIZE, "page": page})

    def get_commit_changed_files(self, owner: str, repo: str, sha: str) -> list[dict[str, Any]]:
        """커밋의 변경 파일 조회 (REST: GET /repos/{owner}/{repo}/commits/{sha})."""
        endpoint = f"repos/{owner}/{repo}/commits/{sha}"
        response = self._request_dict("GET", endpoint)
        # 응답에 files 배열이 있음
        files = response.get("files", [])
        return cast(list[dict[str, Any]], files)

    def get_pull_request_reviews(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> list[dict[str, Any]]:
        """PR의 reviews 조회 (REST: GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews)."""
        endpoint = f"repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        return self._request_list("GET", endpoint, {"per_page": 100})

    def query_repo_activity(self, owner: str, name: str, first: int) -> dict[str, Any]:
        """레포의 브랜치, PR, 기본 브랜치 정보를 GraphQL로 조회한다."""
        from pulse.collector.github import _GITHUB_REPO_ACTIVITY_QUERY

        variables = {"owner": owner, "name": name, "first": first}
        return self._request_graphql(_GITHUB_REPO_ACTIVITY_QUERY, variables)

    def query_branch_commits(
        self, owner: str, name: str, ref_name: str, since_iso: str
    ) -> dict[str, Any]:
        """브랜치의 커밋 히스토리를 GraphQL로 조회한다."""
        from pulse.collector.github import _GITHUB_BRANCH_COMMITS_QUERY

        variables = {
            "owner": owner,
            "name": name,
            "refName": ref_name,
            "after_date": since_iso,
        }
        return self._request_graphql(_GITHUB_BRANCH_COMMITS_QUERY, variables)
