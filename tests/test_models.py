"""모델 불변성 및 직렬화 테스트."""

import json
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from pulse.models import activity_from_dict, activity_to_dict
from tests.conftest import (
    KST,
    make_commit,
    make_merge_request,
    make_repo_activity,
    make_repo_ref,
    make_review_event,
)


class TestModelsImmutability:
    """모델 불변성 테스트."""

    def test_models_are_immutable(self) -> None:
        """frozen dataclass는 필드 대입을 거부한다."""
        commit = make_commit()
        with pytest.raises(FrozenInstanceError):
            commit.sha = "modified"  # type: ignore[misc]  # 불변성 검증을 위한 의도적 타입 위반


class TestRepoRef:
    """RepoRef 속성 테스트."""

    def test_repo_ref_full_path(self) -> None:
        """full_path 속성이 정확히 계산된다."""
        repo = make_repo_ref()
        assert repo.full_path == "sample-group/sample-repo"

    def test_repo_ref_slug(self) -> None:
        """slug 속성이 슬래시를 __ 로 변환한다."""
        repo = make_repo_ref()
        assert repo.slug == "sample-group__sample-repo"


class TestActivityRoundTrip:
    """RepoActivity 직렬화 round-trip 테스트."""

    def test_activity_round_trip_preserves_all_fields(self) -> None:
        """모든 필드가 round-trip에서 보존된다."""
        original = make_repo_activity(
            commits=(make_commit(), make_commit(sha="xyz789")),
            merge_requests=(
                make_merge_request(),
                make_merge_request(
                    iid=43,
                    state="merged",
                    merged_at=datetime(2026, 7, 15, 14, 0, tzinfo=KST),
                    reviews=(make_review_event(), make_review_event(kind="changes_requested")),
                ),
            ),
            deleted_branches=("old-feature", "hotfix-123"),
        )
        data = activity_to_dict(original)
        restored = activity_from_dict(data)
        assert restored == original

    def test_activity_round_trip_preserves_timezone(self) -> None:
        """timezone-aware datetime이 round-trip에서 offset을 유지한다."""
        original = make_repo_activity()
        data = activity_to_dict(original)
        restored = activity_from_dict(data)
        # 원본과 복원본의 UTC offset이 같아야 한다
        orig_offset = original.commits[0].authored_at.utcoffset()
        restored_offset = restored.commits[0].authored_at.utcoffset()
        assert orig_offset == restored_offset

    def test_activity_to_dict_is_json_serializable(self) -> None:
        """activity_to_dict의 결과가 JSON 직렬화 가능하다."""
        original = make_repo_activity()
        data = activity_to_dict(original)
        # json.dumps가 성공해야 한다
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_failed_activity_round_trip(self) -> None:
        """status='failed'인 activity도 round-trip된다."""
        original = make_repo_activity(
            status="failed",
            failure_reason="401 Unauthorized: 토큰 만료",
            commits=(),
            active_branches=(),
            merge_requests=(),
        )
        data = activity_to_dict(original)
        restored = activity_from_dict(data)
        assert restored == original
        assert restored.status == "failed"
        assert restored.failure_reason == "401 Unauthorized: 토큰 만료"

    def test_activity_with_none_fields(self) -> None:
        """Optional 필드(merged_at, failure_reason 등)가 None일 때 round-trip된다."""
        original = make_repo_activity(
            merge_requests=(make_merge_request(merged_at=None),),
            failure_reason=None,
        )
        data = activity_to_dict(original)
        restored = activity_from_dict(data)
        assert restored == original
        assert restored.merge_requests[0].merged_at is None
        assert restored.failure_reason is None

    def test_repo_ref_with_nickname(self) -> None:
        """nickname이 지정되면 display_name이 nickname을 반환."""
        repo = make_repo_ref(nickname="프론트엔드")
        assert repo.display_name == "프론트엔드"

    def test_repo_ref_without_nickname_fallback(self) -> None:
        """nickname이 없으면 display_name이 full_path를 반환."""
        repo = make_repo_ref(nickname=None)
        assert repo.display_name == "sample-group/sample-repo"

    def test_repo_ref_subtree_path_defaults_to_none(self) -> None:
        """subtree_path를 지정하지 않으면 기본값은 None."""
        repo = make_repo_ref()
        assert repo.subtree_path is None


class TestRepoRefSubtreePathSerialization:
    """RepoRef.subtree_path 직렬화 round-trip 및 하위 호환 테스트."""

    def test_round_trip_preserves_subtree_path(self) -> None:
        """subtree_path가 설정된 RepoActivity는 round-trip에서 보존된다."""
        original = make_repo_activity(repo=make_repo_ref(subtree_path="sample-model"))
        data = activity_to_dict(original)
        restored = activity_from_dict(data)
        assert restored.repo.subtree_path == "sample-model"
        assert restored == original

    def test_missing_subtree_path_key_restores_to_none(self) -> None:
        """subtree_path 키가 없는 과거 raw dict(data/raw)는 None으로 복원된다 (하위 호환)."""
        original = make_repo_activity()
        data = activity_to_dict(original)
        del data["repo"]["subtree_path"]
        restored = activity_from_dict(data)
        assert restored.repo.subtree_path is None
