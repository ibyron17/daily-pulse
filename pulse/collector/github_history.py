"""GitHub 브랜치 생애 히스토리 수집 — 분기점부터의 커밋.

GitLab과 경로가 다르다. GitHub의 `compare/{base}...{head}`는 분기점(merge_base_commit)·
ahead·behind·총 커밋 수를 **한 번에** 주므로 merge_base를 따로 조회하지 않는다.
대신 commits 배열에 상한이 있어(실측: 4591건 중 250건) 초과분은 page로 순회한다.
"""

import logging
from datetime import datetime
from typing import Any

from pulse.collector.base_branch import build_base_candidates, pick_closest_base
from pulse.collector.github_client import GitHubClient
from pulse.collector.http_client import _MAX_PAGES
from pulse.models import BranchHistoryFetch, BranchHistoryRequest, HistoryCommit

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime | None:
    """GitHub의 ISO 시각 문자열을 aware datetime으로 파싱한다 (실패 시 None)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _commit_date(commit_data: dict[str, Any]) -> datetime | None:
    """커밋 응답에서 작업 시각을 뽑는다 (author 우선, committer 폴백).

    committer 시각은 리베이스마다 실행 시각으로 리셋돼 작업 이력을 왜곡한다 —
    gitlab_history와 같은 이유로 authored를 우선한다.
    """
    detail = commit_data.get("commit")
    if not isinstance(detail, dict):
        return None
    for role in ("author", "committer"):
        actor = detail.get(role)
        if isinstance(actor, dict):
            when = _parse_iso(actor.get("date"))
            if when:
                return when
    return None


def _compare(
    client: GitHubClient,
    owner: str,
    repo: str,
    base: str,
    head: str,
    page: int = 1,
) -> dict[str, Any] | None:
    """두 ref를 비교한다 (실패는 조회 불가로 간주하고 None)."""
    from pulse.collector.gitlab import CollectionError

    try:
        return client.compare_refs(owner, repo, base, head, page=page)
    except CollectionError as error:
        logger.debug("compare 실패 (%s...%s): %s", base, head, error)
        return None


def _resolve_base(
    client: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    candidates: tuple[str, ...],
) -> tuple[str, dict[str, Any]] | None:
    """후보들을 비교해 분기점이 가장 최근인 base와 그 compare 결과를 고른다.

    Returns:
        (base 브랜치, compare 응답) 또는 확정 불가 시 None
    """
    found: list[tuple[str, dict[str, Any], datetime]] = []
    for candidate in candidates:
        result = _compare(client, owner, repo, candidate, branch)
        if not result:
            continue
        merge_base = result.get("merge_base_commit")
        if not isinstance(merge_base, dict):
            continue
        branched_at = _commit_date(merge_base)
        if branched_at:
            found.append((candidate, result, branched_at))

    if not found:
        return None

    chosen = pick_closest_base(tuple((name, when) for name, _, when in found))
    match = next((item for item in found if item[0] == chosen), None)
    return (match[0], match[1]) if match else None


def _to_history_commits(
    commits_data: list[dict[str, Any]], merge_base_sha: str | None
) -> tuple[HistoryCommit, ...]:
    """API 응답을 경량 커밋 모델로 변환한다 (분기점 커밋 자체는 제외)."""
    collected = []
    for item in commits_data:
        sha = item.get("sha")
        if not isinstance(sha, str) or sha == merge_base_sha:
            continue
        worked_at = _commit_date(item)
        if not worked_at:
            continue
        detail = item.get("commit")
        message = detail.get("message", "") if isinstance(detail, dict) else ""
        collected.append(
            HistoryCommit(
                sha=sha,
                worked_at=worked_at,
                title=str(message).split("\n", 1)[0].strip(),
            )
        )
    return tuple(collected)


def _collect_commits(
    client: GitHubClient,
    owner: str,
    repo: str,
    base: str,
    branch: str,
    first_result: dict[str, Any],
    max_commits: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    """첫 compare 응답에서 시작해 상한까지 커밋을 모은다.

    Returns:
        (커밋 응답 목록, 실제 총 커밋 수, 절단 여부)
    """
    first_batch = first_result.get("commits")
    collected = list(first_batch) if isinstance(first_batch, list) else []
    raw_total = first_result.get("total_commits")
    total = raw_total if isinstance(raw_total, int) else len(collected)

    page = 2
    while len(collected) < min(total, max_commits) and page <= _MAX_PAGES:
        result = _compare(client, owner, repo, base, branch, page=page)
        batch = result.get("commits") if result else None
        if not isinstance(batch, list) or not batch:
            break
        collected.extend(batch)
        page += 1

    if len(collected) > max_commits:
        logger.warning("수집 상한(%d건) 도달 — 초과분 미수집: %s", max_commits, branch)
        collected = collected[:max_commits]

    return collected, total, len(collected) < total


def _fetch_one(
    client: GitHubClient,
    owner: str,
    repo: str,
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

    resolved = _resolve_base(client, owner, repo, request.branch_name, candidates)
    if not resolved:
        logger.debug("분기점 확정 실패 — 건너뜀: %s", request.branch_name)
        return None
    base_branch, compare_result = resolved

    merge_base = compare_result.get("merge_base_commit")
    merge_base_sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
    commits_data, total, truncated = _collect_commits(
        client, owner, repo, base_branch, request.branch_name, compare_result, max_commits
    )
    behind = compare_result.get("behind_by")

    return BranchHistoryFetch(
        branch_name=request.branch_name,
        base_branch=base_branch,
        merge_base_sha=merge_base_sha if isinstance(merge_base_sha, str) else None,
        head_sha=request.head_sha,
        commits=_to_history_commits(commits_data, merge_base_sha),
        total_commits=total,
        truncated=truncated,
        behind_count=behind if isinstance(behind, int) else None,
    )


def collect_branch_history(
    client: GitHubClient,
    owner: str,
    repo: str,
    requests: tuple[BranchHistoryRequest, ...],
    base_hint: str | None,
    max_commits: int,
) -> tuple[BranchHistoryFetch, ...]:
    """대상 브랜치들의 히스토리를 수집한다.

    브랜치 목록과 default_branch는 레포당 1회만 조회한다.
    개별 브랜치 실패는 그 브랜치만 건너뛴다 — 전체를 중단하지 않는다.

    Args:
        client: GitHub HTTP 클라이언트
        owner: 레포 소유자
        repo: 레포 이름
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
        branches = client.list_branches(owner, repo)
        existing = frozenset(
            name for branch in branches if isinstance(name := branch.get("name"), str)
        )
    except CollectionError as error:
        logger.warning("브랜치 목록 조회 실패 — 히스토리 수집 생략: %s", error)
        return ()

    default_branch: str | None = None
    if not base_hint:
        try:
            info = client.get_repo_info(owner, repo)
            raw_default = info.get("default_branch")
            default_branch = raw_default if isinstance(raw_default, str) else None
        except CollectionError as error:
            logger.debug("default_branch 조회 실패: %s", error)

    fetched = [
        result
        for request in requests
        if (
            result := _fetch_one(
                client,
                owner,
                repo,
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
