"""AI 강조 마커(**…**, ⚠ 접두) 변환 테스트 — textmark 단위 + 렌더러/스니펫 배선."""

from pulse.publish import build_share_snippet
from pulse.renderer.sections import (
    render_ai_summary,
    render_group_ai_title,
    render_group_analysis,
)
from pulse.renderer.textmark import apply_emphasis, is_attention_line, strip_emphasis

# ═══ textmark 단위


def test_apply_emphasis_single_pair() -> None:
    """짝 맞는 마커 쌍이 mark 태그로 변환된다."""
    result = apply_emphasis("배포 전 **회귀 테스트 필요** 확인")
    assert result == '배포 전 <mark class="ai-mark">회귀 테스트 필요</mark> 확인'


def test_apply_emphasis_multiple_pairs_non_greedy() -> None:
    """복수 쌍이 각각 변환된다 (non-greedy — 쌍끼리 합쳐지지 않음)."""
    result = apply_emphasis("**A** 그리고 **B**")
    assert result == '<mark class="ai-mark">A</mark> 그리고 <mark class="ai-mark">B</mark>'


def test_apply_emphasis_unpaired_left_as_is() -> None:
    """짝이 없는 마커는 문자 그대로 남는다 (안전한 저하)."""
    text = "짝 없는 ** 마커"
    assert apply_emphasis(text) == text


def test_apply_emphasis_empty_pair_left_as_is() -> None:
    """내용 없는 ****는 변환하지 않는다."""
    assert apply_emphasis("****") == "****"


def test_apply_emphasis_does_not_cross_lines() -> None:
    """마커 쌍은 같은 줄 안에서만 성립한다."""
    text = "**줄1\n줄2**"
    assert apply_emphasis(text) == text


def test_apply_emphasis_custom_tags() -> None:
    """태그를 바꿔 쓸 수 있다 (예: <strong>)."""
    result = apply_emphasis("**중요**", open_tag="<strong>", close_tag="</strong>")
    assert result == "<strong>중요</strong>"


def test_strip_emphasis_removes_markers_keeps_content() -> None:
    """strip은 마커만 제거하고 내용을 유지한다."""
    assert strip_emphasis("배포 전 **회귀 테스트** 확인") == "배포 전 회귀 테스트 확인"


def test_strip_emphasis_unpaired_left_as_is() -> None:
    """짝 없는 마커는 strip에서도 그대로 남는다."""
    assert strip_emphasis("짝 없는 ** 마커") == "짝 없는 ** 마커"


def test_is_attention_line() -> None:
    """⚠ 접두 줄만 주의 줄로 판별한다 (선행 공백 허용)."""
    assert is_attention_line("⚠ 릴리스 차단 이슈")
    assert is_attention_line("  ⚠ 들여쓴 줄")
    assert not is_attention_line("일반 진행 상황")
    assert not is_attention_line("중간에 ⚠ 있는 줄")


# ═══ 대시보드 렌더러 배선


def test_render_ai_summary_emphasis_marker() -> None:
    """레포 요약의 마커가 형광펜으로 변환되고 원문 마커는 사라진다."""
    result = render_ai_summary("진행 요약.\n**MR 재검토 필요** 상태입니다.")
    assert '<mark class="ai-mark">MR 재검토 필요</mark>' in result
    assert "**" not in result


def test_render_ai_summary_single_line_emphasis() -> None:
    """단일 문단 경로에서도 마커가 변환된다."""
    result = render_ai_summary("**긴급 확인** 필요")
    assert '<p class="ai-summary-content"><mark class="ai-mark">긴급 확인</mark> 필요</p>' in result


def test_render_ai_summary_attention_line_class() -> None:
    """⚠ 접두 불릿 줄에 attention 클래스가 붙고 다른 줄에는 안 붙는다."""
    result = render_ai_summary("일반 진행.\n⚠ 릴리스 차단 이슈 확인 필요")
    assert '<li class="attention">⚠ 릴리스 차단 이슈 확인 필요</li>' in result
    assert "<li>일반 진행.</li>" in result


def test_render_ai_summary_xss_inside_marker_stays_escaped() -> None:
    """마커 안의 마크업 원문은 escape된 채 강조된다 (주입 불가)."""
    result = render_ai_summary("**<script>alert(1)</script>**")
    assert "<script>" not in result
    assert '<mark class="ai-mark">&lt;script&gt;alert(1)&lt;/script&gt;</mark>' in result


def test_render_ai_summary_without_marker_unchanged() -> None:
    """마커 없는 기존 텍스트는 종전과 동일하게 렌더된다 (하위호환)."""
    result = render_ai_summary("Line 1\nLine 2")
    assert "<li>Line 1</li>" in result
    assert "<li>Line 2</li>" in result
    assert "ai-mark" not in result
    assert "attention" not in result


def test_render_group_analysis_emphasis_and_attention() -> None:
    """그룹 분석(기능/라인 행 펼침)에서 마커·⚠ 줄이 모두 변환된다."""
    result = render_group_analysis("작업 개요.\n⚠ **회귀 위험** 재검증.\n다음 단계.")
    expected = '<li class="attention">⚠ <mark class="ai-mark">회귀 위험</mark> 재검증.</li>'
    assert expected in result
    assert "**" not in result


def test_render_group_analysis_single_line_emphasis() -> None:
    """그룹 분석 단일 줄 경로에서도 마커가 변환된다."""
    result = render_group_analysis("**보안 검토 대기** 상태")
    assert '<mark class="ai-mark">보안 검토 대기</mark>' in result


def test_render_group_ai_title_strips_markers() -> None:
    """제목에 마커가 들어와도 제거된다 (제목 마커 금지 규약의 방어)."""
    result = render_group_ai_title("**OAuth** 통합")
    assert "OAuth 통합" in result
    assert "**" not in result
    assert "ai-mark" not in result


# ═══ 평문 소비처 (메신저 스니펫)


def test_share_snippet_strips_markers() -> None:
    """스니펫(평문)에서는 마커가 제거되고 내용·⚠은 유지된다."""
    snippet = build_share_snippet({"daily": {"org/repo": "진행 요약.\n⚠ **차단 이슈** 확인 필요"}})
    assert "**" not in snippet
    assert "⚠ 차단 이슈 확인 필요" in snippet
