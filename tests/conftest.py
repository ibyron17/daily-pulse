"""테스트 고정물 팩토리 (Phase 2·3 병렬 개발용)."""

from datetime import datetime
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from pulse.models import (
    BranchInfo,
    CommitInfo,
    FeatureGroup,
    MergeRequestInfo,
    RepoActivity,
    RepoRef,
    ReviewEvent,
    WarningSignal,
)

KST = ZoneInfo("Asia/Seoul")


def make_repo_ref(**overrides: Any) -> RepoRef:
    """테스트용 RepoRef. 기본값은 실제 팀 레포와 동일한 형태."""
    defaults: dict[str, Any] = {
        "provider": "gitlab",
        "base_url": "https://gitlab.example.com",
        "namespace": "sample-group",
        "name": "sample-repo",
        "web_url": "https://gitlab.example.com/sample-group/sample-repo",
    }
    return RepoRef(**{**defaults, **overrides})


def make_commit(**overrides: Any) -> CommitInfo:
    """테스트용 CommitInfo."""
    defaults: dict[str, Any] = {
        "sha": "abc123def456",
        "author_name": "hong-gildong",
        "authored_at": datetime(2026, 7, 15, 9, 0, tzinfo=KST),
        "message": "feat: 에디터 자동 저장",
        "branch": "feature/editor-autosave",
        "changed_files": ("src/editor.ts", "src/components/Editor.tsx"),
        "web_url": "https://gitlab.example.com/sample-group/sample-repo/-/commit/abc123def456",
    }
    return CommitInfo(**{**defaults, **overrides})


def make_branch(**overrides: Any) -> BranchInfo:
    """테스트용 BranchInfo."""
    defaults: dict[str, Any] = {
        "name": "develop",
        "last_commit_sha": "abc123def456",
        "last_pushed_at": datetime(2026, 7, 15, 9, 0, tzinfo=KST),
        "web_url": "https://gitlab.example.com/sample-group/sample-repo/-/tree/develop",
    }
    return BranchInfo(**{**defaults, **overrides})


def make_review_event(**overrides: Any) -> ReviewEvent:
    """테스트용 ReviewEvent."""
    defaults: dict[str, Any] = {
        "kind": "approved",
        "actor_name": "reviewer",
        "occurred_at": datetime(2026, 7, 15, 10, 0, tzinfo=KST),
    }
    return ReviewEvent(**{**defaults, **overrides})


def make_merge_request(**overrides: Any) -> MergeRequestInfo:
    """테스트용 MergeRequestInfo. 기본값은 리뷰 없는 open MR."""
    defaults: dict[str, Any] = {
        "iid": 42,
        "title": "feat: 에디터 자동 저장",
        "state": "open",
        "is_draft": False,
        "labels": (),
        "source_branch": "feature/editor-autosave",
        "target_branch": "develop",
        "author_name": "hong-gildong",
        "created_at": datetime(2026, 7, 14, 9, 0, tzinfo=KST),
        "updated_at": datetime(2026, 7, 15, 9, 0, tzinfo=KST),
        "merged_at": None,
        "reviews": (),
        "is_external": False,
        "web_url": "https://gitlab.example.com/sample-group/sample-repo/-/merge_requests/42",
    }
    return MergeRequestInfo(**{**defaults, **overrides})


def make_repo_activity(**overrides: Any) -> RepoActivity:
    """테스트용 RepoActivity."""
    defaults: dict[str, Any] = {
        "repo": make_repo_ref(),
        "status": "ok",
        "failure_reason": None,
        "commits": (make_commit(),),
        "active_branches": (make_branch(),),
        "created_branches": (),
        "deleted_branches": (),
        "merge_requests": (make_merge_request(),),
        "collected_at": datetime(2026, 7, 15, 12, 0, tzinfo=KST),
        "stale_branches": (),
    }
    return RepoActivity(**{**defaults, **overrides})


def make_feature_group(**overrides: Any) -> FeatureGroup:
    """테스트용 FeatureGroup."""
    defaults: dict[str, Any] = {
        "name": "test-feature",
        "source_rule": "hints",
        "evidence": "1 commit",
        "stage": "developing",
        "repo_full_path": "sample-group/sample-repo",
        "commits": (make_commit(),),
        "merge_requests": (),
        "branch_names": ("feature/test",),
        "participants": ("hong-gildong",),
        "branches": (),
    }
    return FeatureGroup(**{**defaults, **overrides})


def make_warning_signal(**overrides: Any) -> WarningSignal:
    """테스트용 WarningSignal."""
    defaults: dict[str, Any] = {
        "kind": "stale_mr",
        "title": "MR 검토 대기 중",
        "description": "3일 이상 리뷰 대기",
        "days": 3,
        "web_url": "https://gitlab.example.com/sample-group/sample-repo/-/merge_requests/42",
        "repo_full_path": "sample-group/sample-repo",
    }
    return WarningSignal(**{**defaults, **overrides})


@pytest.fixture
def mock_keyring() -> Any:
    """keyring을 모킹한 fixture."""
    with patch("pulse.secrets.keyring") as mock_kr:
        # 기본값: get_password/set_password/delete_password는 None 반환
        mock_kr.get_password.return_value = None
        mock_kr.set_password.return_value = None
        mock_kr.delete_password.return_value = None
        yield mock_kr


@pytest.fixture(autouse=True)
def mock_gh_cli() -> Any:
    """gh CLI를 기본적으로 모킹 (모든 테스트에서 사용).

    resolve_token의 gh 폴백이 테스트 환경에서 실제 gh CLI를 호출하지 않도록 한다.
    """
    with patch("pulse.secrets.subprocess.run") as mock_run:
        # 기본값: FileNotFoundError (gh CLI 미설치)
        mock_run.side_effect = FileNotFoundError("gh not found")
        yield mock_run
