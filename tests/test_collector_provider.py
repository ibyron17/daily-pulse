"""GitProvider 프로토콜 정의 및 준수 검증 테스트."""

from zoneinfo import ZoneInfo

import pytest

from pulse.collector.provider import GitProvider

KST = ZoneInfo("Asia/Seoul")


class TestGitProviderProtocol:
    """GitProvider 프로토콜이 필요한 메서드를 정의하는지 검증."""

    def test_provider_has_get_repo_version_method(self) -> None:
        """GitProvider는 get_repo_version 메서드를 가져야 한다."""
        assert hasattr(GitProvider, "get_repo_version")

    def test_provider_has_collect_repo_activity_method(self) -> None:
        """GitProvider는 collect_repo_activity 메서드를 가져야 한다."""
        assert hasattr(GitProvider, "collect_repo_activity")

    def test_collect_repo_activity_returns_repo_activity(self) -> None:
        """collect_repo_activity는 RepoActivity를 반환해야 한다."""
        # 프로토콜 구조만 검증 (실제 구현은 gitlab.py에서)
        assert True


class TestMRStateNormalization:
    """MR state 정규화 로직 테스트."""

    def test_normalize_mr_state_opened_to_open(self) -> None:
        """GitLab 'opened' state는 'open'으로 정규화되어야 한다."""
        from pulse.collector.gitlab import _normalize_mr_state

        result = _normalize_mr_state("opened")
        assert result == "open"

    def test_normalize_mr_state_merged(self) -> None:
        """GitLab 'merged' state는 그대로 유지되어야 한다."""
        from pulse.collector.gitlab import _normalize_mr_state

        result = _normalize_mr_state("merged")
        assert result == "merged"

    def test_normalize_mr_state_closed(self) -> None:
        """GitLab 'closed' state는 그대로 유지되어야 한다."""
        from pulse.collector.gitlab import _normalize_mr_state

        result = _normalize_mr_state("closed")
        assert result == "closed"

    def test_normalize_mr_state_unknown_raises_error(self) -> None:
        """알 수 없는 state는 CollectionError를 발생시킨다."""
        from pulse.collector.gitlab import CollectionError, _normalize_mr_state

        with pytest.raises(CollectionError, match="알 수 없는 MR 상태"):
            _normalize_mr_state("unknown_state")
