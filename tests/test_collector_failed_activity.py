"""수집 실패 활동(failed activity) 테스트."""

from datetime import datetime, timezone

from pulse.collector import _build_failed_activity
from pulse.models import RepoRef

KST_NOW = datetime(2026, 7, 23, 10, 30, 45, tzinfo=timezone.utc)


class TestBuildFailedActivity:
    """_build_failed_activity 함수 테스트."""

    def test_failed_activity_collected_at_matches_injected_now(self) -> None:
        """실패 활동의 collected_at이 주입한 now와 정확히 같아야 한다."""
        repo = RepoRef(
            provider="gitlab",
            base_url="http://example.com",
            namespace="example",
            name="test",
            web_url="http://example.com/example/test",
        )
        error = ValueError("Test error")

        # 특정 시점의 now 주입 (벽시계와 다른 과거 시각)
        specific_now = datetime(2026, 7, 22, 15, 0, 0, tzinfo=timezone.utc)

        activity = _build_failed_activity(repo, error, specific_now)

        assert activity.collected_at == specific_now
        assert activity.status == "failed"
        assert activity.failure_reason == "Test error"

    def test_failed_activity_status_is_failed(self) -> None:
        """실패 활동의 status는 'failed'여야 한다."""
        repo = RepoRef(
            provider="gitlab",
            base_url="http://example.com",
            namespace="example",
            name="test",
            web_url="http://example.com/example/test",
        )
        error = RuntimeError("Connection failed")

        activity = _build_failed_activity(repo, error, KST_NOW)

        assert activity.status == "failed"

    def test_failed_activity_empty_collections(self) -> None:
        """실패 활동의 활동 컬렉션(commits, MR 등)은 모두 비어있어야 한다."""
        repo = RepoRef(
            provider="github",
            base_url="https://github.com",
            namespace="example",
            name="test",
            web_url="https://github.com/example/test",
        )
        error = Exception("Generic error")

        activity = _build_failed_activity(repo, error, KST_NOW)

        assert activity.commits == ()
        assert activity.active_branches == ()
        assert activity.created_branches == ()
        assert activity.deleted_branches == ()
        assert activity.merge_requests == ()

    def test_failed_activity_preserves_repo_ref(self) -> None:
        """실패 활동은 원본 RepoRef를 보존해야 한다."""
        repo = RepoRef(
            provider="gitlab",
            base_url="http://internal.gitlab",
            namespace="org",
            name="my-repo",
            web_url="http://internal.gitlab/org/my-repo",
        )
        error = Exception("API error")

        activity = _build_failed_activity(repo, error, KST_NOW)

        assert activity.repo == repo
        assert activity.repo.full_path == "org/my-repo"
        assert activity.repo.slug == "org__my-repo"
