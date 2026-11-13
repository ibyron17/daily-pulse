"""그룹 AI 제목/분석 slot 및 inject 함수 테스트."""

from pulse.renderer.html import inject_group_ai_title, inject_group_analysis
from pulse.renderer.sections import group_ai_title_slot, group_analysis_slot


def test_group_ai_title_slot_basic() -> None:
    """group_ai_title_slot이 올바른 마커를 생성한다."""
    repo = "org/repo"
    group_name = "feature-auth"

    result = group_ai_title_slot(repo, group_name)

    assert "<!--PULSE_GROUP_AI_TITLE_SLOT:" in result
    assert "org/repo::feature-auth-->" in result


def test_group_ai_title_slot_special_chars() -> None:
    """group_ai_title_slot이 특수문자를 정리한다."""
    repo = "org/repo"
    group_name = "feature/auth<tag>-->"

    result = group_ai_title_slot(repo, group_name)

    # group_name의 <, >, --> 제거됨 (마커 자체의 <!-- 는 남음)
    # 마커: <!--PULSE_GROUP_AI_TITLE_SLOT:org/repo::feature/authtag-->
    assert "feature/authtag" in result
    assert "<tag>" not in result
    assert "feature/auth<tag>" not in result


def test_group_analysis_slot_basic() -> None:
    """group_analysis_slot이 올바른 마커를 생성한다."""
    repo = "org/repo"
    group_name = "feature-auth"

    result = group_analysis_slot(repo, group_name)

    assert "<!--PULSE_GROUP_ANALYSIS_SLOT:" in result
    assert "org/repo::feature-auth-->" in result


def test_group_analysis_slot_special_chars() -> None:
    """group_analysis_slot이 특수문자를 정리한다."""
    repo = "org/repo"
    group_name = "feature/auth<tag>-->"

    result = group_analysis_slot(repo, group_name)

    # group_name의 <, >, --> 제거됨 (마커 자체의 <!-- 는 남음)
    assert "feature/authtag" in result
    assert "<tag>" not in result


def test_inject_group_ai_title_basic() -> None:
    """inject_group_ai_title이 slot을 치환한다."""
    repo = "org/repo"
    group_name = "feature-auth"
    title = "인증 시스템 리팩토링"

    html = f"""<div class="card">
    {group_ai_title_slot(repo, group_name)}
    <div class="group-name">feature-auth</div>
</div>"""

    result = inject_group_ai_title(html, repo, group_name, title)

    # slot이 사라지고 제목이 주입됨
    assert "PULSE_GROUP_AI_TITLE_SLOT" not in result
    assert "인증 시스템 리팩토링" in result
    assert 'class="group-ai-title"' in result


def test_inject_group_ai_title_empty_title() -> None:
    """inject_group_ai_title이 빈 제목을 slot 제거로 처리한다."""
    repo = "org/repo"
    group_name = "feature-auth"

    html = f"""<div>{group_ai_title_slot(repo, group_name)}</div>"""

    result = inject_group_ai_title(html, repo, group_name, "")

    # slot이 빈 문자열로 치환됨
    assert "PULSE_GROUP_AI_TITLE_SLOT" not in result
    assert result.strip() == "<div></div>"


def test_inject_group_analysis_basic() -> None:
    """inject_group_analysis가 slot을 치환한다."""
    repo = "org/repo"
    group_name = "feature-auth"
    analysis = "현재 인증 모듈 리팩토링 중입니다."

    html = f"""<div>
    {group_analysis_slot(repo, group_name)}
    <details>내용</details>
</div>"""

    result = inject_group_analysis(html, repo, group_name, analysis)

    # slot이 사라지고 분석이 주입됨
    assert "PULSE_GROUP_ANALYSIS_SLOT" not in result
    assert "현재 인증 모듈 리팩토링 중입니다." in result
    assert 'class="group-analysis"' in result


def test_inject_group_analysis_empty_analysis() -> None:
    """inject_group_analysis가 빈 분석을 slot 제거로 처리한다."""
    repo = "org/repo"
    group_name = "feature-auth"

    html = f"""<div>{group_analysis_slot(repo, group_name)}</div>"""

    result = inject_group_analysis(html, repo, group_name, "")

    # slot이 빈 문자열로 치환됨
    assert "PULSE_GROUP_ANALYSIS_SLOT" not in result
    assert result.strip() == "<div></div>"


def test_inject_group_title_multiple_slots() -> None:
    """inject_group_ai_title이 같은 group의 여러 slot을 모두 치환한다."""
    repo = "org/repo"
    group_name = "feature-auth"
    title = "제목"

    html = f"""<div>
    {group_ai_title_slot(repo, group_name)}
    <p>content</p>
    {group_ai_title_slot(repo, group_name)}
</div>"""

    result = inject_group_ai_title(html, repo, group_name, title)

    # 모든 slot이 치환됨 (str.replace는 모든 occurrence를 치환)
    assert "PULSE_GROUP_AI_TITLE_SLOT" not in result
    # 2개의 제목이 주입됨
    assert result.count('class="group-ai-title"') == 2


def test_inject_group_title_different_groups() -> None:
    """inject_group_ai_title이 다른 그룹의 slot은 그대로 둔다."""
    repo = "org/repo"
    group1 = "feature-auth"
    group2 = "feature-api"
    title = "제목"

    html = f"""<div>
    {group_ai_title_slot(repo, group1)}
    {group_ai_title_slot(repo, group2)}
</div>"""

    result = inject_group_ai_title(html, repo, group1, title)

    # group1의 slot만 치환됨
    assert "PULSE_GROUP_AI_TITLE_SLOT" in result
    assert group2 in result
    assert group1 not in result or "group1" not in result
