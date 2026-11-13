"""Round 6 데이터 모델 (GroupLifecycleView, PromotionRung, ReleaseTrain) 단위 테스트."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pulse.models import (
    DashboardModel,
    GroupLifecycleView,
    PromotionRung,
    ReleaseTrain,
    activity_from_dict,
    activity_to_dict,
)
from tests.conftest import make_merge_request, make_repo_activity

KST = ZoneInfo("Asia/Seoul")


class TestGroupLifecycleView:
    """GroupLifecycleView 기본값 테스트."""

    def test_create_lifecycle_view(self) -> None:
        """GroupLifecycleView 생성."""
        view = GroupLifecycleView(
            first_seen="2026-07-21",
            total_days=7,
            current_stage="reviewing",
            current_stage_days=2,
            active_days=6,
            cumulative_commits=15,
        )
        assert view.first_seen == "2026-07-21"
        assert view.total_days == 7
        assert view.current_stage == "reviewing"
        assert view.current_stage_days == 2
        assert view.active_days == 6
        assert view.cumulative_commits == 15

    def test_lifecycle_view_frozen(self) -> None:
        """GroupLifecycleView는 frozen."""
        view = GroupLifecycleView(
            first_seen="2026-07-21",
            total_days=7,
            current_stage="reviewing",
            current_stage_days=2,
            active_days=6,
            cumulative_commits=15,
        )
        with pytest.raises(AttributeError):
            view.total_days = 8  # type: ignore


class TestPromotionRung:
    """PromotionRung 기본값 테스트."""

    def test_create_promotion_rung(self) -> None:
        """PromotionRung 생성."""
        rung = PromotionRung(
            source="develop",
            target="devqa",
            last_merged_at=datetime(2026, 7, 24, 10, 0, tzinfo=KST),
            last_mr_iid=123,
            merged_count=11,
            open_count=1,
        )
        assert rung.source == "develop"
        assert rung.target == "devqa"
        assert rung.last_merged_at == datetime(2026, 7, 24, 10, 0, tzinfo=KST)
        assert rung.last_mr_iid == 123
        assert rung.merged_count == 11
        assert rung.open_count == 1

    def test_promotion_rung_none_merged_at(self) -> None:
        """PromotionRung의 merged_at이 None인 경우."""
        rung = PromotionRung(
            source="sqa",
            target="master",
            last_merged_at=None,
            last_mr_iid=None,
            merged_count=0,
            open_count=2,
        )
        assert rung.last_merged_at is None
        assert rung.last_mr_iid is None
        assert rung.merged_count == 0
        assert rung.open_count == 2


class TestReleaseTrain:
    """ReleaseTrain 기본값 테스트."""

    def test_create_empty_release_train(self) -> None:
        """빈 ReleaseTrain 생성 (기본값)."""
        train = ReleaseTrain()
        assert train.rungs == ()

    def test_create_release_train_with_rungs(self) -> None:
        """rungs를 가진 ReleaseTrain 생성."""
        rungs = (
            PromotionRung(
                source="develop",
                target="devqa",
                last_merged_at=datetime(2026, 7, 24, 10, 0, tzinfo=KST),
                last_mr_iid=123,
                merged_count=11,
                open_count=1,
            ),
            PromotionRung(
                source="devqa",
                target="sqa",
                last_merged_at=datetime(2026, 7, 24, 9, 0, tzinfo=KST),
                last_mr_iid=122,
                merged_count=5,
                open_count=0,
            ),
        )
        train = ReleaseTrain(rungs=rungs)
        assert len(train.rungs) == 2
        assert train.rungs[0].source == "develop"
        assert train.rungs[1].source == "devqa"


class TestFeatureGroupLifecycle:
    """FeatureGroup에 lifecycle 필드 추가 테스트."""

    def test_feature_group_without_lifecycle(self) -> None:
        """lifecycle이 없는 FeatureGroup (기본값 None)."""
        from tests.conftest import make_feature_group

        group = make_feature_group()
        assert group.lifecycle is None

    def test_feature_group_with_lifecycle(self) -> None:
        """lifecycle이 있는 FeatureGroup."""
        from tests.conftest import make_feature_group

        lifecycle = GroupLifecycleView(
            first_seen="2026-07-21",
            total_days=7,
            current_stage="reviewing",
            current_stage_days=2,
            active_days=6,
            cumulative_commits=15,
        )
        group = make_feature_group(lifecycle=lifecycle)
        assert group.lifecycle == lifecycle
        assert group.lifecycle.first_seen == "2026-07-21"


class TestRepoActivityRecentMRs:
    """RepoActivity의 recent_merge_requests 필드 테스트."""

    def test_repo_activity_without_recent_mrs(self) -> None:
        """recent_merge_requests가 없는 RepoActivity (기본값 빈 튜플)."""
        activity = make_repo_activity()
        assert activity.recent_merge_requests == ()

    def test_repo_activity_with_recent_mrs(self) -> None:
        """recent_merge_requests가 있는 RepoActivity."""
        mr1 = make_merge_request(iid=10, source_branch="develop", target_branch="devqa")
        mr2 = make_merge_request(iid=11, source_branch="devqa", target_branch="sqa")
        activity = make_repo_activity(recent_merge_requests=(mr1, mr2))
        assert len(activity.recent_merge_requests) == 2
        assert activity.recent_merge_requests[0].iid == 10
        assert activity.recent_merge_requests[1].iid == 11

    def test_repo_activity_serialize_recent_mrs(self) -> None:
        """RepoActivity를 직렬화할 때 recent_merge_requests 포함."""
        mr = make_merge_request(iid=10, source_branch="develop", target_branch="devqa")
        activity = make_repo_activity(recent_merge_requests=(mr,))
        serialized = activity_to_dict(activity)
        assert "recent_merge_requests" in serialized
        assert len(serialized["recent_merge_requests"]) == 1
        assert serialized["recent_merge_requests"][0]["iid"] == 10

    def test_repo_activity_deserialize_recent_mrs(self) -> None:
        """RepoActivity 역직렬화 시 recent_merge_requests 복원."""
        mr = make_merge_request(iid=10, source_branch="develop", target_branch="devqa")
        activity = make_repo_activity(recent_merge_requests=(mr,))
        serialized = activity_to_dict(activity)
        deserialized = activity_from_dict(serialized)
        assert len(deserialized.recent_merge_requests) == 1
        assert deserialized.recent_merge_requests[0].iid == 10
        assert deserialized.recent_merge_requests[0].source_branch == "develop"

    def test_repo_activity_deserialize_legacy_no_recent_mrs(self) -> None:
        """구버전 raw dict(recent_merge_requests 키 없음) 로드 시 빈 튜플 폴백."""
        activity = make_repo_activity()
        serialized = activity_to_dict(activity)
        # recent_merge_requests 키 제거 (구버전 raw 시뮬레이션)
        del serialized["recent_merge_requests"]
        deserialized = activity_from_dict(serialized)
        assert deserialized.recent_merge_requests == ()

    def test_repo_activity_deserialize_legacy_empty_list(self) -> None:
        """구버전 raw dict에 빈 리스트가 있는 경우."""
        activity = make_repo_activity()
        serialized = activity_to_dict(activity)
        serialized["recent_merge_requests"] = []
        deserialized = activity_from_dict(serialized)
        assert deserialized.recent_merge_requests == ()


class TestDashboardModelReleaseTrain:
    """DashboardModel의 repo_release_trains 필드 테스트."""

    def test_dashboard_model_without_release_trains(self) -> None:
        """repo_release_trains이 없는 DashboardModel (기본값 빈 튜플)."""
        from tests.conftest import make_feature_group

        dashboard = DashboardModel(
            team_name="test-team",
            report_date=__import__("datetime").date(2026, 7, 27),
            lookback_hours=24,
            summary_line="1 project · 5 commits",
            groups=(make_feature_group(),),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
        )
        assert dashboard.repo_release_trains == ()

    def test_dashboard_model_with_release_trains(self) -> None:
        """repo_release_trains이 있는 DashboardModel."""
        from tests.conftest import make_feature_group

        rung = PromotionRung(
            source="develop",
            target="devqa",
            last_merged_at=datetime(2026, 7, 24, 10, 0, tzinfo=KST),
            last_mr_iid=123,
            merged_count=11,
            open_count=1,
        )
        train = ReleaseTrain(rungs=(rung,))
        dashboard = DashboardModel(
            team_name="test-team",
            report_date=__import__("datetime").date(2026, 7, 27),
            lookback_hours=24,
            summary_line="1 project · 5 commits",
            groups=(make_feature_group(),),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repo_release_trains=(("sample-group/sample-repo", train),),
        )
        assert len(dashboard.repo_release_trains) == 1
        assert dashboard.repo_release_trains[0][0] == "sample-group/sample-repo"
        assert len(dashboard.repo_release_trains[0][1].rungs) == 1


class TestBackwardCompatibility:
    """기존 코드와의 하위호환성 테스트."""

    def test_feature_group_creation_unchanged(self) -> None:
        """기존 FeatureGroup 생성 방식이 여전히 작동."""
        from tests.conftest import make_feature_group

        # 기존 방식: lifecycle을 전달하지 않음
        group = make_feature_group()
        assert group.name == "test-feature"
        assert group.stage == "developing"
        assert group.lifecycle is None

    def test_repo_activity_creation_unchanged(self) -> None:
        """기존 RepoActivity 생성 방식이 여전히 작동."""
        activity = make_repo_activity()
        assert activity.repo.namespace == "sample-group"
        assert activity.recent_merge_requests == ()

    def test_dashboard_model_creation_unchanged(self) -> None:
        """기존 DashboardModel 생성 방식이 여전히 작동."""
        from tests.conftest import make_feature_group

        dashboard = DashboardModel(
            team_name="test-team",
            report_date=__import__("datetime").date(2026, 7, 27),
            lookback_hours=24,
            summary_line="1 project · 5 commits",
            groups=(make_feature_group(),),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
        )
        assert dashboard.team_name == "test-team"
        assert dashboard.repo_release_trains == ()
