"""페이지네이션 테스트 — 순회·상한·절단 보고.

7차 이전에는 단일 페이지(100건)만 받고 초과분을 버렸다. 브랜치 전체 히스토리는
100건을 쉽게 넘기므로(실측 211건) 실제 순회가 필요하다.
"""

import logging
from typing import Any

from pulse.collector.http_client import _MAX_PAGES, _PAGE_SIZE, GitLabClient


def make_client(pages: list[list[dict[str, Any]]]) -> tuple[GitLabClient, list[dict[str, Any]]]:
    """페이지별 응답을 미리 정해둔 클라이언트와 요청 기록을 만든다."""
    client = GitLabClient(base_url="http://example.test", token="t")
    calls: list[dict[str, Any]] = []

    def fake_request_list(
        method: str, endpoint: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        calls.append(dict(params or {}))
        page_index = int((params or {}).get("page", 1)) - 1
        return pages[page_index] if page_index < len(pages) else []

    client._request_list = fake_request_list  # type: ignore[method-assign]
    return client, calls


def items(count: int, offset: int = 0) -> list[dict[str, Any]]:
    """식별 가능한 더미 항목 목록."""
    return [{"id": offset + index} for index in range(count)]


class TestPaginate:
    def test_collects_across_pages(self) -> None:
        client, calls = make_client([items(100), items(100, 100), items(50, 200)])
        collected, truncated = client._paginate("endpoint", {})
        assert len(collected) == 250
        assert truncated is False
        assert len(calls) == 3
        assert [call["page"] for call in calls] == [1, 2, 3]

    def test_per_page_is_set_on_every_request(self) -> None:
        client, calls = make_client([items(100), items(10, 100)])
        client._paginate("endpoint", {"ref_name": "x"})
        assert all(call["per_page"] == _PAGE_SIZE for call in calls)
        # 호출자가 넘긴 파라미터는 유지된다
        assert all(call["ref_name"] == "x" for call in calls)

    def test_single_short_page_stops_immediately(self) -> None:
        client, calls = make_client([items(7)])
        collected, truncated = client._paginate("endpoint", {})
        assert len(collected) == 7
        assert truncated is False
        assert len(calls) == 1

    def test_exact_page_boundary_needs_one_more_request(self) -> None:
        """정확히 100건이면 다음 페이지가 빈 배열임을 확인해야 끝을 알 수 있다."""
        client, calls = make_client([items(100), []])
        collected, truncated = client._paginate("endpoint", {})
        assert len(collected) == 100
        assert truncated is False
        assert len(calls) == 2

    def test_max_items_truncates_and_reports(self, caplog: Any) -> None:
        client, calls = make_client([items(100), items(100, 100), items(100, 200)])
        with caplog.at_level(logging.WARNING):
            collected, truncated = client._paginate("endpoint", {}, max_items=150)
        assert len(collected) == 150
        assert truncated is True
        # 상한을 넘긴 시점에 멈춘다 (3페이지까지 가지 않는다)
        assert len(calls) == 2
        assert "상한" in caplog.text

    def test_max_items_exactly_met_is_truncated(self) -> None:
        client, _ = make_client([items(100), items(100, 100)])
        collected, truncated = client._paginate("endpoint", {}, max_items=200)
        assert len(collected) == 200
        # 상한에 정확히 닿았을 때 더 있는지 알 수 없으므로 절단으로 보고한다
        assert truncated is True

    def test_page_ceiling_reports_truncation(self, caplog: Any) -> None:
        client, calls = make_client([items(100) for _ in range(_MAX_PAGES + 5)])
        with caplog.at_level(logging.WARNING):
            collected, truncated = client._paginate("endpoint", {})
        assert truncated is True
        assert len(calls) == _MAX_PAGES
        assert len(collected) == _MAX_PAGES * _PAGE_SIZE
        assert "페이지 상한" in caplog.text

    def test_empty_first_page(self) -> None:
        client, _ = make_client([[]])
        collected, truncated = client._paginate("endpoint", {})
        assert collected == []
        assert truncated is False


class TestPaginateItems:
    def test_returns_items_only(self) -> None:
        client, _ = make_client([items(100), items(20, 100)])
        assert len(client._paginate_items("endpoint", {})) == 120
