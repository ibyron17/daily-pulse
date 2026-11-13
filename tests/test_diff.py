"""diff 계산 단위 테스트 (6개 케이스)."""

import pytest

from pulse.diff import compute_diff
from pulse.models import FeatureGroup


@pytest.fixture
def base_group() -> FeatureGroup:
    """기본 그룹 생성 헬퍼."""
    return FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="developing",
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/editor-main",),
        participants=("alice",),
    )


def test_compute_diff_new_group(base_group: FeatureGroup) -> None:
    """신규 그룹 감지."""
    today_groups = (base_group,)
    yesterday_groups = ()

    new_groups, stage_changes = compute_diff(today_groups, yesterday_groups)

    assert new_groups == (("test/repo", "에디터"),)
    assert stage_changes == ()


def test_compute_diff_stage_change(base_group: FeatureGroup) -> None:
    """단계 변화 감지."""
    yesterday_version = FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="developing",
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/editor-main",),
        participants=("alice",),
    )
    today_version = FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="reviewing",  # 단계 변화
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/editor-main",),
        participants=("alice",),
    )

    new_groups, stage_changes = compute_diff((today_version,), (yesterday_version,))

    assert new_groups == ()
    assert len(stage_changes) == 1
    assert stage_changes[0].group_name == "에디터"
    assert stage_changes[0].previous_stage == "developing"
    assert stage_changes[0].current_stage == "reviewing"
    assert stage_changes[0].repo_full_path == "test/repo"


def test_compute_diff_no_changes(base_group: FeatureGroup) -> None:
    """변화 없음."""
    new_groups, stage_changes = compute_diff((base_group,), (base_group,))
    assert new_groups == ()
    assert stage_changes == ()


def test_compute_diff_multiple_changes(base_group: FeatureGroup) -> None:
    """신규 그룹 + 단계 변화."""
    yesterday_groups = (base_group,)

    # 어제: 에디터만 있음 (developing)
    # 오늘: 에디터 (reviewing으로 변화) + 캐시 (신규)
    editor_reviewed = FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="reviewing",
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/editor-main",),
        participants=("alice",),
    )
    cache_new = FeatureGroup(
        name="캐시",
        source_rule="label",
        evidence="라벨: cache",
        stage="developing",
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=(),
        participants=("bob",),
    )
    today_groups = (editor_reviewed, cache_new)

    new_groups, stage_changes = compute_diff(today_groups, yesterday_groups)

    assert new_groups == (("test/repo", "캐시"),)
    assert len(stage_changes) == 1
    assert stage_changes[0].group_name == "에디터"


def test_compute_diff_merged_group(base_group: FeatureGroup) -> None:
    """머지된 그룹 감지 (stage: developing → merged)."""
    yesterday_version = FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="developing",
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=("feature/editor-main",),
        participants=("alice",),
    )
    today_version = FeatureGroup(
        name="에디터",
        source_rule="branch",
        evidence="브랜치: feature/editor-*",
        stage="merged",  # 머지됨
        repo_full_path="test/repo",
        commits=(),
        merge_requests=(),
        branch_names=(),
        participants=("alice",),
    )

    new_groups, stage_changes = compute_diff((today_version,), (yesterday_version,))

    assert new_groups == ()
    assert len(stage_changes) == 1
    assert stage_changes[0].current_stage == "merged"


def test_compute_diff_returns_tuple() -> None:
    """compute_diff는 (new_groups, stage_changes) 튜플을 반환한다."""
    groups = ()

    result = compute_diff(groups, groups)

    # compute_diff는 (new_groups, stage_changes) 튜플을 반환
    assert isinstance(result, tuple)
    assert len(result) == 2
    new_groups, stage_changes = result
    assert isinstance(new_groups, tuple)
    assert isinstance(stage_changes, tuple)


# === Phase 1: 단계 변화 필터링 (other 단계 제외) ===
class TestIsRealStageChange:
    """_is_meaningful_stage_change 함수 테스트 (도메인 필터링 로직)."""

    def test_meaningful_developing_to_reviewing(self) -> None:
        """developing → reviewing: 포함."""
        from pulse.diff import _is_meaningful_stage_change

        assert _is_meaningful_stage_change("developing", "reviewing")

    def test_meaningful_reviewing_to_merged(self) -> None:
        """reviewing → merged: 포함."""
        from pulse.diff import _is_meaningful_stage_change

        assert _is_meaningful_stage_change("reviewing", "merged")

    def test_meaningful_merged_to_developing(self) -> None:
        """merged → developing (역방향): 포함."""
        from pulse.diff import _is_meaningful_stage_change

        assert _is_meaningful_stage_change("merged", "developing")

    def test_meaningless_developing_to_other(self) -> None:
        """developing → other: 제외 (분류 실패)."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("developing", "other")

    def test_meaningless_other_to_reviewing(self) -> None:
        """other → reviewing: 제외."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("other", "reviewing")

    def test_meaningless_other_to_other(self) -> None:
        """other → other: 제외."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("other", "other")

    def test_meaningless_reviewing_to_other(self) -> None:
        """reviewing → other: 제외."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("reviewing", "other")

    def test_meaningless_merged_to_other(self) -> None:
        """merged → other: 제외."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("merged", "other")

    def test_meaningless_other_to_developing(self) -> None:
        """other → developing: 제외."""
        from pulse.diff import _is_meaningful_stage_change

        assert not _is_meaningful_stage_change("other", "developing")


class TestDetectStageChangesFiltered:
    """단계 변화 필터링이 적용된 _detect_stage_changes 테스트."""

    def test_detect_stage_changes_excludes_other_transitions(
        self, base_group: FeatureGroup
    ) -> None:
        """developing → other 전이는 제외."""
        yesterday_version = FeatureGroup(
            name="테스트",
            source_rule="branch",
            evidence="브랜치: test-*",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=("test-main",),
            participants=("alice",),
        )
        today_version = FeatureGroup(
            name="테스트",
            source_rule="branch",
            evidence="브랜치: test-*",
            stage="other",  # 분류 실패
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=("alice",),
        )

        from pulse.diff import _detect_stage_changes

        stage_changes = _detect_stage_changes(
            (today_version,),
            {("test/repo", "테스트"): yesterday_version},
        )

        # developing → other 제외되어야 함
        assert len(stage_changes) == 0

    def test_detect_stage_changes_includes_meaningful(self, base_group: FeatureGroup) -> None:
        """developing → reviewing 전이는 포함."""
        yesterday_version = FeatureGroup(
            name="의미",
            source_rule="branch",
            evidence="브랜치: meaning-*",
            stage="developing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=("meaning-main",),
            participants=("alice",),
        )
        today_version = FeatureGroup(
            name="의미",
            source_rule="branch",
            evidence="브랜치: meaning-*",
            stage="reviewing",
            repo_full_path="test/repo",
            commits=(),
            merge_requests=(),
            branch_names=("meaning-main",),
            participants=("alice",),
        )

        from pulse.diff import _detect_stage_changes

        stage_changes = _detect_stage_changes(
            (today_version,),
            {("test/repo", "의미"): yesterday_version},
        )

        # developing → reviewing 포함되어야 함
        assert len(stage_changes) == 1
        assert stage_changes[0].current_stage == "reviewing"
