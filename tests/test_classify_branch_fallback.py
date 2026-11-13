"""R4: 분류 폴백 (branch-name) 테스트."""

from datetime import datetime

import pytest

from pulse.config.loader import GroupingHints
from pulse.grouper.classify import classify_branch, classify_commit, classify_merge_request
from pulse.models import CommitInfo, MergeRequestInfo


@pytest.fixture
def empty_hints() -> GroupingHints:
    """빈 힌트."""
    return GroupingHints(
        branch_prefixes=(),
        labels=(),
        directories=(),
    )


def test_classify_commit_branch_name_fallback(empty_hints: GroupingHints) -> None:
    """commit: 분류 규칙 미적용 시 branch-name 폴백."""
    commit = CommitInfo(
        sha="abc123",
        author_name="Alice",
        authored_at=datetime.now(),
        message="random commit",
        branch="develop",
        changed_files=(),
        web_url="http://example.com/commit/abc123",
    )

    result = classify_commit(commit, empty_hints)

    assert result.source_rule == "branch-name"
    assert result.group_name == "develop"


def test_classify_commit_unclassified_no_branch(empty_hints: GroupingHints) -> None:
    """commit: 브랜치 정보 없으면 unclassified."""
    commit = CommitInfo(
        sha="abc123",
        author_name="Alice",
        authored_at=datetime.now(),
        message="random commit",
        branch="",  # 빈 브랜치
        changed_files=(),
        web_url="http://example.com/commit/abc123",
    )

    result = classify_commit(commit, empty_hints)

    assert result.source_rule == "unclassified"
    assert result.group_name == "unclassified"


def test_classify_mr_source_branch_fallback(empty_hints: GroupingHints) -> None:
    """MR: 규칙 미적용 브랜치로 branch-name 폴백."""
    # myfeature (규칙 미적용: feature/* 패턴 아님)
    mr = MergeRequestInfo(
        iid=1,
        title="Feature MR",
        state="open",
        is_draft=False,
        labels=(),
        source_branch="myfeature",
        target_branch="main",
        author_name="Alice",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url="http://example.com/mr/1",
    )

    result = classify_merge_request(mr, empty_hints)

    assert result.source_rule == "branch-name"
    assert result.group_name == "myfeature"


def test_classify_mr_unclassified_no_source_branch(empty_hints: GroupingHints) -> None:
    """MR: source_branch 없으면 unclassified."""
    mr = MergeRequestInfo(
        iid=1,
        title="Feature MR",
        state="open",
        is_draft=False,
        labels=(),
        source_branch="",  # 빈 source_branch
        target_branch="main",
        author_name="Alice",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        merged_at=None,
        reviews=(),
        is_external=False,
        web_url="http://example.com/mr/1",
    )

    result = classify_merge_request(mr, empty_hints)

    assert result.source_rule == "unclassified"


def test_classify_branch_name_fallback(empty_hints: GroupingHints) -> None:
    """branch: 분류 규칙 미적용 시 자동 branch-name 폴백."""
    result = classify_branch("develop", empty_hints)

    assert result.source_rule == "branch-name"
    assert result.group_name == "develop"


def test_classify_branch_always_branch_name(empty_hints: GroupingHints) -> None:
    """branch: unclassified는 절대 반환하지 않음."""
    # feature/something (규칙 매칭 없음)
    result = classify_branch("random-branch-name", empty_hints)

    assert result.source_rule == "branch-name"
    assert result.group_name == "random-branch-name"
