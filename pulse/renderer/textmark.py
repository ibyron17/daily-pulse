"""AI 요약 텍스트 규약(강조 마커·문단 경계)의 단일 진실원.

AI가 평문 요약에 넣는 경량 마커를 escape 이후 안전한 태그로 변환한다:
- 인라인 강조 `**구절**` → 대시보드 <mark class="ai-mark"> (태그는 인자로 바꿀 수 있다)
- 줄 단위 주의 접두 `⚠` → 태그 변환 없이 렌더러가 li 클래스로 처리

변환 함수는 반드시 escape된 텍스트에 적용한다 — 마커 내부 원문이 이미
escape돼 있어 마커를 통한 마크업 주입이 불가능하다.

레포 요약 문자열은 내용 줄 사이의 첫 빈 줄을 경계로 흐름 문단과 개선점 문단으로
나뉜다 (split_brief_paragraphs). 소제목은 AI가 쓰지 않고 렌더러가 붙인다.
"""

import re
from dataclasses import dataclass
from itertools import pairwise

# non-greedy + '.'은 줄바꿈 불일치 — 짝은 같은 줄 안에서만 성립한다
_EMPHASIS_PATTERN = re.compile(r"\*\*(.+?)\*\*")

ATTENTION_PREFIX = "⚠"

# 둘째 문단(쓰는 사람 관점에서 좋아진 점 = 개선 효과)의 소제목. 대시보드·스니펫이 공유한다.
IMPACT_PARAGRAPH_LABEL = "개선점"

DEFAULT_OPEN_TAG = '<mark class="ai-mark">'
DEFAULT_CLOSE_TAG = "</mark>"


def apply_emphasis(
    escaped_text: str,
    *,
    open_tag: str = DEFAULT_OPEN_TAG,
    close_tag: str = DEFAULT_CLOSE_TAG,
) -> str:
    """escape된 텍스트의 짝 맞는 `**…**` 쌍을 강조 태그로 변환한다.

    짝이 맞지 않는 마커는 문자 그대로 남긴다 (안전한 저하).

    Args:
        escaped_text: escape_html/xml_escape를 이미 거친 텍스트
        open_tag: 여는 태그 (기본: 대시보드 형광펜)
        close_tag: 닫는 태그

    Returns:
        강조 태그가 적용된 텍스트
    """
    # 치환 템플릿이 아니라 람다를 쓴다 — 태그 문자열이 \g 등으로 해석되는 것을 차단
    return _EMPHASIS_PATTERN.sub(lambda m: f"{open_tag}{m.group(1)}{close_tag}", escaped_text)


def strip_emphasis(text: str) -> str:
    """평문 소비처(메신저 스니펫·제목)용으로 `**…**` 마커만 제거한다.

    Args:
        text: 마커를 포함할 수 있는 텍스트

    Returns:
        마커가 제거되고 내용은 유지된 텍스트
    """
    return _EMPHASIS_PATTERN.sub(r"\g<1>", text)


def is_attention_line(line: str) -> bool:
    """줄이 주의 접두(⚠)로 시작하는지 판별한다.

    Args:
        line: 검사할 한 줄 텍스트

    Returns:
        주의 줄 여부
    """
    return line.lstrip().startswith(ATTENTION_PREFIX)


@dataclass(frozen=True)
class BriefParagraphs:
    """레포 요약 문자열을 흐름 문단과 개선점 문단으로 나눈 결과."""

    flow: str  # 경계가 없으면 입력 원문 그대로(하위호환의 근거), 있으면 경계 앞(strip)
    impact: str  # 경계 뒤 전부(strip). 경계가 없으면 ""


def split_brief_paragraphs(text: str) -> BriefParagraphs:
    """두 내용 줄 사이의 첫 빈 줄에서 흐름/개선점 문단을 나눈다 (앞뒤 빈 줄은 경계가 아니다).

    빈 줄 판정은 렌더러와 같은 `line.strip() == ""` (공백·탭·`\\r`만 있는 줄 포함)이다.
    첫 경계에서만 나누므로 3문단 이상이면 뒤쪽 전부가 개선점 문단이 된다.

    Args:
        text: 레포 요약 원문 (escape 전)

    Returns:
        경계가 있으면 (경계 앞, 경계 뒤) strip 결과, 없으면 (원문 그대로, "")
    """
    lines = text.split("\n")
    content_indexes = [index for index, line in enumerate(lines) if line.strip()]
    for previous_index, next_index in pairwise(content_indexes):
        if next_index - previous_index > 1:
            return BriefParagraphs(
                flow="\n".join(lines[: previous_index + 1]).strip(),
                impact="\n".join(lines[next_index:]).strip(),
            )
    return BriefParagraphs(flow=text, impact="")
