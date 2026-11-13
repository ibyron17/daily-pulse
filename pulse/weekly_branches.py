"""주간 신규 브랜치: 창 끝 스냅샷과 7일 전 기준 스냅샷을 비교해 activities 에 주입한다.

스냅샷 파일을 읽는다 — 순수 모듈이 아니다.
pulse/pipeline.py 에서 옮겼다(800줄 상한, 직전 PRP §15.3 후보 a). 계약 상대: pipeline.run_pipeline.
"""

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

from pulse.collector.snapshot import (
    BranchSnapshot,
    find_snapshot_near_days_ago,
    find_snapshot_on_or_after,
)
from pulse.config import Config
from pulse.models import RepoActivity

logger = logging.getLogger(__name__)


def find_weekly_baseline_snapshots(
    config: Config,
    end_date: date,
) -> tuple[dict[str, date], date | None]:
    """주간 뷰의 신규 브랜치 비교용 기준 스냅샷을 찾는다 (G3).

    각 레포별로 정확히 end_date 7일 전 스냅샷이 있으면 그것을, 없으면 end_date 이전의
    가장 최근 스냅샷을 쓴다. 이전 스냅샷이 하나도 없는 레포는 created_branches=() 처리.
    표기용 baseline_date는 존재하는 기준 중 **가장 이른 날짜**로 일관된 기준 표시.

    Args:
        config: 설정
        end_date: 주간 창 끝 날짜(그 주 월요일)

    Returns:
        (repo_slug -> baseline_date 매핑, 표기용 baseline_date or None)
    """
    snapshot_dir = config.data_dir / "snapshots"
    baseline_map: dict[str, date] = {}
    baseline_dates: list[date] = []

    for repo_ref in config.repos:
        result = find_snapshot_near_days_ago(
            snapshot_dir, repo_ref.slug, end_date.isoformat(), days_ago=7
        )
        if result:
            snapshot_date_str, _ = result
            baseline_date = date.fromisoformat(snapshot_date_str)
            baseline_map[repo_ref.slug] = baseline_date
            baseline_dates.append(baseline_date)

    # 표기용 baseline: 가장 이른 날짜
    display_baseline = min(baseline_dates) if baseline_dates else None
    return baseline_map, display_baseline


def _created_branches_since_baseline(
    snapshot_dir: Path, repo_slug: str, end_date: date, baseline_date: date
) -> tuple[str, ...]:
    """끝 스냅샷과 기준 스냅샷을 비교해 그 사이 새로 생긴 브랜치를 정렬해 반환한다.

    끝 스냅샷은 end_date(주간 창 끝 날짜 = 그 주 월요일) 이후 가장 이른 것이다. 월요일 실행이
    정상이면 그날 스냅샷이 선택되고, 월요일 실행이 빠진 주는 그날 스냅샷이 없으므로
    그 이후 가장 가까운 스냅샷(다음 실행일의 것)으로 대신한다. 없으면 빈 튜플.
    """
    end_found = find_snapshot_on_or_after(snapshot_dir, repo_slug, end_date.isoformat())
    if end_found is None:
        return ()

    baseline_path = snapshot_dir / baseline_date.isoformat() / f"{repo_slug}.json"
    baseline_snapshot = BranchSnapshot.load(baseline_path) if baseline_path.exists() else None
    created, _ = BranchSnapshot.load(end_found[1]).diff_against(baseline_snapshot)
    return tuple(sorted(created))


def weekly_created_branches(
    config: Config,
    activities: tuple[RepoActivity, ...],
    end_date: date,
    baseline_map: dict[str, date],
) -> tuple[RepoActivity, ...]:
    """end_date 이후 가장 이른 스냅샷과 기준 스냅샷을 비교해 created_branches 를 교체한다 (G3).

    기준 스냅샷이 없는 레포, 끝 스냅샷이 없는 레포, 비교에 실패한 레포는
    created_branches=() 로 둔다 (우아한 저하).

    Args:
        config: 설정 (data_dir)
        activities: 수집된 활동
        end_date: 주간 창 끝 날짜(그 주 월요일)
        baseline_map: 레포 slug -> 기준 스냅샷 날짜 (find_weekly_baseline_snapshots 결과)

    Returns:
        created_branches 가 주간 기준으로 교체된 활동 튜플
    """
    snapshot_dir = config.data_dir / "snapshots"
    updated: list[RepoActivity] = []
    for activity in activities:
        repo_slug = activity.repo.slug
        baseline_date = baseline_map.get(repo_slug)
        created: tuple[str, ...] = ()
        if baseline_date is not None:
            try:
                created = _created_branches_since_baseline(
                    snapshot_dir, repo_slug, end_date, baseline_date
                )
            except Exception as error:
                logger.warning("스냅샷 비교 실패 (%s): %s", repo_slug, error)
        updated.append(replace(activity, created_branches=created))
    return tuple(updated)
