"""확장 영역 접기/펼치기 애니메이션 계약 테스트 (문자열 단언 — 렌더러 테스트 관례).

<details>는 open이 바뀌는 순간 내용이 붙거나 떨어져 CSS만으로는 접기 쪽을
애니메이션할 수 없다. 그래서 기본 토글을 막고 직접 높이를 재서 애니메이션한다 —
그 계약(대상 선택자·같이 움직이는 속성·되돌리기·저하 경로)을 고정한다.
"""

from datetime import date

from pulse.models import DashboardModel
from pulse.renderer.html import _render_expand_animation_script, render_html
from pulse.renderer.styles import CSS
from tests.conftest import make_feature_group


class TestExpandAnimationScript:
    def test_targets_expand_areas_of_both_row_kinds(self) -> None:
        """기능 행과 라인 행이 같은 .feature-expand를 쓰므로 한 선택자로 함께 잡는다."""
        assert "details > .feature-expand" in _render_expand_animation_script()

    def test_height_and_vertical_padding_move_together(self) -> None:
        """높이만 줄이면 세로 패딩(위아래 14px)이 남아 0이 아니라 28px에서 끊긴다."""
        script = _render_expand_animation_script()
        assert "height: '0px', paddingTop: '0px', paddingBottom: '0px'" in script
        assert "paddingTop: style.paddingTop" in script

    def test_close_animates_before_the_open_attribute_drops(self) -> None:
        """open을 먼저 내리면 내용이 사라져 접히는 모습이 보이지 않는다."""
        script = _render_expand_animation_script()
        assert "event.preventDefault();" in script
        assert "if (!opening) details.open = false;" in script

    def test_clicking_while_closing_reopens(self) -> None:
        """접히는 중에도 open은 true라서 details.open만으로는 방향을 알 수 없다."""
        assert "var opening = isClosing || !details.open;" in _render_expand_animation_script()

    def test_clip_is_restored_after_the_animation(self) -> None:
        """자른 상태를 남기면 확장 영역 안의 툴팁 말풍선이 다시 윗변에서 잘린다."""
        script = _render_expand_animation_script()
        assert "expand.style.overflow = 'hidden';" in script
        assert "expand.style.removeProperty('overflow');" in script

    def test_respects_reduced_motion(self) -> None:
        """동작 최소화를 켠 사용자에게는 기본 즉시 토글을 남긴다."""
        script = _render_expand_animation_script()
        assert "(prefers-reduced-motion: reduce)" in script
        assert "if (prefersReducedMotion()) return;" in script

    def test_degrades_without_web_animations_api(self) -> None:
        """animate가 없는 브라우저에서도 접기·펼치기 자체는 계속 동작해야 한다."""
        script = _render_expand_animation_script()
        assert "typeof Element.prototype.animate !== 'function'" in script


class TestExpandAreaStaysUnclipped:
    """CSS는 확장 영역을 상시로 자르지 않는다 — 자르기는 스크립트가 애니메이션 중에만 한다."""

    def test_expand_rule_has_no_static_overflow(self) -> None:
        start = CSS.index(".feature-expand {")
        rule = CSS[start : CSS.index("}", start)]
        assert "overflow" not in rule


class TestScriptIsIncludedInThePage:
    def test_rendered_page_carries_the_script(self) -> None:
        model = DashboardModel(
            team_name="테스트팀",
            report_date=date(2026, 7, 30),
            lookback_hours=24,
            summary_line="test",
            groups=(make_feature_group(),),
            new_work=(),
            warnings=(),
            unclassified_ratio=0.0,
            repos=("sample-group/sample-repo",),
        )

        html = render_html(model)

        assert _render_expand_animation_script() in html
