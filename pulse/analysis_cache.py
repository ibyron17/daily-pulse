"""그룹 분석 캐시 로드/저장 및 지문 계산 (순수 파일 I/O + 해시)."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pulse.models import FeatureGroup


def compute_group_seed_fingerprint(group: FeatureGroup) -> str:
    """그룹의 seed를 기반으로 지문을 계산한다.

    Args:
        group: 기능 그룹

    Returns:
        SHA-256 해시의 첫 16자리
    """
    seed = {
        "name": group.name,
        "stage": group.stage,
        "commit_titles": sorted(group.task_summary.commit_titles),
        "branch_names": sorted(group.task_summary.active_branch_names),
        "mr_titles": sorted(group.task_summary.open_mr_titles),
    }
    seed_json = json.dumps(seed, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(seed_json.encode()).hexdigest()[:16]


def load_analysis_cache(path: Path) -> dict[str, Any]:
    """그룹 분석 캐시를 로드한다.

    Args:
        path: 캐시 파일 경로

    Returns:
        캐시 딕셔너리 (파일 없으면 빈 dict)
    """
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    result = data.get("groups", {})
    return result if isinstance(result, dict) else {}


def save_analysis_cache(cache: dict[str, Any], path: Path) -> None:
    """그룹 분석 캐시를 저장한다.

    Args:
        cache: 캐시 딕셔너리
        path: 캐시 파일 경로
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "cached_at": datetime.now().isoformat(),
        "groups": cache,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_pending(path: Path) -> dict[str, Any]:
    """pending 파일을 로드한다 (collect가 기록, inject가 소비).

    Args:
        path: pending 파일 경로

    Returns:
        pending 딕셔너리 (파일 없으면 빈 dict)
    """
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def save_pending(
    pending: dict[str, Any],
    path: Path,
) -> None:
    """pending 파일을 저장한다.

    Args:
        pending: pending 딕셔너리
        path: pending 파일 경로
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)


def evaluate_cached_status(
    weekly_section: dict[str, Any],
    cache: dict[str, Any] | None = None,
) -> None:
    """스냅샷 재생 시 cached 플래그를 재평가한다 (in-place).

    스냅샷은 발행 시점의 groups 상태를 담는데,
    발행 후 스킬이 주입한(inject) cached 상태와 다를 수 있다.

    비발행 실행에서 재생할 때:
    - 분석 캐시에 존재하는 group → cached=true 유지
    - 없는 group → cached=false (재작성 필요, 단 비발행이므로 스킵)

    Args:
        weekly_section: collect["weekly"] dict (in-place 수정)
        cache: 분석 캐시 dict 또는 None
    """
    if cache is None:
        cache = {}

    groups_data = weekly_section.get("groups", {})

    # groups가 dict인 경우 (key = "org/repo::group_name")
    if isinstance(groups_data, dict):
        for group_key, group_data in groups_data.items():
            if not isinstance(group_data, dict):
                continue

            # 캐시 키 생성: "org/repo::group_name@weekly"
            cache_key = f"{group_key}@weekly"

            if cache_key in cache:
                # 캐시에 존재 → cached=true로 설정
                group_data["cached"] = True
                group_data["cached_title"] = cache[cache_key].get("title")
                group_data["cached_analysis"] = cache[cache_key].get("analysis")
            else:
                # 캐시 부재 → cached=false
                group_data["cached"] = False
                group_data["cached_title"] = None
                group_data["cached_analysis"] = None
