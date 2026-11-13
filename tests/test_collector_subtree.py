"""서브트리 경로 포함 판정 순수 로직 테스트."""

import pytest

from pulse.collector.subtree import is_path_in_subtree, touches_subtree


class TestIsPathInSubtree:
    """is_path_in_subtree 테이블 테스트 — 세그먼트 경계, 대소문자 구분."""

    @pytest.mark.parametrize(
        ("file_path", "subtree_path", "expected"),
        [
            ("sample-model/src/a.ts", "sample-model", True),
            ("sample-model", "sample-model", True),
            ("sample-model2/src/a.ts", "sample-model", False),
            ("sample-modelx", "sample-model", False),
            ("other/src/a.ts", "sample-model", False),
            ("Sample-Model/a.ts", "sample-model", False),
        ],
    )
    def test_is_path_in_subtree(self, file_path: str, subtree_path: str, expected: bool) -> None:
        assert is_path_in_subtree(file_path, subtree_path) is expected


class TestTouchesSubtree:
    """touches_subtree 테이블 테스트."""

    def test_no_changed_files_returns_false(self) -> None:
        """변경 파일이 없으면 False."""
        assert touches_subtree((), "sample-model") is False

    def test_mixed_commit_returns_true(self) -> None:
        """서브트리 파일과 밖 파일이 섞인 커밋은 True (포함 판정)."""
        assert touches_subtree(("a.md", "sample-model/b.ts"), "sample-model") is True
