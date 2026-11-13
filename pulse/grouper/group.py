"""FeatureGroup 조립 (그룹핑, 단계 추정, 참여자 집계)."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pulse.config.loader import GroupingHints
from pulse.grouper.classify import (
    classify_branch,
    classify_commit,
    classify_merge_request,
    extract_issue_keys,
    is_release_line_branch,
    normalize_release_line_name,
)
from pulse.grouper.stage import estimate_stage
from pulse.models import CommitInfo, FeatureGroup, MergeRequestInfo, RepoActivity, TaskSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ClassifiedItem:
    """분류된 항목의 중간 표현."""

    group_name: str
    source_rule: str
    item_type: str  # "commit" | "mr" | "branch"


def _is_merge_commit(message: str) -> bool:
    """머지 커밋 여부 판별 (Git 머지 커밋 패턴만)."""
    title = message.split("\n")[0].strip().lower()
    # Git 머지 커밋 패턴: "merge branch", "merge pull request", "merge remote-tracking"
    return (
        title.startswith("merge branch ")
        or title.startswith("merge pull request ")
        or title.startswith("merge remote-tracking ")
    )


def normalize_commit_titles(commits: tuple[CommitInfo, ...]) -> tuple[str, ...]:
    """커밋에서 제목을 추출하고 정규화한다 (머지 커밋 제외, 중복 제거).

    상한 없음 — publish.py의 seed 파생에서 별도로 상한 적용.
    """
    sorted_commits = sorted(commits, key=lambda c: c.authored_at, reverse=True)
    commit_titles = []
    for commit in sorted_commits:
        if not _is_merge_commit(commit.message):
            title = commit.message.split("\n")[0]  # 첫 줄만
            commit_titles.append(title)
    # 중복 제거 (순서 유지)
    seen = set()
    unique_titles = []
    for title in commit_titles:
        if title not in seen:
            seen.add(title)
            unique_titles.append(title)
    return tuple(unique_titles)


def _derive_task_summary(
    commits: tuple[CommitInfo, ...],
    merge_requests: tuple[MergeRequestInfo, ...],
    branch_names: tuple[str, ...],
) -> TaskSummary:
    """기능 그룹의 상세 내용을 정리한다 (순수 함수).

    제목 상한은 표시용 기준을 유지 (커밋 3/MR 2/브랜치 3) —
    분석 캐시 지문 안정성 보장.
    """
    # 커밋 제목: normalize_commit_titles로 정규화 후 첫 3개
    all_commit_titles = normalize_commit_titles(commits)
    commit_titles_final = all_commit_titles[:3]

    # MR 제목: open 상태만, max 2
    open_mrs = [mr for mr in merge_requests if mr.state == "open"]
    open_mr_titles = tuple(mr.title for mr in open_mrs[:2])

    # 브랜치: 활동 브랜치 + 커밋이 실제로 속한 브랜치의 합집합.
    # 활동 브랜치만 쓰면 조회 창 안에 커밋이 있는데도 목록이 비는 일이 생긴다 —
    # 창 필터는 브랜치의 마지막 push 한 시점만 보므로, 창 이후에 push가 더 있었던
    # 브랜치(= 계속 활발한 브랜치)가 상한을 넘겨 탈락한다. 커밋 쪽 근거로 메운다.
    # 활동 브랜치를 앞에 두는 이유: 그쪽이 브랜치 목록 API에서 온 정식 이름이다.
    # 표시용 목록만 넓힌다 — group_kind·stage 판별은 브랜치 목록 API에서 온
    # 원본(branch_names)을 계속 쓴다. 분류 근거를 표시용 목록으로 바꾸면
    # main/develop/master 제외와 상한 3개가 분류에까지 새어든다.
    candidate_branches = list(branch_names)
    seen_branches = set(branch_names)
    for commit in commits:
        if commit.branch and commit.branch not in seen_branches:
            candidate_branches.append(commit.branch)
            seen_branches.add(commit.branch)

    main_branches = {"main", "develop", "master"}
    display_branches = tuple(b for b in candidate_branches if b not in main_branches)
    active_branch_names = display_branches[:3]

    return TaskSummary(
        commit_titles=commit_titles_final,
        open_mr_titles=open_mr_titles,
        active_branch_names=active_branch_names,
    )


def aggregate_participants(
    commits: tuple[CommitInfo, ...],
    merge_requests: tuple[MergeRequestInfo, ...],
) -> tuple[str, ...]:
    """커밋·MR의 author를 중복 제거하고 Python sorted() (유니코드 코드포인트 순)로 정렬."""
    authors = set()
    for commit in commits:
        authors.add(commit.author_name)
    for mr in merge_requests:
        authors.add(mr.author_name)

    # Python 기본 sorted() — 유니코드 코드포인트 순, 결정적
    return tuple(sorted(authors))


def _ensure_group_initialized(
    groups_dict: dict[tuple[str, str], dict[str, Any]],
    repo_full_path: str,
    group_name: str,
    source_rule: str,
    evidence: str,
) -> None:
    """그룹이 아직 groups_dict에 없으면 초기화한다."""
    key = (repo_full_path, group_name)
    if key not in groups_dict:
        groups_dict[key] = {
            "source_rule": source_rule,
            "evidence": evidence,
            "commits": [],
            "merge_requests": [],
            "branch_names": set(),
            "branches": [],
            "repo_full_path": repo_full_path,
        }


def _collect_commits_into_groups(
    activities: tuple[RepoActivity, ...],
    hints: GroupingHints,
    groups_dict: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """활동의 커밋을 분류해서 groups_dict에 누적한다."""
    for activity in activities:
        for commit in activity.commits:
            result = classify_commit(commit, hints)
            group_name = normalize_release_line_name(result.group_name, hints.release_line_patterns)
            _ensure_group_initialized(
                groups_dict,
                activity.repo.full_path,
                group_name,
                result.source_rule,
                result.evidence,
            )
            key = (activity.repo.full_path, group_name)
            groups_dict[key]["commits"].append(commit)


def _collect_merge_requests_into_groups(
    activities: tuple[RepoActivity, ...],
    hints: GroupingHints,
    groups_dict: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """활동의 MR을 분류해서 groups_dict에 누적한다."""
    for activity in activities:
        for mr in activity.merge_requests:
            result = classify_merge_request(mr, hints)
            group_name = normalize_release_line_name(result.group_name, hints.release_line_patterns)
            _ensure_group_initialized(
                groups_dict,
                activity.repo.full_path,
                group_name,
                result.source_rule,
                result.evidence,
            )
            key = (activity.repo.full_path, group_name)
            groups_dict[key]["merge_requests"].append(mr)


def _collect_branches_into_groups(
    activities: tuple[RepoActivity, ...],
    hints: GroupingHints,
    groups_dict: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """활동의 브랜치를 분류해서 groups_dict에 누적한다."""
    for activity in activities:
        for branch_name in activity.created_branches + tuple(
            b.name for b in activity.active_branches
        ):
            result = classify_branch(branch_name, hints)
            group_name = normalize_release_line_name(result.group_name, hints.release_line_patterns)
            _ensure_group_initialized(
                groups_dict,
                activity.repo.full_path,
                group_name,
                result.source_rule,
                result.evidence,
            )
            key = (activity.repo.full_path, group_name)
            groups_dict[key]["branch_names"].add(branch_name)
            # BranchInfo 찾기: active_branches에서 이름 매칭
            for branch_info in activity.active_branches:
                if branch_info.name == branch_name:
                    groups_dict[key]["branches"].append(branch_info)
                    break


def _collect_classified_items(
    activities: tuple[RepoActivity, ...],
    hints: GroupingHints,
) -> dict[tuple[str, str], dict[str, Any]]:
    """분류 결과를 groups_dict에 수집한다 (커밋/MR/브랜치).

    groups_dict의 키는 (repo_full_path, group_name) 튜플로,
    같은 group_name이라도 다른 repo에 속하면 별개 그룹이 된다.
    """
    groups_dict: dict[tuple[str, str], dict[str, Any]] = {}
    _collect_commits_into_groups(activities, hints, groups_dict)
    _collect_merge_requests_into_groups(activities, hints, groups_dict)
    _collect_branches_into_groups(activities, hints, groups_dict)
    return groups_dict


def _derive_group_metadata(
    group_name: str,
    commits: tuple[CommitInfo, ...],
    merge_requests: tuple[MergeRequestInfo, ...],
    branch_names: tuple[str, ...],
    hints: GroupingHints,
) -> tuple[tuple[str, ...], Literal["feature", "line"], datetime | None]:
    """그룹의 issue_keys, group_kind, last_activity_at을 계산한다 (순수 함수).

    issue_keys: 브랜치명, 커밋 메시지, MR 제목에서 추출한 이슈 키 (중복 제외, 등장 순서 유지)
    group_kind: "feature" (기능) 또는 "line" (release/integration 라인)
    last_activity_at: max(커밋 authored_at, MR updated_at/merged_at), None if 활동 없음

    Args:
        group_name: 그룹명 (branch_names가 빈 그룹의 라인 판별 폴백 — 예: merged MR만 있는 SQA 그룹)
        commits: 그룹의 커밋 튜플
        merge_requests: 그룹의 MR 튜플
        branch_names: 그룹의 브랜치명 튜플
        hints: 설정 힌트

    Returns:
        (issue_keys, group_kind, last_activity_at) 튜플
    """
    # 이슈 키 추출
    all_keys = []
    seen_keys = set()

    # 브랜치명에서
    for branch_name in branch_names:
        keys = extract_issue_keys(branch_name)
        for key in keys:
            if key not in seen_keys:
                all_keys.append(key)
                seen_keys.add(key)

    # 커밋 메시지에서
    for commit in commits:
        keys = extract_issue_keys(commit.message)
        for key in keys:
            if key not in seen_keys:
                all_keys.append(key)
                seen_keys.add(key)

    # MR 제목에서
    for mr in merge_requests:
        keys = extract_issue_keys(mr.title)
        for key in keys:
            if key not in seen_keys:
                all_keys.append(key)
                seen_keys.add(key)

    issue_keys = tuple(all_keys)

    # group_kind 판별: 브랜치명이 모두 라인 패턴이면 "line".
    # branch_names가 빈 그룹(예: merged MR만 있는 SQA/DEVQA)은 그룹명으로 판별한다 —
    # branch-name 폴백 그룹의 이름은 브랜치명과 동일하기 때문.
    group_kind: Literal["feature", "line"] = "feature"
    if branch_names:
        all_are_lines = all(
            is_release_line_branch(bn, hints.release_line_patterns) for bn in branch_names
        )
        if all_are_lines:
            group_kind = "line"
    elif is_release_line_branch(group_name, hints.release_line_patterns):
        group_kind = "line"

    # last_activity_at 계산
    activity_times = []
    for commit in commits:
        activity_times.append(commit.authored_at)
    for mr in merge_requests:
        activity_times.append(mr.updated_at)
        if mr.merged_at:
            activity_times.append(mr.merged_at)

    last_activity_at = max(activity_times) if activity_times else None

    return issue_keys, group_kind, last_activity_at


def _prepare_feature_group_data(
    group_name: str,
    group_data: dict[str, Any],
) -> tuple[
    tuple[CommitInfo, ...],
    tuple[MergeRequestInfo, ...],
    tuple[str, ...],
    tuple[Any, ...],
    str,
    str,
    tuple[str, ...],
]:
    """하나의 그룹 데이터를 FeatureGroup 생성에 필요한 형태로 준비한다."""
    commits = tuple(group_data["commits"])
    mrs = tuple(group_data["merge_requests"])
    branch_names = tuple(sorted(group_data["branch_names"]))
    branch_infos = tuple(group_data["branches"])
    repo_full_path = group_data["repo_full_path"]

    # external MR 표시: evidence에 "[외부 MR]" 접두어 추가
    evidence = group_data["evidence"]
    if any(mr.is_external for mr in mrs):
        evidence = f"[외부 MR] {evidence}"

    participants = aggregate_participants(commits, mrs)

    return commits, mrs, branch_names, branch_infos, repo_full_path, evidence, participants


def _prepare_group_with_stage(
    group_name: str,
    group_data: dict[str, Any],
    now: datetime,
) -> tuple[
    tuple[CommitInfo, ...],
    tuple[MergeRequestInfo, ...],
    tuple[str, ...],
    tuple[Any, ...],
    str,
    str,
    tuple[str, ...],
    Literal["merged", "reviewing", "developing", "other"],
]:
    """하나의 그룹 데이터를 준비하고 stage를 추정한다."""
    commits, mrs, branch_names, branch_infos, repo_full_path, evidence, participants = (
        _prepare_feature_group_data(group_name, group_data)
    )

    # 임시 FeatureGroup으로 stage 추정
    temp_group = FeatureGroup(
        name=group_name,
        source_rule=group_data["source_rule"],
        evidence=evidence,
        stage="other",
        repo_full_path=repo_full_path,
        commits=commits,
        merge_requests=mrs,
        branch_names=branch_names,
        participants=participants,
        branches=branch_infos,
    )
    stage = estimate_stage(temp_group, now)

    return commits, mrs, branch_names, branch_infos, repo_full_path, evidence, participants, stage


def _build_feature_group_from_data(
    group_name: str,
    group_data: dict[str, Any],
    hints: GroupingHints,
    now: datetime,
) -> FeatureGroup:
    """group_data로부터 FeatureGroup을 생성한다."""
    (
        commits,
        mrs,
        branch_names,
        branch_infos,
        repo_full_path,
        evidence,
        participants,
        stage,
    ) = _prepare_group_with_stage(group_name, group_data, now)

    # 작업 상세 내용 파생
    task_summary = _derive_task_summary(commits, mrs, branch_names)

    # 그룹 메타데이터 파생
    issue_keys, group_kind, last_activity_at = _derive_group_metadata(
        group_name, commits, mrs, branch_names, hints
    )

    group = FeatureGroup(
        name=group_name,
        source_rule=group_data["source_rule"],
        evidence=evidence,
        stage=stage,
        repo_full_path=repo_full_path,
        commits=commits,
        merge_requests=mrs,
        branch_names=branch_names,
        participants=participants,
        branches=branch_infos,
        task_summary=task_summary,
        issue_keys=issue_keys,
        group_kind=group_kind,
        last_activity_at=last_activity_at,
    )

    logger.debug(
        f"그룹 '{group_name}' 조립: {len(commits)}개 커밋, {len(mrs)}개 MR, "
        f"{len(branch_names)}개 브랜치, stage={stage}, "
        f"group_kind={group_kind}, repo={repo_full_path}"
    )

    return group


def assemble_groups(
    activities: tuple[RepoActivity, ...],
    hints: GroupingHints,
    now: datetime,
) -> tuple[FeatureGroup, ...]:
    """분류 결과를 FeatureGroup으로 조립한다.

    groups_dict의 키는 (repo_full_path, group_name) 튜플로 정렬한다.
    """
    groups_dict = _collect_classified_items(activities, hints)

    feature_groups = []
    for (_repo_full_path, group_name), group_data in sorted(groups_dict.items()):
        group = _build_feature_group_from_data(group_name, group_data, hints, now)
        feature_groups.append(group)

    return tuple(feature_groups)
