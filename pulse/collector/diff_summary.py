"""diff 발췌 모듈 — provider 비종속 순수 로직."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DiffFileStat:
    """provider 정규화된 파일별 diff 통계."""

    path: str
    added_lines: int
    deleted_lines: int
    hunk_headers: tuple[str, ...]  # "@@ ... @@ def foo(...)" 컨텍스트 부분


def _extract_hunk_headers(diff_text: str) -> tuple[str, ...]:
    """diff 텍스트에서 hunk 헤더(@@ ... @@) 추출.

    Format: @@ -10,3 +10,5 @@ def function_name
    Returns: tuple of context strings (함수명 등)
    """
    # @@ ... @@ 패턴으로 hunk 헤더 찾기
    # 패턴: @@ -L,C +L,C @@ optional_context
    pattern = r"^@@\s+-[\d,]+\s+\+[\d,]+\s+@@\s*(.*?)$"
    headers = []
    for line in diff_text.split("\n"):
        match = re.match(pattern, line)
        if match:
            context = match.group(1).strip()
            if context:
                headers.append(context)
    return tuple(headers)


def _count_added_deleted_lines(diff_text: str) -> tuple[int, int]:
    """diff 텍스트에서 +/- 라인 수 계산."""
    added = 0
    deleted = 0
    for line in diff_text.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1
    return added, deleted


def summarize_diff(
    files: tuple[DiffFileStat, ...],
    max_chars: int = 1500,
) -> str:
    """파일별 diff 통계를 기계적으로 발췌.

    Format:
      path (+N/-M) @@ context
      path (+N/-M) @@ context2
      ...

    max_chars에서 절단. 빈 상태(files 없음)는 빈 문자열 반환.
    """
    if not files:
        return ""

    lines = []
    char_count = 0

    for file_stat in files:
        # 파일 라인 구성: path (+N/-M)
        file_line = f"{file_stat.path} (+{file_stat.added_lines}/-{file_stat.deleted_lines})"

        # hunk 헤더가 있으면 추가
        if file_stat.hunk_headers:
            # 첫 헤더만 (또는 필요하면 모두)
            for header in file_stat.hunk_headers[:1]:
                file_line += f" @@ {header}"

        # max_chars 체크
        if char_count + len(file_line) + 1 > max_chars:  # +1은 newline
            break

        lines.append(file_line)
        char_count += len(file_line) + 1

    return "\n".join(lines)
