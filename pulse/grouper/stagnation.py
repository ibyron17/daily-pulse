"""정체 감지 (stale MR/branch, revert/hotfix)."""

from datetime import datetime

from pulse.config.loader import StagnationThresholds
from pulse.models import BranchInfo, CommitInfo, FeatureGroup, MergeRequestInfo, WarningSignal


def detect_stale_mr(
    mr: MergeRequestInfo,
    now: datetime,
    threshold_days: int,
    repo_full_path: str | None = None,
) -> WarningSignal | None:
    """open MR이 N일 이상 업데이트되지 않은 경우."""
    if mr.state != "open":
        return None

    days_open = (now - mr.updated_at).days
    if days_open >= threshold_days:
        return WarningSignal(
            kind="stale_mr",
            title=mr.title,
            description=f"리뷰 대기 중: {days_open}일",
            days=days_open,
            web_url=mr.web_url,
            repo_full_path=repo_full_path,
        )
    return None


def detect_stale_branch(
    branch: BranchInfo,
    now: datetime,
    threshold_days: int,
    repo_full_path: str | None = None,
) -> WarningSignal | None:
    """push가 없거나 N일 이상 업데이트되지 않은 브랜치."""
    if branch.last_pushed_at is None:
        # last_pushed_at=None인 경우 days=None, 신호는 생성
        return WarningSignal(
            kind="stale_branch",
            title=branch.name,
            description="마지막 push 시각 정보 없음",
            days=None,
            web_url=branch.web_url,
            repo_full_path=repo_full_path,
        )

    days_since_push = (now - branch.last_pushed_at).days
    if days_since_push >= threshold_days:
        return WarningSignal(
            kind="stale_branch",
            title=branch.name,
            description=f"push 없음: {days_since_push}일",
            days=days_since_push,
            web_url=branch.web_url,
            repo_full_path=repo_full_path,
        )
    return None


def _find_revert_signal(
    commits: tuple[CommitInfo, ...], repo_full_path: str | None = None
) -> WarningSignal | None:
    """revert 커밋을 찾아 신호를 생성한다 (case-insensitive)."""
    for commit in commits:
        if "revert" in commit.message.lower():
            return WarningSignal(
                kind="revert_commit",
                title=commit.message[:50],
                description="Revert 커밋이 발견됨",
                days=None,
                web_url=commit.web_url,
                repo_full_path=repo_full_path,
            )
    return None


def _find_hotfix_signal(
    commits: tuple[CommitInfo, ...], repo_full_path: str | None = None
) -> WarningSignal | None:
    """hotfix 커밋을 찾아 신호를 생성한다 (case-insensitive)."""
    for commit in commits:
        if "hotfix" in commit.message.lower():
            return WarningSignal(
                kind="hotfix_commit",
                title=commit.message[:50],
                description="Hotfix 커밋이 발견됨",
                days=None,
                web_url=commit.web_url,
                repo_full_path=repo_full_path,
            )
    return None


def detect_revert_or_hotfix(
    commits: tuple[CommitInfo, ...], repo_full_path: str | None = None
) -> list[WarningSignal]:
    """revert/hotfix 커밋 감지 (case-insensitive)."""
    signals = []

    revert_signal = _find_revert_signal(commits, repo_full_path)
    if revert_signal:
        signals.append(revert_signal)

    hotfix_signal = _find_hotfix_signal(commits, repo_full_path)
    if hotfix_signal:
        signals.append(hotfix_signal)

    return signals


def detect_stagnation_signals(
    group: FeatureGroup,
    now: datetime,
    thresholds: StagnationThresholds,
) -> list[WarningSignal]:
    """그룹의 모든 정체 신호를 감지 (신호 종류별 최대 1개씩)."""
    signals = []

    # stale_mr (최대 1개)
    for mr in group.merge_requests:
        stale = detect_stale_mr(
            mr,
            now,
            thresholds.review_waiting_days,
            repo_full_path=group.repo_full_path,
        )
        if stale:
            signals.append(stale)
            break  # 신호 종류별 최대 1개

    # revert/hotfix (각 1개)
    revert_hotfix_signals = detect_revert_or_hotfix(
        group.commits, repo_full_path=group.repo_full_path
    )
    signals.extend(revert_hotfix_signals)

    return signals
