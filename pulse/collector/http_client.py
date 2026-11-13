"""HTTP 요청 재시도, rate limit 대응, 로깅."""

import logging
import time
from collections.abc import Callable
from typing import Any, cast

import requests

logger = logging.getLogger(__name__)

# 페이지당 조회 크기. _paginate가 이 크기로 순회하며, 받은 건수가 이보다 적으면 마지막 페이지다.
_PAGE_SIZE = 100
_MAX_PAGES = 50  # 무한 순회 방지 안전장치 (최대 5000건)


def collect_pages(
    fetch_page: Callable[[int], list[dict[str, Any]]],
    endpoint: str,
    max_items: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """페이지를 순회해 목록 전체를 모은다 (provider 공통 로직).

    마지막 페이지 판정은 **응답 길이 기반**이다(받은 건수 < _PAGE_SIZE).
    X-Next-Page 같은 헤더에 의존하지 않으므로 응답 헤더를 버리는 요청 구조를
    바꾸지 않아도 되고, GitLab/GitHub의 헤더 차이도 흡수한다.

    Args:
        fetch_page: 페이지 번호(1부터)를 받아 항목 목록을 반환하는 함수
        endpoint: 경고 로그에 남길 대상 표시
        max_items: 수집 상한 (None이면 페이지 상한까지)

    Returns:
        (수집된 항목, 상한으로 절단됐는지) — 절단은 조용히 넘기지 않고 경고를 남긴다
    """
    collected: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        batch = fetch_page(page)
        collected.extend(batch)
        if max_items is not None and len(collected) >= max_items:
            logger.warning("수집 상한(%d건) 도달 — 초과분 미수집: %s", max_items, endpoint)
            return collected[:max_items], True
        if len(batch) < _PAGE_SIZE:
            return collected, False

    logger.warning("페이지 상한(%d페이지) 도달 — 초과분 미수집: %s", _MAX_PAGES, endpoint)
    return collected, True


class RateLimitStats:
    """API 호출 통계. 스레드별 독립 관리, 완료 후 합산."""

    def __init__(self) -> None:
        self.total_requests: int = 0
        self.rate_limited_count: int = 0
        self.total_wait_time: float = 0.0

    def add_request(self) -> None:
        """요청 횟수 증가 (호출자가 Lock 또는 단일 스레드 보장)."""
        self.total_requests += 1

    def add_rate_limited(self, wait_sec: float) -> None:
        """429 응답 기록 (호출자가 Lock 또는 단일 스레드 보장)."""
        self.rate_limited_count += 1
        self.total_wait_time += wait_sec


class GitLabClient:
    """GitLab REST API v4 HTTP 클라이언트 (재시도·rate limit 대응)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        stats: RateLimitStats | None = None,
    ) -> None:
        """
        GitLab API 클라이언트 초기화.

        Args:
            base_url: "https://gitlab.example.com/"
            token: PRIVATE-TOKEN 헤더 값
            stats: 호출 통계 (선택, 로깅용). 스레드 안전성은 호출자가 보장.
        """
        self.base_url = base_url
        self.token = token
        self.stats = stats or RateLimitStats()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "PRIVATE-TOKEN": token,
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

    def _handle_response(
        self,
        resp: requests.Response,
        endpoint: str,
        attempt: int,
        max_retries: int,
    ) -> Any:
        """HTTP 응답을 처리한다."""
        from pulse.collector.gitlab import CollectionError

        if resp.status_code in (200, 201):
            logger.debug("HTTP 200")
            return resp.json()

        if resp.status_code == 429:
            self._handle_rate_limit(attempt, max_retries, endpoint)
            return None

        msg = f"{endpoint}: HTTP {resp.status_code}"
        raise CollectionError(msg)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Any:
        """
        HTTP 요청 (GET/POST 등)을 동기적으로 실행하고 JSON 응답을 반환한다.
        429 응답은 exponential backoff 재시도, 최대 3회.
        실패 시 CollectionError 발생.
        """
        from pulse.collector.gitlab import CollectionError

        url = f"{self.base_url}/api/v4/{endpoint.lstrip('/')}"
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.request(method, url, params=params, timeout=30)
                self.stats.add_request()
                result = self._handle_response(resp, endpoint, attempt, max_retries)
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
        return cast(dict[str, Any], self._request(method, endpoint, params))

    def _request_list(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """HTTP 응답을 list[dict]로 타입 캐스팅."""
        return cast(list[dict[str, Any]], self._request(method, endpoint, params))

    def _paginate(
        self,
        endpoint: str,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """페이지를 순회해 목록 전체를 모은다.

        마지막 페이지 판정은 **응답 길이 기반**이다(받은 건수 < per_page).
        X-Next-Page 헤더에 의존하지 않으므로 응답 헤더를 버리는 _request 구조를
        바꾸지 않아도 되고, provider 간 헤더 차이도 흡수한다.

        Args:
            endpoint: API 경로
            params: 쿼리 파라미터 (per_page·page는 이 메서드가 채운다)
            max_items: 수집 상한 (None이면 페이지 상한까지)

        Returns:
            (수집된 항목, 상한으로 절단됐는지) — 절단은 조용히 넘기지 않고 경고를 남긴다
        """

        def fetch_page(page: int) -> list[dict[str, Any]]:
            return self._request_list(
                "GET", endpoint, params={**params, "per_page": _PAGE_SIZE, "page": page}
            )

        return collect_pages(fetch_page, endpoint, max_items)

    def _paginate_items(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """페이지를 순회해 항목만 반환한다 (절단 여부가 필요 없는 호출부용)."""
        items, _ = self._paginate(endpoint, params)
        return items

    def get_version(self) -> str:
        """GitLab 버전을 조회한다. 응답: {"version": "16.7.0", ...}"""
        resp = self._request_dict("GET", "/version")
        return cast(str, resp.get("version", "unknown"))

    def list_branches(self, project_id: str) -> list[dict[str, Any]]:
        """
        브랜치 목록을 조회한다.
        응답 필드: name, commit (id, committed_date), web_url, ...
        """
        return self._paginate_items(f"projects/{project_id}/repository/branches", params={})

    def list_commits(
        self,
        project_id: str,
        ref: str,
        since_iso: str,
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        지정 브랜치의 커밋을 조회한다.
        응답 필드: id (sha), author_name, authored_date, message, web_url, ...
        path를 주면 그 경로를 건드린 커밋만 서버가 걸러 준다(GitLab 공식 지원).
        path가 None이면 쿼리에 키 자체를 넣지 않는다 — 기존 레포의 요청
        쿼리스트링이 바이트 단위로 동일해야 회귀가 없다.
        """
        params: dict[str, Any] = {"ref_name": ref, "since": since_iso}
        if path is not None:
            params["path"] = path
        return self._paginate_items(
            f"projects/{project_id}/repository/commits",
            params=params,
        )

    def get_commit_diff(self, project_id: str, sha: str) -> list[dict[str, Any]]:
        """
        커밋의 변경 파일 목록을 조회한다.
        응답 필드 (각 파일): new_path, old_path, ...
        """
        return self._request_list("GET", f"projects/{project_id}/repository/commits/{sha}/diff")

    def get_merge_request_changes(self, project_id: str, mr_iid: int) -> list[dict[str, Any]]:
        """
        MR의 변경 파일 목록을 조회한다. 응답의 changes 배열만 반환한다.
        응답 필드 (각 changes 항목): new_path, old_path, ...

        구버전 GitLab에도 있는 /changes 엔드포인트를 쓴다 (신버전 전용 /diffs가 아니다).
        """
        resp = self._request_dict("GET", f"projects/{project_id}/merge_requests/{mr_iid}/changes")
        return cast(list[dict[str, Any]], resp.get("changes", []))

    def list_merge_requests(
        self,
        project_id: str,
        updated_after_iso: str,
    ) -> list[dict[str, Any]]:
        """
        시간 범위 내 MR을 조회한다.
        응답 필드: iid, title, state (opened/merged/closed), web_url, author (username, ...),
                 source_branch, target_branch, created_at, updated_at, merged_at,
                 draft, work_in_progress, labels, ...
        """
        return self._paginate_items(
            f"projects/{project_id}/merge_requests",
            params={"updated_after": updated_after_iso, "state": "all"},
        )

    def list_open_merge_requests(self, project_id: str) -> list[dict[str, Any]]:
        """
        모든 오픈 MR을 조회한다 (시간 범위 제한 없음).
        응답 필드는 list_merge_requests와 동일.
        """
        return self._paginate_items(
            f"projects/{project_id}/merge_requests",
            params={"state": "opened"},
        )

    def get_merge_request_notes(self, project_id: str, mr_iid: int) -> list[dict[str, Any]]:
        """
        MR의 노트(댓글/코멘트)를 조회한다.
        응답 필드: author (username, name, ...), created_at, system, ...
        """
        return self._paginate_items(
            f"projects/{project_id}/merge_requests/{mr_iid}/notes", params={}
        )

    def get_merge_request_approvals(
        self,
        project_id: str,
        mr_iid: int,
    ) -> dict[str, Any]:
        """
        MR의 승인 정보를 조회한다 (선택, 버전 의존).
        응답 필드: approved_by ([user (username, name, ...), ...]), ...
        버전 미지원 시 빈 dict 반환 (호출자가 폴백 처리).
        """
        from pulse.collector.gitlab import CollectionError

        try:
            return self._request_dict(
                "GET", f"projects/{project_id}/merge_requests/{mr_iid}/approvals"
            )
        except CollectionError as error:
            # 구버전 서버나 EE 비활성화 시 폴백
            logger.debug("승인 API 미지원: %s", error)
            return {}

    def list_recent_merge_requests(
        self,
        project_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        최근 N개 MR을 조회한다 (state=all, order_by=updated_at, sort=desc).
        응답 필드는 list_merge_requests와 동일.
        """
        return self._request_list(
            "GET",
            f"projects/{project_id}/merge_requests",
            params={"state": "all", "order_by": "updated_at", "sort": "desc", "per_page": limit},
        )

    def get_project(self, project_id: str) -> dict[str, Any]:
        """프로젝트 정보를 조회한다. 응답 필드: default_branch, path_with_namespace, ..."""
        return self._request_dict("GET", f"projects/{project_id}")

    def get_merge_base(self, project_id: str, ref_a: str, ref_b: str) -> dict[str, Any]:
        """두 ref의 공통 조상 커밋을 조회한다.

        응답 필드: id (sha), committed_date, ...
        구버전 GitLab에서도 동작을 실측 확인했다.
        """
        return self._request_dict(
            "GET",
            f"projects/{project_id}/repository/merge_base",
            params={"refs[]": [ref_a, ref_b]},
        )

    def compare_refs(self, project_id: str, from_ref: str, to_ref: str) -> dict[str, Any]:
        """두 ref를 비교한다. 응답 필드: commits, diffs, compare_timeout, ...

        주의: diffs는 compare_timeout으로 잘릴 수 있어(실측 확인) 파일 지표에 쓰지 않는다.
        커밋 수 계산(behind) 용도로만 사용한다.
        """
        return self._request_dict(
            "GET",
            f"projects/{project_id}/repository/compare",
            params={"from": from_ref, "to": to_ref},
        )
