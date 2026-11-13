"""base(개발 기준선) 브랜치 결정 — provider 비종속 순수 로직.

`default_branch`를 그대로 쓰면 gitflow 레포에서 틀린 답이 나온다. 실측(2026-07-27):
`sample-group/sample-repo`의 default_branch는 `master`였지만 실제 개발 기준선은
`develop`이었다. master 기준으로 비교하면 ahead가 폭증해 진행 상황을 왜곡한다.

분기점이 가장 가까운(최근인) 브랜치가 실제 기준선이라는 관찰에 따라 후보 중에서 고른다.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 관례상 우선순위 — 동률일 때 앞선 것을 택한다
BASE_BRANCH_CANDIDATES: tuple[str, ...] = ("develop", "main", "master", "trunk", "staging")

# 파생 브랜치 이름 관례: 부모명 바로 뒤에 오는 구분자
_PARENT_SEPARATORS: tuple[str, ...] = ("_", "-", "/", ".")


def _prefix_parents(branch: str, existing_branches: frozenset[str]) -> tuple[str, ...]:
    """이름이 이 브랜치의 접두사인 브랜치들 — 다른 브랜치에서 파생된 브랜치의 부모 후보.

    `feature/ai_visualize_poc`처럼 기존 기능 브랜치 위에 쌓아 올린 브랜치는
    develop이 아니라 부모 브랜치가 실제 기준선이다. 실측(2026-07-30): develop과
    비교하면 부모의 커밋 4건이 섞여 시작일이 1년 일찍 잡혔고, 부모와 비교하면
    고유 커밋 15건이 정확히 분리됐다. 이름 관례(부모명 + 구분자)로 후보에 올리되,
    선택은 분기점이 가장 최근인 쪽(pick_closest_base)에 맡긴다 — 부모가 이미
    base에 머지돼 낡았으면 자연히 라인 브랜치가 이긴다.
    """
    parents = [
        name
        for name in existing_branches
        if name != branch
        and branch.startswith(name)
        and branch[len(name) :].startswith(_PARENT_SEPARATORS)
    ]
    return tuple(sorted(parents, key=lambda name: (-len(name), name)))


def pick_closest_base(candidates: tuple[tuple[str, datetime | None], ...]) -> str | None:
    """(후보 브랜치, 분기 시각) 쌍에서 분기점이 가장 최근인 브랜치를 고른다.

    분기 시각이 None인 후보(merge_base 조회 실패)는 제외한다.
    시각이 같으면 BASE_BRANCH_CANDIDATES 순서가 앞선 쪽을 택한다.

    Args:
        candidates: (브랜치명, 분기 시각) 쌍들

    Returns:
        선택된 브랜치명, 유효한 후보가 없으면 None
    """
    dated = [(name, when) for name, when in candidates if when is not None]
    if not dated:
        return None

    def sort_key(item: tuple[str, datetime]) -> tuple[float, int]:
        name, when = item
        rank = (
            BASE_BRANCH_CANDIDATES.index(name)
            if name in BASE_BRANCH_CANDIDATES
            else len(BASE_BRANCH_CANDIDATES)
        )
        return (-when.timestamp(), rank)

    return min(dated, key=sort_key)[0]


def build_base_candidates(
    branch: str,
    base_hint: str | None,
    existing_branches: frozenset[str],
    default_branch: str | None,
) -> tuple[str, ...]:
    """이 브랜치의 base 후보 목록을 만든다.

    이름 접두사로 판별한 부모 브랜치가 있으면 항상 후보에 포함한다 — hint는
    레포 단위 관례이고, 브랜치에서 파생된 브랜치는 그 관례의 예외이기 때문이다.
    그 외에는: config로 지정한 hint가 실제로 존재하면 그것만 후보로 둔다 —
    merge_base 조회를 1회로 줄이는 것이 명시 지정의 이득이다. hint가 없거나
    존재하지 않으면 관례 후보와 default_branch를 후보로 삼는다.

    Args:
        branch: 대상 브랜치
        base_hint: config에 지정된 base 브랜치 (선택)
        existing_branches: 레포에 실제로 존재하는 브랜치 이름들
        default_branch: 레포의 기본 브랜치 (선택)

    Returns:
        후보 브랜치 이름들 (자기 자신은 제외)
    """
    parents = _prefix_parents(branch, existing_branches)

    if base_hint:
        if base_hint in existing_branches:
            hinted = (base_hint,) if base_hint != branch and base_hint not in parents else ()
            return parents + hinted
        logger.warning("지정한 base 브랜치 %r가 없어 관례 후보로 폴백합니다", base_hint)

    ordered = list(parents)
    ordered += [
        name for name in BASE_BRANCH_CANDIDATES if name in existing_branches and name not in ordered
    ]
    if default_branch and default_branch not in ordered:
        ordered.append(default_branch)
    return tuple(name for name in ordered if name != branch)
