"""GitLab 브랜치 생애 히스토리 수집 — 분기점(merge_base)부터의 커밋.

gitlab.py에서 분리한 이유: 그 파일이 이미 800행 상한에 닿아 있고, 히스토리 수집은
lookback 창 수집과 관심사가 다르다(창 산출물이 아니라 브랜치 단위 누적).

조회 전략(실측 근거, 2026-07-27 정정): `compare(base, branch)`의 commits를 쓴다.

처음에는 "compare_timeout=True이므로 잘린다"고 보고 `merge_base` + `commits?since=분기일`을
썼으나 **틀렸다.** 실측 비교 결과:

  merge_base(develop, X) = 07-09 → since 방식 82건 (07-09~)
  compare(develop, X)                    = 211건 (05-27~)  ← 130건 차이

`merge_base`는 "처음 갈라진 지점"이 아니라 **마지막으로 base를 머지한 지점**이다.
브랜치가 base를 주기적으로 동기화하면 그 이전 작업이 전부 시간 필터에서 빠진다.
반대로 base에서 흘러든 커밋이 섞여 들어오기도 한다(실측 1건).
`compare_timeout`은 **diffs만** 자르며 commits는 온전하다.

merge_base는 base 후보를 고르는 데만 쓴다(빠르고, 후보 간 비교에는 충분하다).

커밋 시각은 `authored_date` 우선이다(2026-07-30 정정). `committed_date`는 리베이스마다
전 커밋이 실행 시각으로 리셋돼 시작일·활동일·추이가 리베이스 날짜로 왜곡된다
(실측: 7/7 시작 브랜치가 두 번의 리베이스로 "7/24 시작 · 활동 2일"로 표시).
compare가 이미 브랜치 고유 커밋만 주므로 authored가 곧 실제 작업 시각이다.
"""

import logging
from datetime import datetime
from typing import Any

from pulse.collector.base_branch import build_base_candidates, pick_closest_base
from pulse.collector.http_client import GitLabClient
from pulse.models import BranchHistoryFetch, BranchHistoryRequest, HistoryCommit

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime | None:
    """GitLab의 ISO 시각 문자열을 aware datetime으로 파싱한다 (실패 시 None)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _merge_base_of(
    client: GitLabClient, project_id: str, ref_a: str, ref_b: str
) -> dict[str, Any] | None:
    """두 ref의 공통 조상을 조회한다 (실패는 조회 불가로 간주하고 None)."""
    from pulse.collector.gitlab import CollectionError

    try:
        return client.get_merge_base(project_id, ref_a, ref_b)
    except CollectionError as error:
        logger.debug("merge_base 조회 실패 (%s..%s): %s", ref_a, ref_b, error)
        return None


def _resolve_base(
    client: GitLabClient,
    project_id: str,
    branch: str,
    candidates: tuple[str, ...],
) -> tuple[str, str, datetime] | None:
    """후보들의 분기점을 조회해 가장 최근인 base를 고른다.

    Returns:
        (base 브랜치, merge_base SHA, 분기 시각) 또는 확정 불가 시 None
    """
    found: list[tuple[str, str, datetime]] = []
    for candidate in candidates:
        data = _merge_base_of(client, project_id, candidate, branch)
        if not data:
            continue
        sha = data.get("id")
        branched_at = _parse_iso(data.get("committed_date"))
        if isinstance(sha, str) and branched_at:
            found.append((candidate, sha, branched_at))

    if not found:
        return None

    chosen = pick_closest_base(tuple((name, when) for name, _, when in found))
    return next((item for item in found if item[0] == chosen), None)


def _compare_commits(
    client: GitLabClient, project_id: str, base: str, branch: str
) -> list[dict[str, Any]] | None:
    """base 대비 브랜치 고유 커밋을 조회한다 (실패 시 None).

    compare 응답의 diffs는 compare_timeout으로 잘릴 수 있지만 commits는 온전하다.
    diffs를 빼는 파라미터가 없어 응답이 무겁다(실측 9.6초) — 브랜치당 1회이고
    증분 캐시로 두 번째 실행부터는 호출되지 않으므로 정확성을 택했다.
    """
    from pulse.collector.gitlab import CollectionError

    try:
        result = client.compare_refs(project_id, base, branch)
    except CollectionError as error:
        logger.warning("히스토리 compare 실패 (%s): %s", branch, error)
        return None
    commits = result.get("commits")
    return commits if isinstance(commits, list) else []


def _count_behind(client: GitLabClient, project_id: str, branch: str, base: str) -> int | None:
    """base가 브랜치보다 앞서 있는 커밋 수를 센다 (역방향 compare).

    "병합 가능한 상태인가"를 보여주는 실질 신호다. 실측 0.14~0.76초 — 이 방향은
    diffs가 거의 없어 빠르다.
    """
    from pulse.collector.gitlab import CollectionError

    try:
        result = client.compare_refs(project_id, branch, base)
    except CollectionError as error:
        logger.debug("behind 계산 실패 (%s): %s", branch, error)
        return None
    commits = result.get("commits")
    return len(commits) if isinstance(commits, list) else None


def _to_history_commits(
    commits_data: list[dict[str, Any]], merge_base_sha: str
) -> tuple[HistoryCommit, ...]:
    """API 응답을 경량 커밋 모델로 변환한다.

    merge_base 커밋 자체는 제외한다 — `since`가 분기 시각을 포함할 수 있어
    남겨두면 분기 이전 활동이 브랜치 작업으로 집계된다.
    """
    collected = []
    for item in commits_data:
        sha = item.get("id")
        if not isinstance(sha, str) or sha == merge_base_sha:
            continue
        worked_at = _parse_iso(item.get("authored_date")) or _parse_iso(item.get("committed_date"))
        if not worked_at:
            continue
        message = item.get("message") or item.get("title") or ""
        collected.append(
            HistoryCommit(
                sha=sha,
                worked_at=worked_at,
                title=str(message).split("\n", 1)[0].strip(),
            )
        )
    return tuple(collected)


def _fetch_one(
    client: GitLabClient,
    project_id: str,
    request: BranchHistoryRequest,
    base_hint: str | None,
    existing_branches: frozenset[str],
    default_branch: str | None,
    max_commits: int,
) -> BranchHistoryFetch | None:
    """브랜치 하나의 히스토리를 수집한다 (확정 불가·실패 시 None)."""
    candidates = build_base_candidates(
        request.branch_name, base_hint, existing_branches, default_branch
    )
    if not candidates:
        logger.debug("base 후보 없음 — 건너뜀: %s", request.branch_name)
        return None

    resolved = _resolve_base(client, project_id, request.branch_name, candidates)
    if not resolved:
        logger.debug("분기점 확정 실패 — 건너뜀: %s", request.branch_name)
        return None
    base_branch, merge_base_sha, _branched_at = resolved

    commits_data = _compare_commits(client, project_id, base_branch, request.branch_name)
    if commits_data is None:
        return None

    commits = _to_history_commits(commits_data, merge_base_sha)
    total_commits = len(commits)
    truncated = total_commits > max_commits
    if truncated:
        logger.warning(
            "집계 상한(%d건) 초과 — 최근 구간만 집계: %s (총 %d건)",
            max_commits,
            request.branch_name,
            total_commits,
        )
        commits = tuple(sorted(commits, key=lambda commit: commit.worked_at)[-max_commits:])

    return BranchHistoryFetch(
        branch_name=request.branch_name,
        base_branch=base_branch,
        merge_base_sha=merge_base_sha,
        head_sha=request.head_sha,
        commits=commits,
        total_commits=total_commits,
        truncated=truncated,
        behind_count=_count_behind(client, project_id, request.branch_name, base_branch),
    )


def collect_branch_history(
    client: GitLabClient,
    project_id: str,
    requests: tuple[BranchHistoryRequest, ...],
    base_hint: str | None,
    max_commits: int,
) -> tuple[BranchHistoryFetch, ...]:
    """대상 브랜치들의 히스토리를 수집한다.

    브랜치 목록과 default_branch는 레포당 1회만 조회한다(base 후보의 존재 확인용).
    개별 브랜치 실패는 그 브랜치만 건너뛴다 — 전체를 중단하지 않는다.

    Args:
        client: GitLab HTTP 클라이언트
        project_id: URL-encoded 프로젝트 ID
        requests: 조회 대상 (브랜치명, head SHA)
        base_hint: config에 지정된 base 브랜치 (선택)
        max_commits: 브랜치당 커밋 수집 상한

    Returns:
        수집 성공한 브랜치들의 조회 결과
    """
    from pulse.collector.gitlab import CollectionError

    if not requests:
        return ()

    try:
        branches = client.list_branches(project_id)
        existing = frozenset(
            name for branch in branches if isinstance(name := branch.get("name"), str)
        )
    except CollectionError as error:
        logger.warning("브랜치 목록 조회 실패 — 히스토리 수집 생략: %s", error)
        return ()

    default_branch: str | None = None
    if not base_hint:
        try:
            project = client.get_project(project_id)
            raw_default = project.get("default_branch")
            default_branch = raw_default if isinstance(raw_default, str) else None
        except CollectionError as error:
            logger.debug("default_branch 조회 실패: %s", error)

    fetched = [
        result
        for request in requests
        if (
            result := _fetch_one(
                client,
                project_id,
                request,
                base_hint,
                existing,
                default_branch,
                max_commits,
            )
        )
        is not None
    ]
    return tuple(fetched)
