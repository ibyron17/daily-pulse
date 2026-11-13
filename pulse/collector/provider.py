"""Git 호스팅 공급자(provider) 추상화 인터페이스."""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pulse.models import (
    BranchHistoryFetch,
    BranchHistoryRequest,
    RepoActivity,
    RepoRef,
)


class GitProvider(Protocol):
    """
    Git 호스팅(GitLab, GitHub 등)에서 레포 활동을 동기적으로 수집하는 공통 인터페이스.
    각 구현체는 이 메서드들을 통해 정규화된 RepoActivity를 반환한다.

    주의: requests 라이브러리 기반이므로 모든 메서드는 동기(def).
    병렬화는 ThreadPoolExecutor로 외부에서 처리한다.
    """

    def get_repo_version(self, repo: RepoRef) -> str:
        """
        수집 가능 확인용 버전 문자열을 반환한다.
        예: "16.7.0" (GitLab) / "GitHub Enterprise" 등.
        레포 접근 불가면 CollectionError 발생.
        """
        ...

    def collect_repo_activity(
        self,
        repo: RepoRef,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        snapshot_dir: Path | None = None,
        stale_branch_days: int = 7,
        now: datetime | None = None,
    ) -> RepoActivity:
        """
        레포의 활동을 동기적으로 수집해 RepoActivity를 반환한다.

        Args:
            repo: 레포 참조
            lookback_hours: 조회 범위 (시간 단위)
            exclude_bot_authors: 제외할 봇 author 목록 (author_name에 포함되면 제외)
            snapshot_dir: 브랜치 스냅샷 저장 디렉토리 (선택, None이면 스냅샷 미생성)
            stale_branch_days: 정체 브랜치 판별 일 수 (기본 7일)
            now: 기준 시각 (UTC aware datetime, 선택, None이면 현재 시각 사용)

        Returns:
            RepoActivity (실패 시 status="failed", failure_reason 포함, 예외 발생 금지).
        """
        ...

    def collect_branch_history(
        self,
        repo: RepoRef,
        branches: tuple[BranchHistoryRequest, ...],
        base_branch_hint: str | None,
        max_commits: int,
    ) -> tuple[BranchHistoryFetch, ...]:
        """
        분기점(merge_base)부터의 브랜치 히스토리를 수집한다.

        lookback 창과 무관하게 브랜치가 갈라진 시점 전체를 대상으로 한다 —
        "초기 시작 단계부터" 진행 상황을 보기 위한 조회다.

        Args:
            repo: 레포 참조
            branches: 조회 대상 (브랜치명, head SHA) — head SHA는 증분 판정에 쓰인다
            base_branch_hint: config에 지정된 base 브랜치 (None이면 자동 판별)
            max_commits: 브랜치당 커밋 수집 상한

        Returns:
            수집 성공한 브랜치들의 결과. 개별 브랜치 실패는 결과에서 제외하며
            예외를 발생시키지 않는다 (부분 실패가 전체를 막지 않는다).
        """
        ...
