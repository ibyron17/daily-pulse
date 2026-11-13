"""diff 계산: 전일 대비 변화 (신규 그룹, 단계 변화)."""

from pulse.models import MEANINGFUL_STAGES, FeatureGroup, FeatureStage, GroupStageChange


def _is_meaningful_stage_change(
    previous_stage: FeatureStage,
    current_stage: FeatureStage,
) -> bool:
    """단계 변화가 정보가치 있는지 판정한다.

    규칙:
    - 양쪽 모두 MEANINGFUL_STAGES(developing ↔ reviewing ↔ merged)면 포함
    - "other"(분류 불가)로의/로부터의 전이는 제외

    Args:
        previous_stage: 이전 단계
        current_stage: 현재 단계

    Returns:
        True if 변화를 보고할 가치가 있음
    """
    return previous_stage in MEANINGFUL_STAGES and current_stage in MEANINGFUL_STAGES


def _detect_stage_changes(
    today_groups: tuple[FeatureGroup, ...],
    yesterday_by_key: dict[tuple[str, str], FeatureGroup],
) -> tuple[GroupStageChange, ...]:
    """같은 이름·repo 그룹 중 진행 단계가 바뀐 것을 찾는다 (의미 있는 전이만).

    "other" 단계로의/로부터의 전이는 제외한다 (정보가치 없음).
    """
    stage_changes = []
    for today_group in today_groups:
        key = (today_group.repo_full_path, today_group.name)
        yesterday_group = yesterday_by_key.get(key)
        if yesterday_group and today_group.stage != yesterday_group.stage:
            # 의미 있는 전이 여부 판정
            if not _is_meaningful_stage_change(yesterday_group.stage, today_group.stage):
                continue
            stage_changes.append(
                GroupStageChange(
                    group_name=today_group.name,
                    previous_stage=yesterday_group.stage,
                    current_stage=today_group.stage,
                    repo_full_path=today_group.repo_full_path,
                )
            )
    return tuple(stage_changes)


def compute_diff(
    today_groups: tuple[FeatureGroup, ...],
    yesterday_groups: tuple[FeatureGroup, ...],
) -> tuple[tuple[tuple[str, str], ...], tuple[GroupStageChange, ...]]:
    """신규 그룹과 단계 변화를 계산한다 (매칭 키: (repo_full_path, group_name)).

    Returns:
        (신규_그룹_튜플_of_(repo, name), 단계변화_튜플)
    """
    yesterday_by_key = {(g.repo_full_path, g.name): g for g in yesterday_groups}
    new_groups = tuple(
        (g.repo_full_path, g.name)
        for g in today_groups
        if (g.repo_full_path, g.name) not in yesterday_by_key
    )
    return (new_groups, _detect_stage_changes(today_groups, yesterday_by_key))
