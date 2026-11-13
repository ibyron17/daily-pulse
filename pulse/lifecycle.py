"""수명주기 등록부 로드/저장 및 뷰 구축 (순수 로직 + 파일 I/O)."""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from pulse.models import FeatureGroup, GroupLifecycleView

logger = logging.getLogger(__name__)

GRADUATION_DAYS = 14
# 경과일은 첫 관측일을 1일차로 센다. 기준일(today)이 등록부 기록보다 이르면
# (--now 과거 재현·ad-hoc) 계산값이 0 이하가 되므로 이 값으로 막는다.
MIN_ELAPSED_DAYS = 1


@dataclass(frozen=True)
class StageTransition:
    """단계 전이 기록."""

    stage: str
    entered_at: date


@dataclass(frozen=True)
class GroupLifecycleEntry:
    """등록부의 한 그룹 항목."""

    first_seen: date
    last_seen: date
    stage_history: tuple[StageTransition, ...]
    date_commit_counts: tuple[tuple[str, int], ...]  # (ISO date, count) 불변 튜플
    group_kind: str


@dataclass(frozen=True)
class GroupLifecycleRegistry:
    """수명주기 등록부 전체."""

    schema_version: int
    updated_at: datetime
    groups: tuple[tuple[str, GroupLifecycleEntry], ...] = ()  # 불변 튜플 (key, entry)


def _group_key(repo_full_path: str, group_name: str) -> str:
    """그룹의 등록부 키를 생성한다."""
    return f"{repo_full_path}::{group_name}"


def _groups_as_dict(
    registry: GroupLifecycleRegistry,
) -> dict[str, GroupLifecycleEntry]:
    """등록부의 불변 튜플을 dict로 변환한다 (조회용 헬퍼)."""
    return dict(registry.groups)


def _earliest_active_date(date_commit_counts: tuple[tuple[str, int], ...]) -> date | None:
    """커밋이 실제로 있었던 가장 이른 날짜를 찾는다 (없으면 None)."""
    active_dates = [
        date.fromisoformat(date_str) for date_str, count in date_commit_counts if count > 0
    ]
    return min(active_dates) if active_dates else None


def _resolve_first_seen(candidate: date, date_commit_counts: tuple[tuple[str, int], ...]) -> date:
    """첫 관측일을 확정한다.

    커밋 히스토그램은 7일 창이라 등록일보다 이전의 활동까지 담고 있다.
    그 활동도 관측된 사실이므로 더 이른 날짜를 첫 관측일로 삼는다 —
    이렇게 하지 않으면 "진행 8일차 · 활동 12일"처럼 총 경과일보다 활동일이 커진다.
    """
    earliest = _earliest_active_date(date_commit_counts)
    return min(candidate, earliest) if earliest else candidate


def _register_new_group(
    group: FeatureGroup,
    run_date: date,
) -> GroupLifecycleEntry:
    """신규 그룹을 등록부에 추가한다 (순수)."""
    current_commit_counts = group.daily_commit_counts or ()
    return GroupLifecycleEntry(
        first_seen=_resolve_first_seen(run_date, current_commit_counts),
        last_seen=run_date,
        stage_history=(StageTransition(stage=group.stage, entered_at=run_date),),
        date_commit_counts=current_commit_counts,
        group_kind=group.group_kind,
    )


def _update_stage_history(
    entry: GroupLifecycleEntry,
    current_stage: str,
    run_date: date,
) -> tuple[StageTransition, ...]:
    """기존 항목의 단계 이력을 갱신한다 (순수)."""
    stage_history_tuple = entry.stage_history
    if stage_history_tuple and stage_history_tuple[-1].stage != current_stage:
        new_transition = StageTransition(stage=current_stage, entered_at=run_date)
        return stage_history_tuple + (new_transition,)
    elif not stage_history_tuple:
        return (StageTransition(stage=current_stage, entered_at=run_date),)
    return stage_history_tuple


def _merge_commit_counts(
    entry: GroupLifecycleEntry,
    current_commit_counts: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    """date_commit_counts를 날짜 overwrite 병합한다 (순수)."""
    date_map = dict(entry.date_commit_counts)
    for date_str, count in current_commit_counts:
        date_map[date_str] = count
    return tuple(sorted(date_map.items()))


def update_registry(
    registry: GroupLifecycleRegistry,
    weekly_groups: tuple[FeatureGroup, ...],
    run_date: date,
    updated_at: datetime | None = None,
) -> GroupLifecycleRegistry:
    """주간 그룹으로 등록부를 갱신한다 (순수 함수 — 새 등록부 반환).

    신규 그룹 등록, stage 전이 감지 시 stage_history append,
    daily_commit_counts를 date_commit_counts에 날짜 overwrite 병합.
    입력은 불변이며 새 등록부를 반환한다.

    Args:
        registry: 기존 등록부
        weekly_groups: 주간 그룹들
        run_date: 실행 날짜
        updated_at: 갱신 시각 (기본 None → 현재 timezone-aware datetime)
    """
    if updated_at is None:
        # Timezone-aware datetime 사용 (기본값: 현재 UTC)
        updated_at = datetime.now(timezone.utc)

    # dict 변환
    groups_dict = _groups_as_dict(registry)

    for group in weekly_groups:
        key = _group_key(group.repo_full_path, group.name)
        current_commit_counts = group.daily_commit_counts or ()

        if key not in groups_dict:
            groups_dict[key] = _register_new_group(group, run_date)
        else:
            entry = groups_dict[key]
            stage_history = _update_stage_history(entry, group.stage, run_date)
            date_commit_counts = _merge_commit_counts(entry, current_commit_counts)
            groups_dict[key] = GroupLifecycleEntry(
                first_seen=_resolve_first_seen(entry.first_seen, date_commit_counts),
                last_seen=run_date,
                stage_history=stage_history,
                date_commit_counts=date_commit_counts,
                group_kind=group.group_kind,
            )

    # dict → 정렬된 튜플로 변환
    sorted_groups = tuple(sorted(groups_dict.items()))

    return GroupLifecycleRegistry(
        schema_version=1,
        updated_at=updated_at,
        groups=sorted_groups,
    )


def build_lifecycle_view(
    registry: GroupLifecycleRegistry, group_key: str, today: date
) -> GroupLifecycleView | None:
    """그룹의 경과일·현재 단계 지속일 뷰 계산.

    등록부에 없으면 None 반환.
    졸업 정책: merged 후 14일 경과 시 None 반환 (뷰 제외, 등록부는 유지).

    total_days = (today - first_seen).days + 1 (첫 관측일을 1일차로, 최소 1).
    current_stage_days = (today - entered_at).days + 1 (최소 1).
    active_days = date_commit_counts에서 count > 0인 날짜 수.
    cumulative_commits = 값의 합계.
    """
    groups_dict = _groups_as_dict(registry)
    if group_key not in groups_dict:
        return None

    entry = groups_dict[group_key]

    # total_days 계산
    total_days = max(MIN_ELAPSED_DAYS, (today - entry.first_seen).days + 1)

    # 현재 단계와 current_stage_days 계산
    if entry.stage_history:
        last_transition = entry.stage_history[-1]
        current_stage = last_transition.stage
        current_stage_days = max(MIN_ELAPSED_DAYS, (today - last_transition.entered_at).days + 1)
    else:
        # 안전장치 (이력이 없으면 등록부 자체가 손상된 것)
        current_stage = "other"
        current_stage_days = total_days

    # 졸업 정책: merged 후 14일 경과 시 None 반환
    if current_stage == "merged":
        days_since_merged = (today - entry.stage_history[-1].entered_at).days
        if days_since_merged >= GRADUATION_DAYS:
            return None

    # active_days 계산: count > 0인 날짜 수
    active_days = sum(1 for _, count in entry.date_commit_counts if count > 0)

    # cumulative_commits 계산: 모든 카운트의 합
    cumulative_commits = sum(count for _, count in entry.date_commit_counts)

    return GroupLifecycleView(
        first_seen=entry.first_seen.isoformat(),
        total_days=total_days,
        current_stage=current_stage,
        current_stage_days=current_stage_days,
        active_days=active_days,
        cumulative_commits=cumulative_commits,
    )


def load_registry(path: Path) -> GroupLifecycleRegistry:
    """registry.json 로드 — 없음/손상 시 빈 등록부 + 경고 (우아한 저하).

    파일이 없거나 JSON 손상, 스키마 불일치 시 빈 등록부를 반환하고 경고를 로깅한다.
    """
    if not path.exists():
        return GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(timezone.utc),
            groups=(),
        )

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Expected dict at root")

        schema_version = data.get("schema_version", 1)
        if schema_version != 1:
            logger.warning("lifecycle registry: unsupported schema version %s", schema_version)
            return GroupLifecycleRegistry(
                schema_version=1,
                updated_at=datetime.now(timezone.utc),
                groups=(),
            )

        updated_at_str = data.get("updated_at", datetime.now(timezone.utc).isoformat())
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
        except (ValueError, TypeError):
            updated_at = datetime.now(timezone.utc)

        groups_data = data.get("groups", {})
        if not isinstance(groups_data, dict):
            logger.warning("lifecycle registry: groups must be a dict")
            return GroupLifecycleRegistry(
                schema_version=1,
                updated_at=datetime.now(timezone.utc),
                groups=(),
            )

        # 각 그룹 항목을 복원
        groups_dict: dict[str, GroupLifecycleEntry] = {}
        for key, entry_data in groups_data.items():
            if not isinstance(entry_data, dict):
                continue

            try:
                first_seen = date.fromisoformat(entry_data.get("first_seen", ""))
                last_seen = date.fromisoformat(entry_data.get("last_seen", ""))

                # stage_history 복원
                stage_history_data = entry_data.get("stage_history", [])
                stage_history_list: list[StageTransition] = []
                for trans_data in stage_history_data:
                    if isinstance(trans_data, dict):
                        stage = trans_data.get("stage")
                        entered_at_str = trans_data.get("entered_at")
                        if stage and entered_at_str:
                            entered_at = date.fromisoformat(entered_at_str)
                            transition = StageTransition(stage=stage, entered_at=entered_at)
                            stage_history_list.append(transition)
                stage_history: tuple[StageTransition, ...] = tuple(stage_history_list)

                # date_commit_counts 복원
                date_counts_data = entry_data.get("date_commit_counts", {})
                if isinstance(date_counts_data, dict):
                    date_commit_counts = tuple(sorted(date_counts_data.items()))
                else:
                    # 이미 list of tuples라면 그대로 사용
                    date_commit_counts = (
                        tuple(date_counts_data)
                        if isinstance(date_counts_data, (list, tuple))
                        else ()
                    )

                group_kind = entry_data.get("group_kind", "feature")

                groups_dict[key] = GroupLifecycleEntry(
                    first_seen=first_seen,
                    last_seen=last_seen,
                    stage_history=stage_history,
                    date_commit_counts=date_commit_counts,
                    group_kind=group_kind,
                )
            except (ValueError, TypeError, KeyError) as error:
                logger.warning("lifecycle registry: skipping malformed entry %s: %s", key, error)
                continue

        # dict → 정렬된 튜플로 변환
        sorted_groups = tuple(sorted(groups_dict.items()))

        return GroupLifecycleRegistry(
            schema_version=1,
            updated_at=updated_at,
            groups=sorted_groups,
        )

    except (json.JSONDecodeError, OSError) as error:
        logger.warning("lifecycle registry load failed: %s, using empty registry", error)
        return GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(timezone.utc),
            groups=(),
        )


def save_registry(registry: GroupLifecycleRegistry, path: Path) -> None:
    """registry.json 저장 (디렉토리 자동 생성, 그룹 키 정렬 고정)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # 직렬화: tuple을 dict로 변환하고 date와 StageTransition을 dict로 변환
    groups_dict = {}
    for key, entry in registry.groups:
        groups_dict[key] = {
            "first_seen": entry.first_seen.isoformat(),
            "last_seen": entry.last_seen.isoformat(),
            "stage_history": [
                {"stage": trans.stage, "entered_at": trans.entered_at.isoformat()}
                for trans in entry.stage_history
            ],
            "date_commit_counts": dict(entry.date_commit_counts),
            "group_kind": entry.group_kind,
        }

    data = {
        "schema_version": registry.schema_version,
        "updated_at": registry.updated_at.isoformat(),
        "groups": groups_dict,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def registry_path(data_dir: Path) -> Path:
    """등록부 파일 경로를 생성한다."""
    return data_dir / "lifecycle" / "registry.json"
