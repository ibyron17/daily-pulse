"""커스텀 툴팁 배치 계약 테스트 (문자열 단언 — 렌더러 테스트 관례).

말풍선은 트리거 기준 가운데 정렬이라 페이지 가장자리의 트리거에서는 화면 밖으로
잘린다. 어느 요소가 가장자리에 놓일지는 화면 폭에 따라 달라져 CSS만으로 정할 수
없으므로 열리는 순간 실측해 보정한다 — 그 계약(CSS 변수 이름·적용 지점)을 고정한다.
"""

from pulse.renderer.html import _render_tooltip_edge_script
from pulse.renderer.styles import CSS


class TestEdgeClampContract:
    def test_bubble_offset_is_driven_by_tip_shift(self) -> None:
        """스크립트가 쓰는 --tip-shift를 말풍선이 실제로 반영한다."""
        assert "margin-left: var(--tip-shift, 0px);" in CSS

    def test_arrow_compensates_for_the_shift(self) -> None:
        """말풍선이 밀려도 화살표는 트리거를 계속 가리켜야 한다."""
        assert "var(--tip-arrow-base, 50%) - var(--tip-shift, 0px)" in CSS

    def test_arrow_stays_inside_the_bubble(self) -> None:
        """보정량이 크면 화살표가 말풍선 밖으로 튀어나가므로 clamp로 가둔다."""
        assert "clamp(12px, calc(var(--tip-arrow-base, 50%)" in CSS

    def test_align_start_variant_moves_the_arrow_base(self) -> None:
        """왼쪽 정렬 변형은 화살표 기준점이 가운데가 아니다."""
        assert "--tip-arrow-base: 14px;" in CSS

    def test_bubble_never_exceeds_viewport_width(self) -> None:
        """좁은 화면에서는 보정만으로 담을 수 없어 폭 자체를 제한한다."""
        assert "max-width: min(280px, calc(100vw - 2rem));" in CSS


class TestEdgeScript:
    def test_script_targets_every_tooltip_host(self) -> None:
        """개별 컴포넌트가 아니라 툴팁 전체에 한 번에 적용된다."""
        script = _render_tooltip_edge_script()
        assert '.closest(".tooltip-host")' in script
        assert '.querySelector(".tooltip-bubble")' in script

    def test_script_resets_before_measuring(self) -> None:
        """이전 보정을 지우지 않으면 창 크기 변화에 따라 값이 누적된다."""
        script = _render_tooltip_edge_script()
        assert 'setProperty("--tip-shift", "0px")' in script

    def test_script_handles_both_edges(self) -> None:
        script = _render_tooltip_edge_script()
        assert "rect.left < EDGE_MARGIN" in script
        assert "rect.right > window.innerWidth - EDGE_MARGIN" in script

    def test_script_reacts_to_keyboard_focus_too(self) -> None:
        """호버 전용이면 키보드 사용자에게는 여전히 잘린 채로 열린다."""
        script = _render_tooltip_edge_script()
        assert '"focusin"' in script
        assert '"mouseover"' in script


class TestSummaryRowAlignment:
    def test_group_name_has_no_leftover_bottom_margin(self) -> None:
        """요약 행은 세로 가운데 정렬 — 아래 여백이 남으면 글자가 위로 밀린다."""
        assert ".feature-summary .group-name," in CSS
        assert ".feature-summary .group-ai-title {" in CSS


class TestWeekBarSize:
    def test_bar_slot_is_wide_enough_to_point_at(self) -> None:
        """막대가 너무 좁으면 주별 차이도, 툴팁 트리거 영역도 확보되지 않는다."""
        assert "flex: 0 0 22px;" in CSS
