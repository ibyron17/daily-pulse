"""레포 브리핑 두 문단(흐름 + 개선점) 규약 테스트.

- T2 골든: 문단 규약 도입 전 코드로 생성한 기대값 리터럴이다. 경계(내용 줄 사이 빈 줄)가 없는
  입력이 종전과 바이트 단위로 같은 결과를 내는지 고정한다 — 기대값을 새 코드로 다시 만들지 않는다.
  이 테스트가 깨졌다면 기대값이 아니라 하위호환이 깨진 것이다.
- T1: 문단 분리 규칙(PRP §3-A 표 #1~#13).
- T3~T7·T11·T12: 대시보드 개선점 블록. 소제목 기대값은 상수를 import하지 않고 리터럴
  「개선점」으로 쓴다 — 문구가 조용히 바뀌는 것을 잡기 위해서다.
"""

import re
from dataclasses import dataclass

import pytest

from pulse.publish import build_share_snippet
from pulse.renderer.html import ai_summary_slot, inject_ai_summary
from pulse.renderer.sections import render_ai_summary
from pulse.renderer.styles import CSS
from pulse.renderer.textmark import (
    IMPACT_PARAGRAPH_LABEL,
    BriefParagraphs,
    split_brief_paragraphs,
)

# ═══ T2 골든 — 변경 전 코드로 생성한 기대값 (경계 없는 입력의 바이트 동일)

GOLDEN_REPO_NAME = "org/repo"


@dataclass(frozen=True)
class GoldenCase:
    """한 입력 요약에 대한 변경 전 출력 (대시보드 일간·스니펫)."""

    case_id: str
    text: str
    daily_html: str
    snippet: str


# 첫 sample-* 6건은 실제 발행 요약의 줄 구성(줄 수·`**` 마커 위치)만 본뜬 가상 문장이다.
# 렌더러는 줄바꿈·마커·escape 대상 문자만 보므로 문장 내용을 바꿔도 검증 대상(바이트 동일)은 같다.
GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        case_id="sample-daily-multi",
        text=(
            "PROJ-145 대응으로 sample-calendar 4.2.0 및 sample-form 2.7.1 교체가 "
            "develop·test·devqa 라인에 반영됐습니다.\n"
            "대기자 알림 기능(WAIT-189) 실제 구현과 문자 발송 응답 연동이 "
            "완료됐습니다.\n"
            "예약 내역 조회 현황판 오류 표시와 페이지 번호 표시 개선도 진행됐습니다."
        ),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>PROJ-145 대응으로 sample-calendar 4.2.0 및 sample-form 2.7.1 "
            "교체가 develop·test·devqa 라인에 반영됐습니다.</li>\n"
            "      <li>대기자 알림 기능(WAIT-189) 실제 구현과 문자 발송 "
            "응답 연동이 완료됐습니다.</li>\n"
            "      <li>예약 내역 조회 현황판 오류 표시와 페이지 번호 표시 "
            "개선도 진행됐습니다.</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=(
            "## Daily Pulse 요약\n"
            "\n"
            "### org/repo\n"
            "PROJ-145 대응으로 sample-calendar 4.2.0 및 sample-form 2.7.1 교체가 "
            "develop·test·devqa 라인에 반영됐습니다.\n"
            "대기자 알림 기능(WAIT-189) 실제 구현과 문자 발송 응답 연동이 "
            "완료됐습니다.\n"
            "예약 내역 조회 현황판 오류 표시와 페이지 번호 표시 개선도 진행됐습니다.\n"
        ),
    ),
    GoldenCase(
        case_id="sample-daily-editor",
        text=(
            "sample-form을 2.7.1로 교체하고, TASK-540 보안 대응으로 예약 "
            "중복 판정 로직을 isSameBooking으로 단일화했습니다.\n"
            "테스트 환경 설정 수정도 포함됩니다."
        ),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>sample-form을 2.7.1로 교체하고, TASK-540 보안 대응으로 "
            "예약 중복 판정 로직을 isSameBooking으로 단일화했습니다.</li>\n"
            "      <li>테스트 환경 설정 수정도 포함됩니다.</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=(
            "## Daily Pulse 요약\n"
            "\n"
            "### org/repo\n"
            "sample-form을 2.7.1로 교체하고, TASK-540 보안 대응으로 예약 "
            "중복 판정 로직을 isSameBooking으로 단일화했습니다.\n"
            "테스트 환경 설정 수정도 포함됩니다.\n"
        ),
    ),
    GoldenCase(
        case_id="sample-daily-idle",
        text="조회 기간 내 특이 활동이 없습니다.",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">조회 기간 내 특이 활동이 '
            "없습니다.</p>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\n조회 기간 내 특이 활동이 없습니다.\n"),
    ),
    GoldenCase(
        case_id="sample-weekly-multi",
        text=(
            "이번 주 31건 커밋, MR 4건이 처리됐습니다.\n"
            "PROJ-145 sample-calendar 업그레이드와 대기자 알림 기능(WAIT-189) 구현이 "
            "주요 흐름입니다.\n"
            "**PROJ-412 예약자 입력 검증 보강 코드가 devqa에 임시 반영됐다가 원복됐으며, "
            "input_check 브랜치를 통한 정식 반영이 예정됩니다.**\n"
            "신규 작업 3건이 이번 주에 새로 관측됐습니다."
        ),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>이번 주 31건 커밋, MR 4건이 처리됐습니다.</li>\n"
            "      <li>PROJ-145 sample-calendar 업그레이드와 대기자 알림 기능(WAIT-189) "
            "구현이 주요 흐름입니다.</li>\n"
            '      <li><mark class="ai-mark">PROJ-412 예약자 입력 검증 보강 코드가 '
            "devqa에 임시 반영됐다가 원복됐으며, input_check 브랜치를 "
            "통한 정식 반영이 예정됩니다.</mark></li>\n"
            "      <li>신규 작업 3건이 이번 주에 새로 관측됐습니다.</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=(
            "## Daily Pulse 요약\n"
            "\n"
            "### org/repo\n"
            "이번 주 31건 커밋, MR 4건이 처리됐습니다.\n"
            "PROJ-145 sample-calendar 업그레이드와 대기자 알림 기능(WAIT-189) 구현이 "
            "주요 흐름입니다.\n"
            "PROJ-412 예약자 입력 검증 보강 코드가 devqa에 임시 반영됐다가 원복됐으며, "
            "input_check 브랜치를 통한 정식 반영이 예정됩니다.\n"
            "신규 작업 3건이 이번 주에 새로 관측됐습니다.\n"
        ),
    ),
    GoldenCase(
        case_id="sample-weekly-editor",
        text=(
            "이번 주 4건 커밋이 처리됐습니다.\n"
            "TASK-540 보안 대응으로 예약 병합 판정 최적화와 sample-form "
            "2.7.1 교체가 주요 내용입니다.\n"
            "테스트 환경 개선도 포함됩니다."
        ),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>이번 주 4건 커밋이 처리됐습니다.</li>\n"
            "      <li>TASK-540 보안 대응으로 예약 병합 판정 최적화와 "
            "sample-form 2.7.1 교체가 주요 내용입니다.</li>\n"
            "      <li>테스트 환경 개선도 포함됩니다.</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=(
            "## Daily Pulse 요약\n"
            "\n"
            "### org/repo\n"
            "이번 주 4건 커밋이 처리됐습니다.\n"
            "TASK-540 보안 대응으로 예약 병합 판정 최적화와 sample-form "
            "2.7.1 교체가 주요 내용입니다.\n"
            "테스트 환경 개선도 포함됩니다.\n"
        ),
    ),
    GoldenCase(
        case_id="sample-weekly-tooling",
        text=(
            "이번 주 2건 커밋이 처리됐습니다.\n"
            "예약 확인서 생성 도구를 일시·장소·인원 기준으로 개편하고 "
            "안내 문단 유무 판정 기준을 추가하는 작업이 이뤄졌습니다."
        ),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>이번 주 2건 커밋이 처리됐습니다.</li>\n"
            "      <li>예약 확인서 생성 도구를 일시·장소·인원 기준으로 "
            "개편하고 안내 문단 유무 판정 기준을 추가하는 작업이 이뤄졌습니다.</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=(
            "## Daily Pulse 요약\n"
            "\n"
            "### org/repo\n"
            "이번 주 2건 커밋이 처리됐습니다.\n"
            "예약 확인서 생성 도구를 일시·장소·인원 기준으로 개편하고 "
            "안내 문단 유무 판정 기준을 추가하는 작업이 이뤄졌습니다.\n"
        ),
    ),
    GoldenCase(
        case_id="single-line",
        text="요약",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">요약</p>\n'
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\n요약\n"),
    ),
    GoldenCase(
        case_id="two-lines",
        text=("A\nB"),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>A</li>\n"
            "      <li>B</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\nB\n"),
    ),
    GoldenCase(
        case_id="trailing-newline",
        text="A\n",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">A\n'
            "</p>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\n"),
    ),
    GoldenCase(
        case_id="padded-single",
        text="  A  ",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">  A  </p>\n'
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\n"),
    ),
    GoldenCase(
        case_id="emphasis-single",
        text="**X** 필요",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content"><mark class="ai-mark">X</mark> '
            "필요</p>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nX 필요\n"),
    ),
    GoldenCase(
        case_id="attention-line",
        text=("진행.\n⚠ 주의"),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>진행.</li>\n"
            '      <li class="attention">⚠ 주의</li>\n'
            "      </ul>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\n진행.\n⚠ 주의\n"),
    ),
    GoldenCase(
        case_id="script-tag",
        text="<script>x</script>",
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">&lt;script&gt;x&lt;/script&gt;</p>\n'
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\n<script>x</script>\n"),
    ),
    GoldenCase(
        case_id="trailing-blank-line",
        text=("A\n\n"),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">A\n'
            "\n"
            "</p>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\n"),
    ),
    GoldenCase(
        case_id="leading-blank-lines",
        text=("\n\nA"),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            '  <p class="ai-summary-content">\n'
            "\n"
            "A</p>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\n"),
    ),
    GoldenCase(
        case_id="outer-blank-lines",
        text=("\nA\nB\n\n"),
        daily_html=(
            '<section class="ai-summary">\n'
            "  <h2>일간 브리핑</h2>\n"
            "  <ul>\n"
            "      <li>A</li>\n"
            "      <li>B</li>\n"
            "      </ul>\n"
            "</section>"
        ),
        snippet=("## Daily Pulse 요약\n\n### org/repo\nA\nB\n"),
    ),
    GoldenCase(
        case_id="empty",
        text="",
        daily_html="",
        snippet=("## Daily Pulse 요약\n\n"),
    ),
    GoldenCase(
        case_id="whitespace-only",
        text=("   \n  "),
        daily_html="",
        snippet=("## Daily Pulse 요약\n\n"),
    ),
)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_golden_dashboard_daily_is_byte_identical(case: GoldenCase) -> None:
    """경계 없는 요약의 일간 대시보드 HTML이 종전과 바이트 단위로 같다."""
    assert render_ai_summary(case.text, period="daily") == case.daily_html


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_golden_dashboard_weekly_is_byte_identical(case: GoldenCase) -> None:
    """주간 대시보드 HTML도 제목만 다르고 종전과 바이트 단위로 같다."""
    expected = case.daily_html.replace("일간 브리핑", "주간 브리핑")
    assert render_ai_summary(case.text, period="weekly") == expected


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_golden_share_snippet_is_byte_identical(case: GoldenCase) -> None:
    """경계 없는 요약의 메신저 스니펫이 종전과 바이트 단위로 같다."""
    snippet = build_share_snippet({"daily": {GOLDEN_REPO_NAME: case.text}})
    assert snippet == case.snippet


# ═══ T1 문단 분리 — PRP §3-A 표 #1~#13 (입력, (흐름, 개선점))
# 경계 없음 → 흐름은 입력 원문 그대로(하위호환의 근거), 개선점은 "".

SPLIT_CASES: tuple[tuple[str, str, tuple[str, str]], ...] = (
    ("01-single-line", "A", ("A", "")),
    ("02-three-lines", "A\nB\nC", ("A\nB\nC", "")),
    ("03a-trailing-newline", "A\n", ("A\n", "")),
    ("03b-trailing-blank-line", "A\n\n", ("A\n\n", "")),
    ("03c-leading-blank-lines", "\n\nA", ("\n\nA", "")),
    ("03d-outer-blank-lines", "\nA\nB\n\n", ("\nA\nB\n\n", "")),
    ("04-boundary-multi-line", "A\nB\n\nX\nY", ("A\nB", "X\nY")),
    ("05-boundary-single-lines", "A\n\nX", ("A", "X")),
    ("06-consecutive-blank-lines", "A\n\n\n\nX", ("A", "X")),
    ("07a-whitespace-only-line", "A\n \t\nX", ("A", "X")),
    ("07b-crlf-blank-line", "A\r\n\r\nX", ("A", "X")),
    ("08-three-paragraphs", "A\n\nX\n\nY", ("A", "X\n\nY")),
    ("09-impact-only-leading-blank", "\n\nX", ("\n\nX", "")),
    ("10a-empty", "", ("", "")),
    ("10b-whitespace-only", "   \n  ", ("   \n  ", "")),
    ("11-stray-blank-line-in-flow", "A\n\nB", ("A", "B")),
    ("12-markers-in-impact", "A\n\n**중요** 효과", ("A", "**중요** 효과")),
    (
        "13-markup-in-impact",
        "A\n\n<script>alert(1)</script>",
        ("A", "<script>alert(1)</script>"),
    ),
    ("14-strips-outer-blank-lines", "\nA\n\nX\n", ("A", "X")),
    ("15-strips-outer-spaces", "  A\n\nX  ", ("A", "X")),
    ("16-ideographic-space-line", "A\n\u3000\nX", ("A", "X")),
    ("17-nbsp-line", "A\n\xa0\nX", ("A", "X")),
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [pytest.param(text, expected, id=case_id) for case_id, text, expected in SPLIT_CASES],
)
def test_split_brief_paragraphs_follows_boundary_table(
    text: str, expected: tuple[str, str]
) -> None:
    """내용 줄 사이의 첫 빈 줄만 경계이고, 경계가 없으면 원문이 그대로 흐름이 된다."""
    paragraphs = split_brief_paragraphs(text)
    assert (paragraphs.flow, paragraphs.impact) == expected


def test_split_brief_paragraphs_returns_frozen_dataclass() -> None:
    """분리 결과는 불변 데이터 모델이다."""
    paragraphs = split_brief_paragraphs("A\n\nX")
    assert paragraphs == BriefParagraphs(flow="A", impact="X")
    with pytest.raises(AttributeError):
        paragraphs.flow = "changed"  # type: ignore[misc]


# ═══ T3~T7·T11·T12 대시보드 개선점 블록
# 소제목 기대값은 일부러 리터럴이다 (상수와 비교만 하면 문구 변경을 못 잡는다).

IMPACT_LABEL_HTML = '<h3 class="ai-summary-impact-label">개선점</h3>'
FLOW_PARAGRAPH_OPEN = '<p class="ai-summary-content">'


def test_dashboard_impact_block_exact_html() -> None:
    """개선점이 있으면 점선 구분 div + h3 소제목 + 본문이 흐름 문단 뒤에 붙는다."""
    expected = (
        '<section class="ai-summary">\n'
        "  <h2>일간 브리핑</h2>\n"
        "  <ul>\n"
        "      <li>A</li>\n"
        "      <li>B</li>\n"
        "      </ul>\n"
        '  <div class="ai-summary-impact">\n'
        f"    {IMPACT_LABEL_HTML}\n"
        "    <ul>\n"
        "      <li>X</li>\n"
        "      <li>Y</li>\n"
        "      </ul>\n"
        "  </div>\n"
        "</section>"
    )
    assert render_ai_summary("A\nB\n\nX\nY") == expected


def test_dashboard_impact_block_placed_after_flow_with_single_label() -> None:
    """흐름 li는 소제목 앞, 개선점 li는 소제목 뒤이고 소제목·블록은 정확히 1개다."""
    html = render_ai_summary("A\nB\n\nX\nY")
    label_position = html.index(IMPACT_LABEL_HTML)
    assert html.count('class="ai-summary-impact"') == 1
    assert html.count("<h3") == 1
    assert html.index("<li>A</li>") < html.index("<li>B</li>") < label_position
    assert label_position < html.index("<li>X</li>") < html.index("<li>Y</li>")


def test_dashboard_single_line_paragraphs_render_as_two_paragraphs() -> None:
    """흐름·개선점이 각각 한 줄이면 둘 다 p.ai-summary-content 로 렌더된다."""
    html = render_ai_summary("A\n\nX")
    assert html.count(FLOW_PARAGRAPH_OPEN) == 2
    assert html.index(f"{FLOW_PARAGRAPH_OPEN}A</p>") < html.index(IMPACT_LABEL_HTML)
    assert html.index(IMPACT_LABEL_HTML) < html.index(f"{FLOW_PARAGRAPH_OPEN}X</p>")


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
@pytest.mark.parametrize("period", ["daily", "weekly"])
def test_dashboard_without_boundary_has_no_impact_block(case: GoldenCase, period: str) -> None:
    """경계 없는 요약(T2 말뭉치 전부)에는 개선점 블록도 소제목도 나오지 않는다."""
    html = render_ai_summary(case.text, period=period)
    assert "ai-summary-impact" not in html
    assert "개선점" not in html


def test_dashboard_three_paragraphs_split_only_at_first_boundary() -> None:
    """3문단이면 소제목은 1개이고 둘째·셋째 문단이 모두 개선점 목록 안에 들어간다."""
    html = render_ai_summary("A\n\nX\n\nY")
    flow_html, impact_html = html.split(IMPACT_LABEL_HTML)
    assert html.count("<h3") == 1
    assert f"{FLOW_PARAGRAPH_OPEN}A</p>" in flow_html
    assert "<ul>" in impact_html
    assert "<li>X</li>" in impact_html
    assert "<li>Y</li>" in impact_html


def test_dashboard_impact_script_tag_is_escaped() -> None:
    """개선점 문단의 스크립트 태그는 escape 되어 실행 가능한 태그로 남지 않는다."""
    html = render_ai_summary("A\n\n<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_dashboard_impact_marker_content_stays_escaped() -> None:
    """개선점 문단의 마커 안 마크업 원문도 escape 된 채 강조된다."""
    html = render_ai_summary("A\n\n**<b>x</b>**")
    assert "<b>" not in html
    assert '<mark class="ai-mark">&lt;b&gt;x&lt;/b&gt;</mark>' in html


def test_dashboard_flow_markers_survive_with_impact_block() -> None:
    """흐름 문단의 ⚠ 줄·강조 마커는 유지되고 소제목 텍스트에는 마커가 없다."""
    html = render_ai_summary("**긴급** 확인\n⚠ 주의 줄\n\n효과 줄")
    flow_html, impact_html = html.split(IMPACT_LABEL_HTML)
    assert '<mark class="ai-mark">긴급</mark>' in flow_html
    assert '<li class="attention">⚠ 주의 줄</li>' in flow_html
    assert "ai-mark" not in impact_html
    assert "attention" not in impact_html
    assert "**" not in html


def test_dashboard_impact_paragraph_converts_markers_like_flow() -> None:
    """개선점 문단에 마커가 섞여 들어와도 흐름과 같게 변환된다 (안전한 저하, PRP §3-A #12)."""
    html = render_ai_summary("A\nB\n\nX\n⚠ **Y** 확인")
    _, impact_html = html.split(IMPACT_LABEL_HTML)
    assert '<li class="attention">⚠ <mark class="ai-mark">Y</mark> 확인</li>' in impact_html
    assert "<li>X</li>" in impact_html
    assert "**" not in html


def test_dashboard_impact_block_in_weekly_view() -> None:
    """주간 뷰에서도 제목만 주간 브리핑으로 바뀌고 개선점 블록이 붙는다."""
    html = render_ai_summary("A\n\nX", period="weekly")
    assert "<h2>주간 브리핑</h2>" in html
    assert IMPACT_LABEL_HTML in html


def test_inject_ai_summary_puts_impact_block_into_slot() -> None:
    """슬롯 주입 경로에서도 개선점 블록이 그려지고 슬롯 주석은 사라진다."""
    slot = ai_summary_slot("org/repo")
    injected = inject_ai_summary(f"<main>{slot}</main>", "org/repo", "A\n\nX")
    assert slot not in injected
    assert IMPACT_LABEL_HTML in injected


def _css_rule_body(selector: str) -> str:
    """CSS 에서 정확히 이 셀렉터의 규칙 본문(중괄호 안)을 꺼낸다."""
    match = re.search(rf"(?<![\w-]){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS)
    assert match is not None, f"{selector} 규칙이 CSS 에 없다"
    return match.group(1)


def test_css_impact_block_rule_has_dashed_top_border() -> None:
    """개선점 블록 규칙 본문에 점선 상단 구분선이 있다 (다른 규칙의 dashed 와 구별)."""
    assert re.search(r"border-top:\s*1px dashed", _css_rule_body(".ai-summary-impact"))


def test_css_impact_label_rule_uses_accent_color() -> None:
    """개선점 소제목 규칙 본문이 강조색(accent)과 굵기를 지정한다."""
    label_rule = _css_rule_body(".ai-summary-impact-label")
    assert "color: var(--accent)" in label_rule
    assert "font-weight: 700" in label_rule


# ═══ 소제목 문구 고정


def test_impact_label_is_approved_literal() -> None:
    """개선점 소제목 상수가 승인된 문구(리터럴)다."""
    assert IMPACT_PARAGRAPH_LABEL == "개선점"


# ═══ T10 메신저 스니펫 — 평문이라 소제목은 [대괄호] 한 줄, 마커는 제거


def test_share_snippet_puts_label_line_before_impact_paragraph() -> None:
    """개선점이 있으면 흐름 뒤에 빈 줄 + [개선점] 줄 + 개선점 문단이 붙고 마커는 사라진다."""
    snippet = build_share_snippet({"daily": {GOLDEN_REPO_NAME: "흐름\n\n⚠ **X** 효과"}})
    assert snippet == "## Daily Pulse 요약\n\n### org/repo\n흐름\n\n[개선점]\n⚠ X 효과\n"
    assert "**" not in snippet


def test_share_snippet_keeps_later_blank_lines_of_impact_paragraph() -> None:
    """3문단이면 첫 경계에서만 나누고 개선점 문단 안의 빈 줄은 원문 그대로 둔다."""
    snippet = build_share_snippet({"daily": {GOLDEN_REPO_NAME: "A\n\nX\n\nY"}})
    assert snippet == "## Daily Pulse 요약\n\n### org/repo\nA\n\n[개선점]\nX\n\nY\n"


def test_share_snippet_without_boundary_has_no_label() -> None:
    """경계 없는 요약에는 소제목 줄이 붙지 않는다."""
    snippet = build_share_snippet({"daily": {GOLDEN_REPO_NAME: "A\nB"}})
    assert "[개선점]" not in snippet
