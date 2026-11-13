"""일일 브랜치 스냅샷 저장/로드 및 변화 감지."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from pulse.state_io import save_optional_state

logger = logging.getLogger(__name__)


class BranchSnapshot:
    """특정 시점의 레포 브랜치 목록 스냅샷."""

    def __init__(self, repo_slug: str, branch_names: set[str], snapshot_date: str) -> None:
        """
        Args:
            repo_slug: "sample-group__sample-repo"
            branch_names: {"develop", "feature/foo", ...}
            snapshot_date: "2026-07-15" (ISO 형식)
        """
        self.repo_slug = repo_slug
        self.branch_names = branch_names
        self.snapshot_date = snapshot_date

    @classmethod
    def from_gitlab_response(
        cls,
        repo_slug: str,
        branches_data: list[dict[str, Any]],
        snapshot_date: str,
    ) -> "BranchSnapshot":
        """GitLab API 응답(브랜치 목록)으로부터 스냅샷 생성."""
        branch_names = {b["name"] for b in branches_data}
        return cls(repo_slug, branch_names, snapshot_date)

    def save(self, snapshot_dir: Path) -> Path:
        """스냅샷을 JSON으로 저장. 경로: snapshot_dir/{YYYY-MM-DD}/{slug}.json"""
        date_dir = snapshot_dir / self.snapshot_date
        date_dir.mkdir(parents=True, exist_ok=True)

        path = date_dir / f"{self.repo_slug}.json"
        with open(path, "w") as f:
            json.dump(
                {
                    "repo_slug": self.repo_slug,
                    "branch_names": sorted(self.branch_names),
                    "snapshot_date": self.snapshot_date,
                },
                f,
            )
        logger.debug("스냅샷 저장: %s (%d개 브랜치)", path, len(self.branch_names))
        return path

    @staticmethod
    def load(path: Path) -> "BranchSnapshot":
        """JSON 파일로부터 스냅샷을 로드한다."""
        with open(path) as f:
            data = json.load(f)
        return BranchSnapshot(
            repo_slug=data["repo_slug"],
            branch_names=set(data["branch_names"]),
            snapshot_date=data["snapshot_date"],
        )

    def diff_against(self, previous: "BranchSnapshot | None") -> tuple[set[str], set[str]]:
        """
        이전 스냅샷과 비교해 생성/삭제 브랜치를 반환한다.
        previous가 None이면 (첫 실행) 생성만 계산, 삭제는 공집합.
        """
        if previous is None:
            return self.branch_names, set()
        created = self.branch_names - previous.branch_names
        deleted = previous.branch_names - self.branch_names
        return created, deleted


def _validate_date_dir(dir_name: str) -> bool:
    """YYYY-MM-DD 형식의 디렉토리명 검증."""
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    return bool(date_pattern.match(dir_name))


def _collect_snapshot_candidates(
    snapshot_dir: Path,
    repo_slug: str,
    current_date: str,
) -> list[tuple[str, Path]]:
    """현재 날짜 이전의 스냅샷 후보 수집 (날짜별 정렬)."""
    candidates = []
    for date_dir in snapshot_dir.iterdir():
        if not date_dir.is_dir() or not _validate_date_dir(date_dir.name):
            continue
        if date_dir.name >= current_date:
            continue
        snapshot_path = date_dir / f"{repo_slug}.json"
        if snapshot_path.exists():
            candidates.append((date_dir.name, snapshot_path))
    candidates.sort(reverse=True)
    return candidates


def find_previous_snapshot(
    snapshot_dir: Path,
    repo_slug: str,
    current_date: str,
) -> Path | None:
    """
    현재 날짜 이전의 가장 최근 스냅샷을 찾는다.
    경로 구조: snapshot_dir/{YYYY-MM-DD}/{slug}.json
    """
    if not snapshot_dir.exists():
        return None
    candidates = _collect_snapshot_candidates(snapshot_dir, repo_slug, current_date)
    return candidates[0][1] if candidates else None


def _load_previous_snapshot(
    snapshot_dir: Path,
    repo_slug: str,
    current_date: str,
) -> BranchSnapshot | None:
    """이전 스냅샷을 로드한다. 없으면 None."""
    previous_path = find_previous_snapshot(snapshot_dir, repo_slug, current_date)
    if previous_path is None:
        return None
    return BranchSnapshot.load(previous_path)


def find_snapshot_near_days_ago(
    snapshot_dir: Path,
    repo_slug: str,
    current_date: str,
    days_ago: int = 7,
) -> tuple[str, Path] | None:
    """
    현재 날짜로부터 days_ago일 전에 가장 가까운 과거 스냅샷을 찾는다.

    예: days_ago=7, current_date="2026-07-20"일 때
    2026-07-13 00:00 <= target_date <= 2026-07-13 23:59 범위에서 찾고,
    없으면 그 이전 가장 최신 스냅샷을 반환.

    Args:
        snapshot_dir: 스냅샷 디렉토리
        repo_slug: 레포 slug
        current_date: 현재 날짜 (ISO 형식, "2026-07-20")
        days_ago: 몇 일 전 (기본 7)

    Returns:
        (snapshot_date_str, path) 또는 None
    """
    from datetime import datetime, timedelta

    if not snapshot_dir.exists():
        return None

    try:
        current = datetime.fromisoformat(current_date)
    except ValueError:
        logger.warning("유효하지 않은 날짜: %s", current_date)
        return None

    target_date = current - timedelta(days=days_ago)
    target_date_str = target_date.date().isoformat()

    candidates = _collect_snapshot_candidates(snapshot_dir, repo_slug, current_date)
    if not candidates:
        return None

    # target_date_str과 일치하는 것을 먼저 찾음
    for candidate_date, candidate_path in candidates:
        if candidate_date == target_date_str:
            return (candidate_date, candidate_path)

    # 없으면 그 이전 가장 최신 것 (candidates는 이미 역순 정렬)
    if candidates:
        return candidates[0]

    return None


def find_snapshot_on_or_after(
    snapshot_dir: Path,
    repo_slug: str,
    target_date: str,
) -> tuple[str, Path] | None:
    """target_date 이후(포함) 가장 이른 스냅샷을 찾는다.

    월요일 실행이 빠진 주는 그날 스냅샷이 없을 수 있으므로,
    그 날짜 이후 가장 가까운 스냅샷(다음 실행일이 남긴 것)을 대신 쓴다.

    Args:
        snapshot_dir: 스냅샷 디렉토리
        repo_slug: 레포 slug
        target_date: 기준 날짜 (ISO 형식, "2026-10-05")

    Returns:
        (snapshot_date_str, path) 또는 None
    """
    if not snapshot_dir.exists():
        return None

    candidates: list[tuple[str, Path]] = []
    for date_dir in snapshot_dir.iterdir():
        if not date_dir.is_dir() or not _validate_date_dir(date_dir.name):
            continue
        if date_dir.name < target_date:
            continue
        snapshot_path = date_dir / f"{repo_slug}.json"
        if snapshot_path.exists():
            candidates.append((date_dir.name, snapshot_path))
    return min(candidates) if candidates else None


def load_or_create(
    snapshot_dir: Path,
    repo_slug: str,
    current_branches: set[str],
    current_date: str,
) -> tuple[BranchSnapshot, bool, "BranchSnapshot | None"]:
    """현재 스냅샷을 로드 또는 생성.

    Returns:
        (snapshot, is_first_collection, previous):
        is_first_collection=True이면 이전 스냅샷이 없어 첫 수집 상태.
        previous는 이전 스냅샷 객체 또는 None.
    """
    previous = _load_previous_snapshot(snapshot_dir, repo_slug, current_date)
    current = BranchSnapshot(repo_slug, current_branches, current_date)
    is_first = previous is None
    # 저장 실패는 다음 실행의 신규 브랜치 감지를 한 번 둔하게 만들 뿐이므로 발행을 막지 않는다
    save_optional_state(f"브랜치 스냅샷({repo_slug})", lambda: current.save(snapshot_dir))
    return current, is_first, previous
