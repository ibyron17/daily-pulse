"""진행 단계 추정 단위 테스트 (Task 2 - stage.py)."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pulse.grouper.stage import estimate_stage, has_review_activity
from pulse.models import FeatureGroup
from tests.conftest import (
    make_branch,
    make_merge_request,
    make_review_event,
)

KST = ZoneInfo("Asia/Seoul")


def make_feature_group(**overrides: Any) -> FeatureGroup:
    """테스트용 FeatureGroup."""
    defaults = {
        "name": "test-feature",
        "source_rule": "branch",
        "evidence": "branch matching",
        "stage": "other",
        "repo_full_path": "org/repo",
        "commits": (),
        "merge_requests": (),
        "branch_names": (),
        "participants": (),
    }
    return FeatureGroup(**{**defaults, **overrides})


class TestHasReviewActivity:
    """has_review_activity 함수 테스트."""

    def test_approved(self) -> None:
        """approved 리뷰."""
        mr = make_merge_request(reviews=(make_review_event(kind="approved"),))
        assert has_review_activity(mr) is True

    def test_changes_requested(self) -> None:
        """changes_requested 리뷰."""
        mr = make_merge_request(reviews=(make_review_event(kind="changes_requested"),))
        assert has_review_activity(mr) is True

    def test_commented(self) -> None:
        """commented 리뷰."""
        mr = make_merge_request(reviews=(make_review_event(kind="commented"),))
        assert has_review_activity(mr) is True

    def test_all_kinds(self) -> None:
        """모든 kind 포함."""
        mr = make_merge_request(
            reviews=(
                make_review_event(kind="approved"),
                make_review_event(kind="changes_requested"),
                make_review_event(kind="commented"),
            )
        )
        assert has_review_activity(mr) is True

    def test_no_reviews(self) -> None:
        """리뷰 없음."""
        mr = make_merge_request(reviews=())
        assert has_review_activity(mr) is False


class TestEstimateStage:
    """estimate_stage 함수 테스트."""

    def test_merged_within_48h(self) -> None:
        """merged_at이 now - 24h인 경우."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        merged_at = now - timedelta(hours=24)
        mr = make_merge_request(
            state="merged",
            merged_at=merged_at,
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "merged"

    def test_merged_at_threshold(self) -> None:
        """merged_at이 정확히 now - 48h인 경우."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        # 정확히 48시간 전: (now - 48h).total_seconds() = 48 * 3600 = 172800
        # 조건: (now - merged_at).total_seconds() < 48 * 3600
        # 따라서 정확히 48시간은 조건을 만족하지 않음
        merged_at = now - timedelta(hours=48)
        mr = make_merge_request(
            state="merged",
            merged_at=merged_at,
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) != "merged"

    def test_merged_outside_48h(self) -> None:
        """merged_at이 now - 72h인 경우."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        merged_at = now - timedelta(hours=72)
        mr = make_merge_request(
            state="merged",
            merged_at=merged_at,
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "other"

    def test_reviewing_with_open_mr_and_review(self) -> None:
        """open MR + 리뷰 활동."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            created_at=now - timedelta(hours=1),
            reviews=(make_review_event(kind="approved"),),
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "reviewing"

    def test_reviewing_with_open_mr_after_24h(self) -> None:
        """open MR + 24시간 이상 경과 (리뷰 활동 없음)."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            created_at=now - timedelta(hours=24, minutes=1),
            reviews=(),
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "reviewing"

    def test_not_reviewing_with_open_mr_before_24h_no_review(self) -> None:
        """open MR + 24시간 미만 + 리뷰 없음 → developing."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            created_at=now - timedelta(hours=23),
            reviews=(),
        )
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "developing"

    def test_developing_with_draft_mr(self) -> None:
        """draft MR가 있으면 developing."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(is_draft=True)
        group = make_feature_group(merge_requests=(mr,))
        assert estimate_stage(group, now) == "developing"

    def test_other_with_old_merged_and_closed(self) -> None:
        """오래된 merged MR과 closed MR만 있으면 other."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        old_merged_mr = make_merge_request(
            state="merged",
            merged_at=now - timedelta(hours=72),
        )
        closed_mr = make_merge_request(
            state="closed",
            merged_at=None,
        )
        group = make_feature_group(merge_requests=(old_merged_mr, closed_mr))
        assert estimate_stage(group, now) == "other"

    def test_other_with_no_activity(self) -> None:
        """활동이 없으면 other."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        group = make_feature_group(
            merge_requests=(),
            branch_names=(),
        )
        assert estimate_stage(group, now) == "other"

    def test_multiple_mrs_merged_priority(self) -> None:
        """여러 MR 중 merged MR이 있고 48시간 이내면 merged."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        closed_mr = make_merge_request(
            state="closed",
            merged_at=None,
        )
        merged_mr = make_merge_request(
            state="merged",
            merged_at=now - timedelta(hours=24),
        )
        group = make_feature_group(merge_requests=(closed_mr, merged_mr))
        assert estimate_stage(group, now) == "merged"

    def test_multiple_mrs_reviewing_priority(self) -> None:
        """merged가 48시간 초과, open이 있으면 reviewing."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        old_merged_mr = make_merge_request(
            state="merged",
            merged_at=now - timedelta(hours=72),
        )
        open_mr = make_merge_request(
            state="open",
            created_at=now - timedelta(hours=25),
            reviews=(),
        )
        group = make_feature_group(merge_requests=(old_merged_mr, open_mr))
        assert estimate_stage(group, now) == "reviewing"

    def test_stage_developing_with_active_branch_only(self) -> None:
        """Arrange: MR 없고 active branch만 있으며 last_pushed_at이 7일 이내.

        Act: estimate_stage 호출.

        Assert: 반환값은 "developing".
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(
            name="feature/active-branch",
            last_pushed_at=now - timedelta(days=3),
        )
        group = make_feature_group(
            merge_requests=(),
            branch_names=("feature/active-branch",),
            branches=(branch,),
        )

        # Act
        stage = estimate_stage(group, now)

        # Assert
        assert stage == "developing"

    def test_stage_active_branch_boundary_inside(self) -> None:
        """Arrange: branch.last_pushed_at이 now - 6d 23h (7일 미만).

        Act: estimate_stage 호출.

        Assert: 반환값은 "developing".
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(
            name="feature/fresh-branch",
            last_pushed_at=now - timedelta(days=6, hours=23),
        )
        group = make_feature_group(
            merge_requests=(),
            branch_names=("feature/fresh-branch",),
            branches=(branch,),
        )

        # Act
        stage = estimate_stage(group, now)

        # Assert
        assert stage == "developing"

    def test_stage_active_branch_boundary_outside(self) -> None:
        """Arrange: branch.last_pushed_at이 now - 7d 1h (7일 초과).

        Act: estimate_stage 호출.

        Assert: 반환값은 "other".
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(
            name="feature/stale-branch",
            last_pushed_at=now - timedelta(days=7, hours=1),
        )
        group = make_feature_group(
            merge_requests=(),
            branch_names=("feature/stale-branch",),
            branches=(branch,),
        )

        # Act
        stage = estimate_stage(group, now)

        # Assert
        assert stage == "other"

    def test_stage_branch_without_pushed_at_not_active(self) -> None:
        """Arrange: branch.last_pushed_at이 None (활성 상태 판단 불가).

        Act: estimate_stage 호출.

        Assert: 반환값은 "other".
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(
            name="feature/no-timestamp",
            last_pushed_at=None,
        )
        group = make_feature_group(
            merge_requests=(),
            branch_names=("feature/no-timestamp",),
            branches=(branch,),
        )

        # Act
        stage = estimate_stage(group, now)

        # Assert
        assert stage == "other"
