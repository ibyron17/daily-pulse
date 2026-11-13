"""정체 감지 단위 테스트 (Task 3 - stagnation.py)."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pulse.config.loader import StagnationThresholds
from pulse.grouper.stagnation import (
    detect_revert_or_hotfix,
    detect_stagnation_signals,
    detect_stale_branch,
    detect_stale_mr,
)
from pulse.models import FeatureGroup
from tests.conftest import (
    make_branch,
    make_commit,
    make_merge_request,
)

KST = ZoneInfo("Asia/Seoul")


def make_feature_group_for_stagnation(**overrides: Any) -> FeatureGroup:
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


class TestDetectStaleMr:
    """detect_stale_mr 함수 테스트."""

    def test_stale_mr_exactly_threshold(self) -> None:
        """updated_at이 정확히 임계값."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        updated_at = now - timedelta(days=3)
        mr = make_merge_request(
            state="open",
            updated_at=updated_at,
        )
        result = detect_stale_mr(mr, now, threshold_days=3)
        assert result is not None
        assert result.kind == "stale_mr"
        assert result.days == 3

    def test_stale_mr_beyond_threshold(self) -> None:
        """updated_at이 임계값 초과."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        updated_at = now - timedelta(days=5)
        mr = make_merge_request(
            state="open",
            updated_at=updated_at,
        )
        result = detect_stale_mr(mr, now, threshold_days=3)
        assert result is not None
        assert result.days == 5

    def test_not_stale_mr(self) -> None:
        """updated_at이 임계값 이내."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        updated_at = now - timedelta(days=2)
        mr = make_merge_request(
            state="open",
            updated_at=updated_at,
        )
        result = detect_stale_mr(mr, now, threshold_days=3)
        assert result is None

    def test_closed_mr_not_stale(self) -> None:
        """closed MR은 정체 신호 아님."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        updated_at = now - timedelta(days=10)
        mr = make_merge_request(
            state="closed",
            updated_at=updated_at,
        )
        result = detect_stale_mr(mr, now, threshold_days=3)
        assert result is None


class TestDetectStaleBranch:
    """detect_stale_branch 함수 테스트."""

    def test_stale_branch_exactly_threshold(self) -> None:
        """last_pushed_at이 정확히 임계값."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        last_pushed_at = now - timedelta(days=7)
        branch = make_branch(last_pushed_at=last_pushed_at)
        result = detect_stale_branch(branch, now, threshold_days=7)
        assert result is not None
        assert result.kind == "stale_branch"
        assert result.days == 7

    def test_stale_branch_beyond_threshold(self) -> None:
        """last_pushed_at이 임계값 초과."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        last_pushed_at = now - timedelta(days=10)
        branch = make_branch(last_pushed_at=last_pushed_at)
        result = detect_stale_branch(branch, now, threshold_days=7)
        assert result is not None
        assert result.days == 10

    def test_not_stale_branch(self) -> None:
        """last_pushed_at이 임계값 이내."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        last_pushed_at = now - timedelta(days=5)
        branch = make_branch(last_pushed_at=last_pushed_at)
        result = detect_stale_branch(branch, now, threshold_days=7)
        assert result is None

    def test_stale_branch_null_last_pushed(self) -> None:
        """last_pushed_at=None인 경우 days=None, 신호 생성."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(last_pushed_at=None)
        result = detect_stale_branch(branch, now, threshold_days=7)
        assert result is not None
        assert result.kind == "stale_branch"
        assert result.days is None


class TestDetectRevertOrHotfix:
    """detect_revert_or_hotfix 함수 테스트."""

    def test_revert_commit(self) -> None:
        """revert 커밋 감지 (소문자)."""
        commits = (make_commit(message="revert: undo bad change"),)
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 1
        assert results[0].kind == "revert_commit"

    def test_revert_commit_uppercase(self) -> None:
        """Revert 커밋 감지 (대문자)."""
        commits = (make_commit(message="Revert: undo bad change"),)
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 1
        assert results[0].kind == "revert_commit"

    def test_hotfix_commit(self) -> None:
        """hotfix 커밋 감지 (소문자)."""
        commits = (make_commit(message="hotfix: critical bug"),)
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 1
        assert results[0].kind == "hotfix_commit"

    def test_hotfix_commit_uppercase(self) -> None:
        """Hotfix 커밋 감지 (대문자)."""
        commits = (make_commit(message="Hotfix: critical bug"),)
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 1
        assert results[0].kind == "hotfix_commit"

    def test_no_revert_or_hotfix(self) -> None:
        """revert/hotfix 커밋 없음."""
        commits = (
            make_commit(message="feat: add feature"),
            make_commit(message="fix: minor bug"),
        )
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 0

    def test_multiple_commits_mixed(self) -> None:
        """여러 커밋 중 일부는 revert/hotfix."""
        commits = (
            make_commit(message="feat: add feature"),
            make_commit(message="revert: undo"),
            make_commit(message="hotfix: critical"),
        )
        results = detect_revert_or_hotfix(commits)
        assert len(results) == 2
        kinds = [r.kind for r in results]
        assert "revert_commit" in kinds
        assert "hotfix_commit" in kinds


class TestDetectStagnationSignals:
    """detect_stagnation_signals 함수 테스트 (신호 중복 방지)."""

    def test_no_signals(self) -> None:
        """정체 신호 없음."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(state="closed")
        group = make_feature_group_for_stagnation(merge_requests=(mr,))
        thresholds = StagnationThresholds()
        results = detect_stagnation_signals(group, now, thresholds)
        assert len(results) == 0

    def test_single_stale_mr(self) -> None:
        """stale MR 신호 정확히 1건."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            updated_at=now - timedelta(days=5),
        )
        group = make_feature_group_for_stagnation(merge_requests=(mr,))
        thresholds = StagnationThresholds(review_waiting_days=3)
        results = detect_stagnation_signals(group, now, thresholds)
        stale_mr_results = [r for r in results if r.kind == "stale_mr"]
        assert len(stale_mr_results) == 1

    def test_multiple_stale_mrs_one_signal(self) -> None:
        """여러 stale MR이 있어도 신호 1건 (첫 MR만)."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr1 = make_merge_request(
            iid=1,
            title="MR 1",
            state="open",
            updated_at=now - timedelta(days=5),
        )
        mr2 = make_merge_request(
            iid=2,
            title="MR 2",
            state="open",
            updated_at=now - timedelta(days=10),
        )
        group = make_feature_group_for_stagnation(merge_requests=(mr1, mr2))
        thresholds = StagnationThresholds(review_waiting_days=3)
        results = detect_stagnation_signals(group, now, thresholds)
        stale_mr_results = [r for r in results if r.kind == "stale_mr"]
        assert len(stale_mr_results) == 1

    def test_signal_deduplication_by_kind(self) -> None:
        """신호 종류별 최대 1개씩."""
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        mr = make_merge_request(
            state="open",
            updated_at=now - timedelta(days=5),
        )
        commits = (
            make_commit(message="revert: undo"),
            make_commit(message="hotfix: critical"),
        )
        group = make_feature_group_for_stagnation(
            merge_requests=(mr,),
            commits=commits,
        )
        thresholds = StagnationThresholds(review_waiting_days=3)
        results = detect_stagnation_signals(group, now, thresholds)
        # stale_mr 1개 + revert_commit 1개 + hotfix_commit 1개
        assert len(results) == 3
        kinds = [r.kind for r in results]
        assert kinds.count("stale_mr") == 1
        assert kinds.count("revert_commit") == 1
        assert kinds.count("hotfix_commit") == 1

    def test_stale_branch_without_pushed_at_days_none(self) -> None:
        """Arrange: branch.last_pushed_at=None.

        Act: detect_stale_branch 호출.

        Assert: result.days=None, result.kind="stale_branch".
        """
        # Arrange
        now = datetime(2026, 7, 16, 12, 0, tzinfo=KST)
        branch = make_branch(last_pushed_at=None)

        # Act
        result = detect_stale_branch(branch, now, threshold_days=7)

        # Assert
        assert result is not None
        assert result.kind == "stale_branch"
        assert result.days is None
