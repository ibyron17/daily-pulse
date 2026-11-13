"""신규 작업 신호 생성 단위 테스트 (Task 4 - signals.py)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pulse.grouper.signals import generate_new_work_signals
from tests.conftest import make_branch, make_merge_request, make_repo_activity

KST = ZoneInfo("Asia/Seoul")


class TestGenerateNewWorkSignals:
    """generate_new_work_signals 함수 테스트."""

    def test_created_branch_no_lookback_filter(self) -> None:
        """created_branches는 lookback 필터 없이 모두 신규로 취급."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity = make_repo_activity(
            created_branches=("feature/new-1", "feature/new-2"),
            active_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        # created_branches는 모두 신규
        assert len(signals) == 2
        titles = [s.title for s in signals]
        assert "feature/new-1" in titles
        assert "feature/new-2" in titles

    def test_new_mr_within_lookback(self) -> None:
        """신규 MR: created_at이 lookback_hours 이내."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        new_mr = make_merge_request(
            title="New MR",
            created_at=now - timedelta(hours=12),
        )
        activity = make_repo_activity(
            merge_requests=(new_mr,),
            created_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 1
        assert signals[0].title == "New MR"
        assert signals[0].branch_or_mr == "!42"  # default iid

    def test_old_mr_outside_lookback(self) -> None:
        """오래된 MR: created_at이 lookback_hours 이상 경과."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        old_mr = make_merge_request(
            title="Old MR",
            created_at=now - timedelta(hours=48),
        )
        activity = make_repo_activity(
            merge_requests=(old_mr,),
            created_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 0

    def test_web_url_from_active_branch_match(self) -> None:
        """web_url: active_branches에서 이름 매칭."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        active_branch = make_branch(
            name="feature/new-branch",
            web_url="http://example.com/branch/feature/new-branch",
        )
        activity = make_repo_activity(
            created_branches=("feature/new-branch",),
            active_branches=(active_branch,),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 1
        # active_branches에서 매칭된 web_url 사용
        assert signals[0].web_url == "http://example.com/branch/feature/new-branch"

    def test_web_url_fallback_to_repo(self) -> None:
        """web_url 폴백: active_branches에 매칭 없으면 repo.web_url."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity = make_repo_activity(
            created_branches=("feature/unknown-branch",),
            active_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 1
        # repo.web_url로 폴백
        assert signals[0].web_url == "https://gitlab.example.com/sample-group/sample-repo"

    def test_mixed_new_items(self) -> None:
        """created_branches + new MRs 혼합."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        new_mr = make_merge_request(
            title="New MR",
            created_at=now - timedelta(hours=12),
        )
        activity = make_repo_activity(
            created_branches=("feature/new",),
            merge_requests=(new_mr,),
            active_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 2
        titles = [s.title for s in signals]
        assert "feature/new" in titles
        assert "New MR" in titles

    def test_empty_activities(self) -> None:
        """활동이 없으면 신호 없음."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity = make_repo_activity(
            created_branches=(),
            merge_requests=(),
            active_branches=(),
        )
        signals = generate_new_work_signals((activity,), now, lookback_hours=24)
        assert len(signals) == 0

    def test_multiple_repos(self) -> None:
        """여러 레포의 신규 항목을 모두 수집."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        activity1 = make_repo_activity(
            created_branches=("feature/new-1",),
            merge_requests=(),
        )
        activity2 = make_repo_activity(
            created_branches=("feature/new-2",),
            merge_requests=(),
        )
        signals = generate_new_work_signals((activity1, activity2), now, lookback_hours=24)
        assert len(signals) == 2
