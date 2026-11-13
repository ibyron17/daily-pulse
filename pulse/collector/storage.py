"""레포 활동을 raw JSON으로 저장/로드, 주간 스냅샷을 저장/로드."""

import json
import logging
from pathlib import Path
from typing import Any

from pulse.models import RepoActivity, activity_from_dict, activity_to_dict

logger = logging.getLogger(__name__)


def save_raw_activity(activity: RepoActivity, raw_dir: Path) -> Path:
    """
    RepoActivity를 JSON으로 저장한다.
    경로: raw_dir / {YYYY-MM-DD} / {repo.slug}.json
    """
    date_str = activity.collected_at.strftime("%Y-%m-%d")
    date_dir = raw_dir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    file_path = date_dir / f"{activity.repo.slug}.json"
    with open(file_path, "w") as f:
        json.dump(activity_to_dict(activity), f, indent=2, ensure_ascii=False)

    logger.info(
        "raw 저장: %s (커밋=%d, MR=%d)",
        file_path,
        len(activity.commits),
        len(activity.merge_requests),
    )
    return file_path


def load_raw_activity(file_path: Path) -> RepoActivity:
    """JSON 파일에서 RepoActivity를 로드한다."""
    with open(file_path) as f:
        data = json.load(f)
    return activity_from_dict(data)


def save_weekly_snapshot(data_dir: Path, weekly_section: dict[str, Any]) -> None:
    """주간 발행 섹션 스냅샷을 저장한다 (collect.json 섹션 그대로).

    위치: data/weekly_publish/latest.json (고정, 항상 overwrite)

    Args:
        data_dir: 프로젝트 data/ 디렉토리
        weekly_section: collect.json["weekly"] 섹션 dict

    Raises:
        IOError: 저장 실패
    """
    weekly_dir = data_dir / "weekly_publish"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = weekly_dir / "latest.json"

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(weekly_section, f, ensure_ascii=False, indent=2)

    logger.info("주간 스냅샷 저장: %s", snapshot_path)


def load_weekly_snapshot(data_dir: Path) -> dict[str, Any] | None:
    """최신 주간 발행 스냅샷을 로드한다.

    위치: data/weekly_publish/latest.json

    Args:
        data_dir: 프로젝트 data/ 디렉토리

    Returns:
        스냅샷 dict 또는 None (파일 없음 또는 파싱 실패)
    """
    snapshot_path = data_dir / "weekly_publish" / "latest.json"

    if not snapshot_path.exists():
        logger.debug("주간 스냅샷 없음: %s", snapshot_path)
        return None

    try:
        with open(snapshot_path, encoding="utf-8") as f:
            data: Any = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("주간 스냅샷 로드 실패: %s — %s", snapshot_path, e)
        return None
