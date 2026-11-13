"""5단계 분류 규칙: hints → branch → label → directory → scope → unclassified."""

import re
from dataclasses import dataclass
from typing import Literal

from pulse.config.loader import GroupingHints
from pulse.models import CommitInfo, MergeRequestInfo


@dataclass(frozen=True)
class ClassificationResult:
    """한 항목(커밋/MR/브랜치)의 분류 결과."""

    group_name: str
    source_rule: Literal[
        "hints", "branch", "label", "directory", "scope", "branch-name", "unclassified"
    ]
    evidence: str


def is_release_line_branch(branch_name: str, patterns: tuple[str, ...]) -> bool:
    """브랜치명이 release/integration 라인인지 판별 (대소문자 무시, 완전 일치).

    Args:
        branch_name: 브랜치명
        patterns: 라인 패턴 (기본값: main, master, develop, dev, test, sqa, devqa, release, hotfix)

    Returns:
        True if 브랜치명이 패턴 중 하나와 완전 일치 (대소문자 무시)
    """
    normalized_branch = branch_name.lower()
    return any(normalized_branch == pattern.lower() for pattern in patterns)


def extract_bracket_scope(message: str) -> str | None:
    """커밋 메시지 '[type][영역] 제목'에서 영역 추출.

    예: '[feat][auth] 개선' → 'auth'

    Args:
        message: 커밋 메시지

    Returns:
        영역 문자열 또는 None
    """
    match = re.match(r"^\[([^\]]+)\]\[([^\]]+)\]", message)
    if match:
        return match.group(2)
    return None


def extract_issue_keys(text: str) -> tuple[str, ...]:
    """텍스트에서 이슈 키([A-Z][A-Z0-9]+-\\d+) 추출, 등장 순서 유지 중복 제거.

    예: "DOCS-123 and B20C-456" → ("DOCS-123", "B20C-456")

    Args:
        text: 검색 대상 텍스트

    Returns:
        이슈 키 튜플 (중복 제거, 등장 순서 유지)
    """
    matches = re.findall(r"[A-Z][A-Z0-9]+-\d+", text)
    # 중복 제거 (순서 유지)
    seen = set()
    unique_keys = []
    for key in matches:
        if key not in seen:
            seen.add(key)
            unique_keys.append(key)
    return tuple(unique_keys)


def normalize_release_line_name(group_name: str, patterns: tuple[str, ...]) -> str:
    """그룹명이 라인 패턴과 대소문자 무시로 일치하면 패턴 표기(표준형)로 정규화한다.

    같은 배포 흐름이 MR 라벨(예: "DEVQA")과 브랜치명(예: "devqa")으로
    대소문자만 다른 두 그룹으로 갈라지는 것을 막는다.

    Args:
        group_name: 분류 결과 그룹명
        patterns: 라인 패턴 (config release_line_patterns)

    Returns:
        일치 시 패턴 문자열, 아니면 원본 그룹명
    """
    lowered = group_name.lower()
    for pattern in patterns:
        if lowered == pattern.lower():
            return pattern
    return group_name


def extract_ticket_from_branch(branch_name: str) -> str | None:
    """branch에서 ticket 번호 추출 (JIRA-123 또는 #123)."""
    # JIRA-\d+ 패턴
    match = re.search(r"JIRA-\d+", branch_name)
    if match:
        return match.group(0)
    # #\d+ 패턴
    match = re.search(r"#\d+", branch_name)
    if match:
        return match.group(0)
    return None


def extract_prefix_and_name(branch_name: str) -> tuple[str, str] | None:
    """branch에서 prefix와 name 추출."""
    # slash 구분자: feature/something
    if "/" in branch_name:
        parts = branch_name.split("/", 1)
        if len(parts) == 2:
            return (parts[0], parts[1])
    # dash 구분자: feature-something
    if "-" in branch_name:
        parts = branch_name.split("-", 1)
        if len(parts) == 2:
            return (parts[0], parts[1])
    # colon 구분자: feat:auth
    if ":" in branch_name:
        parts = branch_name.split(":", 1)
        if len(parts) == 2:
            return (parts[0], parts[1])
    return None


def extract_scope(message: str) -> str | None:
    """conventional commit message에서 scope 추출."""
    # type(scope): message 패턴
    match = re.match(r"^[a-z]+\(([^)]+)\):", message)
    if match:
        return match.group(1)
    return None


def classify_by_directory(
    changed_files: tuple[str, ...],
    hints: GroupingHints,
) -> ClassificationResult | None:
    """파일 경로 기반 분류 (경로 길이 내림차순으로 정렬)."""
    if not changed_files or not hints.directories:
        return None

    # 경로 길이 내림차순으로 정렬
    sorted_hints = sorted(hints.directories, key=lambda x: len(x[0]), reverse=True)

    for dir_pattern, group_name in sorted_hints:
        for file_path in changed_files:
            if file_path.startswith(dir_pattern):
                return ClassificationResult(
                    group_name=group_name,
                    source_rule="directory",
                    evidence=f"경로 '{file_path}'이 규칙 '{dir_pattern}'과 매칭",
                )
    return None


def _classify_by_hints(
    branch_or_source_branch: str,
    labels: tuple[str, ...] | None,
    hints: GroupingHints,
) -> ClassificationResult | None:
    """hints 규칙으로 분류."""
    # branch_prefixes 확인
    for prefix, group_name in hints.branch_prefixes:
        if branch_or_source_branch.startswith(prefix):
            return ClassificationResult(
                group_name=group_name,
                source_rule="hints",
                evidence=f"브랜치 접두어 '{prefix}' 매칭",
            )

    # labels 확인 (MR 전용)
    if labels:
        for label_hint, group_name in hints.labels:
            if label_hint in labels:
                return ClassificationResult(
                    group_name=group_name,
                    source_rule="hints",
                    evidence=f"라벨 '{label_hint}' 매칭",
                )

    return None


def _classify_by_branch(branch_name: str) -> ClassificationResult | None:
    """branch 규칙으로 분류."""
    # ticket 번호 추출
    ticket = extract_ticket_from_branch(branch_name)
    if ticket:
        return ClassificationResult(
            group_name=ticket,
            source_rule="branch",
            evidence=f"티켓 번호 '{ticket}' 추출",
        )

    # prefix/name 패턴
    prefix_name = extract_prefix_and_name(branch_name)
    if prefix_name:
        prefix, name = prefix_name
        # 알려진 접두어 확인
        if prefix in ("feature", "fix", "feat", "hotfix", "bugfix"):
            return ClassificationResult(
                group_name=name,
                source_rule="branch",
                evidence=f"브랜치 규칙 '{prefix}/*' 매칭",
            )

    return None


def _classify_by_label(labels: tuple[str, ...]) -> ClassificationResult | None:
    """label 규칙으로 분류 (MR 전용)."""
    if labels:
        # 첫 라벨 사용
        group_name = labels[0]
        return ClassificationResult(
            group_name=group_name,
            source_rule="label",
            evidence=f"라벨 '{group_name}' 사용",
        )
    return None


def _classify_by_scope(message: str) -> ClassificationResult | None:
    """scope 규칙으로 분류."""
    scope = extract_scope(message)
    if scope:
        return ClassificationResult(
            group_name=scope,
            source_rule="scope",
            evidence=f"conventional commit scope '{scope}' 추출",
        )
    return None


def classify_commit(
    commit: CommitInfo,
    hints: GroupingHints,
) -> ClassificationResult:
    """커밋의 6단계 분류: hints → branch → directory → scope → branch-name → unclassified."""
    # 1. hints
    result = _classify_by_hints(commit.branch, None, hints)
    if result:
        return result

    # 2. branch
    result = _classify_by_branch(commit.branch)
    if result:
        return result

    # 3. directory
    result = classify_by_directory(commit.changed_files, hints)
    if result:
        return result

    # 4. scope
    result = _classify_by_scope(commit.message)
    if result:
        return result

    # 5. branch-name (폴백)
    if commit.branch:
        return ClassificationResult(
            group_name=commit.branch,
            source_rule="branch-name",
            evidence=f"분류 규칙에 일치하지 않아 브랜치 이름 '{commit.branch}'을 그룹명으로 사용",
        )

    # 6. unclassified (브랜치 정보 없음)
    return ClassificationResult(
        group_name="unclassified",
        source_rule="unclassified",
        evidence="자동 분류 규칙에 일치하는 항목이 없습니다",
    )


def classify_merge_request(
    mr: MergeRequestInfo,
    hints: GroupingHints,
) -> ClassificationResult:
    """MR의 5단계 분류: hints → branch → label → branch-name → unclassified."""
    # 1. hints (branch_prefixes와 labels 모두 확인)
    result = _classify_by_hints(mr.source_branch, mr.labels, hints)
    if result:
        return result

    # 2. branch (source_branch)
    result = _classify_by_branch(mr.source_branch)
    if result:
        return result

    # 3. label
    result = _classify_by_label(mr.labels)
    if result:
        return result

    # 4. branch-name (폴백)
    if mr.source_branch:
        msg = f"분류 규칙에 일치하지 않아 소스 브랜치 '{mr.source_branch}'을 그룹명으로 사용"
        return ClassificationResult(
            group_name=mr.source_branch,
            source_rule="branch-name",
            evidence=msg,
        )

    # 5. unclassified (source_branch 없음)
    return ClassificationResult(
        group_name="unclassified",
        source_rule="unclassified",
        evidence="자동 분류 규칙에 일치하는 항목이 없습니다",
    )


def classify_branch(
    branch_name: str,
    hints: GroupingHints,
) -> ClassificationResult:
    """브랜치명 3단계 분류: hints → branch → branch-name."""
    # 1. hints (branch_prefixes만 확인, labels는 N/A)
    result = _classify_by_hints(branch_name, None, hints)
    if result:
        return result

    # 2. branch
    result = _classify_by_branch(branch_name)
    if result:
        return result

    # 3. branch-name (자동 폴백)
    return ClassificationResult(
        group_name=branch_name,
        source_rule="branch-name",
        evidence=f"분류 규칙에 일치하지 않아 브랜치 이름 '{branch_name}'을 그룹명으로 사용",
    )
