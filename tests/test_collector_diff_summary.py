"""diff 발췌 모듈 테스트."""

from pulse.collector.diff_summary import DiffFileStat, summarize_diff


class TestSummarizeDiff:
    """summarize_diff 함수 테스트."""

    def test_empty_files(self) -> None:
        """파일 없음 → 빈 문자열."""
        result = summarize_diff(())
        assert result == ""

    def test_single_file(self) -> None:
        """파일 1개 → 경로 + 통계."""
        files = (
            DiffFileStat(
                path="auth/handlers.py",
                added_lines=34,
                deleted_lines=6,
                hunk_headers=("def token_exchange",),
            ),
        )
        result = summarize_diff(files)
        assert "auth/handlers.py (+34/-6)" in result
        assert "def token_exchange" in result

    def test_multiple_files(self) -> None:
        """파일 3개 → 모두 포함."""
        files = (
            DiffFileStat("auth/handlers.py", 34, 6, ("def token_exchange",)),
            DiffFileStat("auth/tokens.py", 12, 2, ("def validate_redirect",)),
            DiffFileStat("auth/config.py", 3, 1, ()),
        )
        result = summarize_diff(files)
        assert "auth/handlers.py" in result
        assert "auth/tokens.py" in result
        assert "auth/config.py" in result

    def test_max_chars_truncation(self) -> None:
        """1500자 상한 검증."""
        files = tuple(DiffFileStat(f"file_{i}.py", 100, 50, (f"func_{i}",)) for i in range(100))
        result = summarize_diff(files, max_chars=500)
        assert len(result) <= 500

    def test_no_hunk_headers(self) -> None:
        """hunk 헤더 없는 파일."""
        files = (DiffFileStat("test.py", 10, 5, ()),)
        result = summarize_diff(files)
        assert "test.py (+10/-5)" in result
        # hunk 헤더가 없어도 라인이 나타남
        assert "@@" not in result

    def test_format_structure(self) -> None:
        """출력 형식: 줄바꿈으로 파일 구분."""
        files = (
            DiffFileStat("a.py", 1, 1, ("func_a",)),
            DiffFileStat("b.py", 2, 2, ("func_b",)),
        )
        result = summarize_diff(files)
        lines = result.split("\n")
        assert len(lines) >= 2  # 최소 2개 라인
