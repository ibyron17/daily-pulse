"""GitLab/GitHub API 수집 계층 (Phase 2에서 구현). 외부 I/O 전담."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from pulse.collector.gitlab import CollectionError, GitLab
from pulse.collector.http_client import RateLimitStats
from pulse.config import Config
from pulse.models import (
    BranchHistoryFetch,
    BranchHistoryRequest,
    RepoActivity,
    RepoRef,
)
from pulse.secrets import missing_token_hint, resolve_token

logger = logging.getLogger(__name__)

__all__ = ["collect_repos", "CollectionError", "missing_tokens"]


def missing_tokens(config: Config) -> tuple[str, ...]:
    """
    config의 repos를 기반으로 누락된 토큰의 환경변수명 tuple을 반환한다.

    토큰 확인은 계층 폴백(env → keyring → gh)으로 수행된다.
    GitLab 레포가 있으면 GITLAB_TOKEN, GitHub 레포가 있으면 GITHUB_TOKEN 확인.
    """
    missing: list[str] = []

    if any(repo.provider == "gitlab" for repo in config.repos) and not resolve_token("gitlab"):
        missing.append("GITLAB_TOKEN")

    if any(repo.provider == "github" for repo in config.repos) and not resolve_token("github"):
        missing.append("GITHUB_TOKEN")

    return tuple(missing)


def _build_failed_activity(repo: RepoRef, error: Exception, now: datetime) -> RepoActivity:
    """실패한 레포 활동을 구성한다."""
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


def _log_collection_success(
    repo: RepoRef,
    activity: RepoActivity,
    stats: RateLimitStats,
) -> None:
    """수집 성공 로깅."""
    logger.info(
        "수집 완료: %s (커밋=%d, MR=%d, 요청=%d)",
        repo.full_path,
        len(activity.commits),
        len(activity.merge_requests),
        stats.total_requests,
    )


def _build_provider(repo: RepoRef, token: str, stats: RateLimitStats) -> Any:
    """레포의 provider 구현체를 만든다 (GitProvider 프로토콜 준수)."""
    if repo.provider == "github":
        from pulse.collector.github import GitHub

        return GitHub(token=token, stats=stats)
    if repo.provider == "gitlab":
        return GitLab(base_url=repo.base_url, token=token, stats=stats)
    raise CollectionError(f"알 수 없는 provider: {repo.provider}")


def _resolve_provider_tokens(config: Config) -> dict[str, str]:
    """설정에 쓰인 provider들의 토큰을 계층 폴백(env → keyring → gh)으로 로드한다."""
    tokens: dict[str, str] = {}
    for provider in ("gitlab", "github"):
        if any(repo.provider == provider for repo in config.repos):
            token = resolve_token(provider)
            if token:
                tokens[provider] = token
    return tokens


def _collect_single_repo(
    repo: RepoRef,
    tokens: dict[str, str],
    config: Config,
    now: datetime,
    save_snapshots: bool = True,
) -> tuple[RepoActivity, RateLimitStats]:
    """레포 하나를 수집한다. 스레드별 독립 통계 관리."""
    thread_stats = RateLimitStats()
    try:
        token = tokens.get(repo.provider)
        if not token:
            raise CollectionError(f"토큰 미설정: {repo.provider}")

        snapshot_dir = (config.data_dir / "snapshots") if save_snapshots else None

        provider = _build_provider(repo, token, thread_stats)
        activity = provider.collect_repo_activity(
            repo=repo,
            lookback_hours=config.lookback_hours,
            exclude_bot_authors=config.exclude_bot_authors,
            snapshot_dir=snapshot_dir,
            stale_branch_days=config.stagnation.no_push_days,
            now=now,
        )
        _log_collection_success(repo, activity, thread_stats)
        return activity, thread_stats
    except Exception as error:
        # 레포 단위 격리 경계 — 예상 못한 오류도 failed로 격리하고 파이프라인 계속
        logger.exception("수집 실패 (예외): %s", repo.full_path)
        failed_activity = _build_failed_activity(repo, error, now)
        return failed_activity, thread_stats


def _aggregate_stats(
    all_stats: RateLimitStats,
    thread_stats: RateLimitStats,
) -> None:
    """스레드별 통계를 최종 통계에 합산한다."""
    all_stats.total_requests += thread_stats.total_requests
    all_stats.rate_limited_count += thread_stats.rate_limited_count
    all_stats.total_wait_time += thread_stats.total_wait_time


def _log_collection_summary(
    all_stats: RateLimitStats,
    activity_count: int,
) -> None:
    """수집 완료 통계를 로깅한다."""
    logger.info(
        "수집 통계: 레포=%d, 요청=%d, 429_응답=%d, 대기=%.1fs",
        activity_count,
        all_stats.total_requests,
        all_stats.rate_limited_count,
        all_stats.total_wait_time,
    )


def _run_collection_pool(
    config: Config,
    tokens: dict[str, str],
    now: datetime,
    save_snapshots: bool = True,
) -> tuple[list[RepoActivity], RateLimitStats]:
    """ThreadPoolExecutor로 병렬 수집 (동시성 5), 통계 누적."""
    activities = []
    all_stats = RateLimitStats()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_collect_single_repo, repo, tokens, config, now, save_snapshots): repo
            for repo in config.repos
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                activity, thread_stats = future.result()
                activities.append(activity)
                _aggregate_stats(all_stats, thread_stats)
            except Exception as error:
                # 스레드 풀 경계 — 예상 못한 오류도 레포 단위로 격리하고,
                # 해당 레포가 대시보드에서 사라지지 않도록 "수집 실패"로 남긴다
                logger.exception("스레드 오류 (%s)", repo.full_path)
                activities.append(_build_failed_activity(repo, error, now))

    return activities, all_stats


def collect_repos(
    config: Config,
    now: datetime | None = None,
    save_snapshots: bool = True,
) -> list[RepoActivity]:
    """
    config.repos를 수집해 RepoActivity 목록을 반환한다.

    레포별로 ThreadPoolExecutor로 병렬 처리 (동시성 5).
    필요한 provider별 토큰을 계층 폴백(env → keyring → gh)으로 로드.
    일부 레포 실패는 status="failed" 항목으로 반환 (파이프라인 계속).

    Args:
        config: 설정
        now: 기준 시각 (UTC aware datetime, None이면 현재 시각 사용)
        save_snapshots: False면 BranchSnapshot 미생성 (ad-hoc 모드)

    Returns:
        RepoActivity 목록
    """
    # 누락된 토큰 체크 (계층 폴백: env → keyring → gh)
    missing = missing_tokens(config)
    if missing:
        raise CollectionError(missing_token_hint(missing))

    # 필요한 토큰 로드 (계층 폴백: env → keyring → gh)
    tokens = _resolve_provider_tokens(config)

    if now is None:
        now = datetime.now(tz=timezone.utc)

    activities, all_stats = _run_collection_pool(config, tokens, now, save_snapshots=save_snapshots)
    _log_collection_summary(all_stats, len(activities))
    return activities


def collect_histories(
    config: Config,
    requests_by_repo: dict[str, tuple[BranchHistoryRequest, ...]],
    max_commits: int,
) -> dict[str, tuple[BranchHistoryFetch, ...]]:
    """레포별 브랜치 생애 히스토리를 수집한다.

    순차 처리한다 — 증분 캐시 덕에 두 번째 실행부터 조회 대상이 통상 0~수 건이고
    첫 실행만 무겁다. 병렬화는 실제 지연이 측정된 뒤에 도입한다(측정 없는 최적화 금지).

    레포 단위로 실패를 격리한다 — 한 레포의 실패가 다른 레포를 막지 않는다.

    Args:
        config: 설정
        requests_by_repo: 레포 full_path → 조회 대상 브랜치들
        max_commits: 브랜치당 커밋 수집 상한

    Returns:
        레포 full_path → 조회 결과 (실패·대상 없음은 키가 생기지 않는다)
    """
    tokens = _resolve_provider_tokens(config)
    results: dict[str, tuple[BranchHistoryFetch, ...]] = {}

    for repo in config.repos:
        requests = requests_by_repo.get(repo.full_path) or ()
        if not requests:
            continue
        token = tokens.get(repo.provider)
        if not token:
            logger.warning("토큰 미설정으로 히스토리 수집 생략: %s", repo.full_path)
            continue
        try:
            provider = _build_provider(repo, token, RateLimitStats())
            results[repo.full_path] = provider.collect_branch_history(
                repo=repo,
                branches=requests,
                base_branch_hint=repo.base_branch,
                max_commits=max_commits,
            )
        except Exception as error:  # noqa: BLE001 — 레포 단위 격리 경계
            logger.warning("브랜치 히스토리 수집 실패 (%s): %s", repo.full_path, error)

    return results
