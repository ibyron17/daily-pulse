"""R1: 탭 순서 버그 수정 테스트."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pulse.models import RepoActivity, RepoRef
from pulse.renderer.assemble import _extract_repo_tabs

KST = ZoneInfo("Asia/Seoul")


@pytest.fixture
def config_repos() -> tuple[RepoRef, ...]:
    """설정의 repos 순서를 정의하는 fixture."""
    return (
        RepoRef(
            provider="gitlab",
            base_url="http://example.com",
            namespace="org",
            name="first",
            web_url="http://example.com/org/first",
        ),
        RepoRef(
            provider="gitlab",
            base_url="http://example.com",
            namespace="org",
            name="second",
            web_url="http://example.com/org/second",
        ),
    )


def test_extract_repo_tabs_respects_config_order(config_repos: tuple[RepoRef, ...]) -> None:
    """탭 순서는 config.repos 기준이어야 한다."""
    activities = (
        RepoActivity(
            repo=config_repos[1],  # second
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
        ),
        RepoActivity(
            repo=config_repos[0],  # first
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
        ),
    )

    tabs = _extract_repo_tabs(activities, config_repos)

    # config 순서: first, second
    assert tabs == ("org/first", "org/second")


def test_extract_repo_tabs_fallback_alphabetical(config_repos: tuple[RepoRef, ...]) -> None:
    """config에 없는 레포는 알파벳순 폴백."""
    from pulse.models import RepoActivity

    new_repo = RepoRef(
        provider="gitlab",
        base_url="http://example.com",
        namespace="org",
        name="zebra",
        web_url="http://example.com/org/zebra",
    )

    activities = (
        RepoActivity(
            repo=config_repos[0],
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
        ),
        RepoActivity(
            repo=new_repo,
            status="ok",
            failure_reason=None,
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=datetime.now(tz=KST),
        ),
    )

    tabs = _extract_repo_tabs(activities, config_repos)

    # first는 config 순서, zebra는 없으므로 알파벳 뒤에 추가
    assert tabs == ("org/first", "org/zebra")
