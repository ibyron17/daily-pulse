"""릴리스 열차(승격 사다리) 구축: 라인 간 MR에서 배포 경로 유도."""

from collections import defaultdict
from datetime import datetime

from pulse.grouper.classify import is_release_line_branch, normalize_release_line_name
from pulse.models import MergeRequestInfo, PromotionRung, ReleaseTrain


def build_release_train(
    recent_mrs: tuple[MergeRequestInfo, ...],
    release_line_patterns: tuple[str, ...],
) -> ReleaseTrain:
    """라인→라인 MR에서 승격 사다리를 유도한다 (순수).

    1) source·target이 모두 라인 패턴에 해당하는 MR만 채택 (기능→라인 MR은 제외).
    2) (source, target)로 묶어 각 칸의 최근 merged 시각·건수·대기 수 집계.
    3) 체인 정렬: 어떤 칸의 target도 아닌 source를 시작점으로 삼아 링크를 따라간다.
       분기·순환으로 단일 체인이 안 되면 merged_count 내림차순 폴백 (예외 없음).
    """
    # 1단계: 라인→라인 MR만 채택
    line_mrs = [
        mr
        for mr in recent_mrs
        if is_release_line_branch(mr.source_branch, release_line_patterns)
        and is_release_line_branch(mr.target_branch, release_line_patterns)
    ]

    if not line_mrs:
        return ReleaseTrain(rungs=())

    # 2단계: (source, target)별 집계 (대소문자 정규화)
    aggregates: dict[tuple[str, str], dict[str, int | datetime | None]] = defaultdict(
        lambda: {
            "merged_count": 0,
            "open_count": 0,
            "last_merged_at": None,
            "last_mr_iid": None,
        }
    )

    for mr in line_mrs:
        # 대소문자 정규화 (develop vs DEVELOP vs Develop → develop)
        source_normalized = normalize_release_line_name(mr.source_branch, release_line_patterns)
        target_normalized = normalize_release_line_name(mr.target_branch, release_line_patterns)
        key = (source_normalized, target_normalized)
        agg = aggregates[key]

        if mr.state == "merged":
            agg["merged_count"] = int(agg["merged_count"]) + 1  # type: ignore
            # merged_at이 None이 아닌 경우만 비교하여 최신값 유지
            if mr.merged_at is not None:
                current_max = agg["last_merged_at"]
                if current_max is None or mr.merged_at > current_max:  # type: ignore
                    agg["last_merged_at"] = mr.merged_at
                    agg["last_mr_iid"] = mr.iid
        elif mr.state == "open":
            agg["open_count"] = int(agg["open_count"]) + 1  # type: ignore

    # 3단계: 칸 객체 생성
    rungs_list = [
        PromotionRung(
            source=source,
            target=target,
            last_merged_at=agg["last_merged_at"],  # type: ignore
            last_mr_iid=agg["last_mr_iid"],  # type: ignore
            merged_count=agg["merged_count"],  # type: ignore
            open_count=agg["open_count"],  # type: ignore
        )
        for (source, target), agg in aggregates.items()
    ]

    if not rungs_list:
        return ReleaseTrain(rungs=())

    # 3단계: 체인 정렬 시도
    sorted_rungs = _topological_sort(rungs_list)

    return ReleaseTrain(rungs=tuple(sorted_rungs))


def _topological_sort(rungs: list[PromotionRung]) -> list[PromotionRung]:
    """칸들을 위상 정렬 (상류→하류). 분기·순환 시 merged_count 폴백.

    어떤 칸의 target도 아닌 source를 시작점으로 삼아 체인을 따라간다.
    분기(한 source가 여러 target) 또는 순환으로 단일 체인이 안 되면
    merged_count 내림차순으로 나열한다.
    """
    if not rungs:
        return []

    # source → [target들] 매핑
    graph: dict[str, list[PromotionRung]] = defaultdict(list)
    for rung in rungs:
        graph[rung.source].append(rung)

    # 모든 target 수집 (시작점 판정에 사용)
    all_targets = {rung.target for rung in rungs}

    # 시작점: target으로 등장하지 않는 source
    start_points = []
    for rung in rungs:
        if rung.source not in all_targets:
            start_points.append(rung.source)

    # 단일 체인 구성 가능한지 확인
    if start_points:
        # 시작점에서 체인을 따라가며 단일 경로가 가능한지 검증
        single_start = start_points[0] if len(start_points) == 1 else None
        result = _follow_chain_or_fallback(graph, single_start, rungs)
        if result:
            return result

    # 폴백: merged_count 내림차순
    return sorted(rungs, key=lambda r: r.merged_count, reverse=True)


def _follow_chain_or_fallback(
    graph: dict[str, list[PromotionRung]], start_point: str | None, rungs: list[PromotionRung]
) -> list[PromotionRung] | None:
    """단일 시작점에서 체인을 따라가며 단일 경로 확인.

    분기나 순환이 있으면 None 반환 (폴백 처리).
    """
    if start_point is None:
        return None

    visited = set()
    result = []
    current = start_point

    while current is not None:
        if current in visited:
            # 순환 감지
            return None

        visited.add(current)

        if current in graph:
            candidates = graph[current]
            if len(candidates) != 1:
                # 분기 또는 말단
                if len(candidates) > 1:
                    return None  # 분기 → 폴백
                result.append(candidates[0])
                current = candidates[0].target
            else:
                result.append(candidates[0])
                current = candidates[0].target
        else:
            # 말단 도달
            break

    # 모든 칸이 체인에 포함됐는지 확인
    if len(result) == len(rungs):
        return result

    return None  # 폴백
