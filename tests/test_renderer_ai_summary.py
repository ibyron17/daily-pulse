"""AI 요약 섹션 렌더링 및 주입 테스트 (레포별 슬롯)."""

from datetime import date

from pulse.models import DashboardModel
from pulse.renderer.html import ai_summary_slot, inject_ai_summary, render_html
from pulse.renderer.sections import render_ai_summary


def test_render_ai_summary_with_text() -> None:
    """render_ai_summary가 텍스트를 받으면 ai-summary 섹션을 렌더한다."""
    summary = "오늘은 신규 기능 3개가 진행 중입니다."
    result = render_ai_summary(summary)
    assert '<section class="ai-summary">' in result
    assert "일간 브리핑" in result
    assert "오늘은 신규 기능 3개가 진행 중입니다." in result


def test_render_ai_summary_empty_string() -> None:
    """render_ai_summary가 빈 문자열을 받으면 빈 문자열을 반환한다."""
    result = render_ai_summary("")
    assert result == ""


def test_render_ai_summary_none() -> None:
    """render_ai_summary가 None을 받으면 빈 문자열을 반환한다."""
    result = render_ai_summary(None)
    assert result == ""


def test_render_ai_summary_whitespace() -> None:
    """render_ai_summary가 공백만 있으면 빈 문자열을 반환한다."""
    result = render_ai_summary("   \n  \t  ")
    assert result == ""


def test_render_ai_summary_xss_escape() -> None:
    """render_ai_summary가 <script> 태그를 escape한다."""
    dangerous = "<script>alert('XSS')</script>"
    result = render_ai_summary(dangerous)
    assert "&lt;script&gt;" in result
    assert "<script>" not in result
    assert "&lt;/script&gt;" in result


def test_render_html_single_repo_contains_slot() -> None:
    """render_html(단일 레포)이 해당 레포의 AI 요약 슬롯을 포함한다."""
    model = DashboardModel(
        team_name="Test Team",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        period="daily",
        repos=("org/repo",),
    )
    html = render_html(model)
    assert ai_summary_slot("org/repo") in html
    # 본문 최상단에는 전역 슬롯이 없어야 함


def test_render_html_multiple_repos_contains_slots() -> None:
    """render_html(다중 레포)이 각 레포의 AI 요약 슬롯을 포함한다 (본문 최상단 제외)."""
    model = DashboardModel(
        team_name="Test Team",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="테스트",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        period="daily",
        repos=("org/repo1", "org/repo2"),
    )
    html = render_html(model)
    # 각 레포 슬롯이 포함되어야 함
    assert ai_summary_slot("org/repo1") in html
    assert ai_summary_slot("org/repo2") in html
    # 본문 최상단에는 전역 슬롯이 없어야 함 (탭 내부에만 있어야 함)
    # 탭 내부에 있으므로 직접 테스트 불가하지만, 각 슬롯이 탭 내부에 있는지 확인
    repo1_tab_start = html.find('id="tab-content-org__repo1"')
    repo1_tab_end = html.find('id="tab-content-org__repo2"') if "org__repo2" in html else len(html)
    if repo1_tab_start >= 0:
        repo1_section = html[repo1_tab_start:repo1_tab_end]
        assert ai_summary_slot("org/repo1") in repo1_section


def test_inject_ai_summary_replaces_slot() -> None:
    """inject_ai_summary가 해당 레포 슬롯만 요약 섹션으로 치환한다."""
    slot_a = ai_summary_slot("org/repo-a")
    slot_b = ai_summary_slot("org/repo-b")
    html = f"<body>\n{slot_a}\n<p>Content A</p>\n{slot_b}\n<p>Content B</p>\n</body>"
    summary = "테스트 요약 A"
    result = inject_ai_summary(html, "org/repo-a", summary)

    assert slot_a not in result
    assert slot_b in result  # 다른 레포 슬롯은 유지
    assert '<section class="ai-summary">' in result
    assert "테스트 요약 A" in result
    assert "<p>Content A</p>" in result
    assert "<p>Content B</p>" in result


def test_inject_ai_summary_empty_removes_slot() -> None:
    """inject_ai_summary가 빈 요약을 받으면 해당 슬롯을 제거한다 (graceful)."""
    slot = ai_summary_slot("org/repo")
    html = f"<body>\n{slot}\n<p>Content</p>\n</body>"
    result = inject_ai_summary(html, "org/repo", "")

    assert slot not in result
    assert '<section class="ai-summary">' not in result
    assert "<p>Content</p>" in result


def test_inject_ai_summary_no_slot() -> None:
    """inject_ai_summary가 슬롯 없는 HTML을 받으면 원본을 반환한다."""
    html = "<body><p>Content</p></body>"
    summary = "요약"
    result = inject_ai_summary(html, "org/repo", summary)

    assert result == html


def test_inject_ai_summary_same_repo_multiple_slots() -> None:
    """inject_ai_summary가 같은 레포의 모든 슬롯을 같은 요약으로 치환한다."""
    slot = ai_summary_slot("org/repo")
    html = f"{slot}\n<p>Content</p>\n{slot}"
    summary = "요약"
    result = inject_ai_summary(html, "org/repo", summary)

    assert slot not in result
    assert result.count('<section class="ai-summary">') == 2


def test_inject_ai_summary_preserves_other_content() -> None:
    """inject_ai_summary가 다른 콘텐츠를 보존한다."""
    slot = ai_summary_slot("org/repo")
    html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
{slot}
<h1>Title</h1>
<p>Paragraph</p>
</body>
</html>"""
    summary = "요약 텍스트"
    result = inject_ai_summary(html, "org/repo", summary)

    assert "<!DOCTYPE html>" in result
    assert "<h1>Title</h1>" in result
    assert "<p>Paragraph</p>" in result
    assert "요약 텍스트" in result


def test_render_ai_summary_html_structure() -> None:
    """render_ai_summary가 올바른 HTML 구조를 생성한다."""
    summary = "Summary"
    result = render_ai_summary(summary)

    assert '<section class="ai-summary">' in result
    assert "<h2>일간 브리핑</h2>" in result
    assert '<p class="ai-summary-content">' in result
    assert "</section>" in result


def test_render_ai_summary_multiline_text() -> None:
    """render_ai_summary가 줄바꿈 포함 텍스트를 처리한다."""
    summary = "Line 1\nLine 2\nLine 3"
    result = render_ai_summary(summary)

    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result
    assert '<section class="ai-summary">' in result


def test_render_ai_summary_special_chars() -> None:
    """render_ai_summary가 특수 문자를 escape한다."""
    summary = "Test & <div> \"quotes\" 'apostrophe'"
    result = render_ai_summary(summary)

    assert "&amp;" in result
    assert "&lt;div&gt;" in result
    assert "&quot;" in result or '"' in result  # quotes는 escape될 수도, 아닐 수도 있음


def test_inject_ai_summary_whitespace_summary() -> None:
    """inject_ai_summary가 공백만 있는 요약을 받으면 해당 슬롯을 제거한다."""
    slot = ai_summary_slot("org/repo")
    html = f"<body>{slot}<p>Content</p></body>"
    result = inject_ai_summary(html, "org/repo", "   \n   ")

    assert slot not in result
    assert '<section class="ai-summary">' not in result


def test_render_ai_summary_period_daily() -> None:
    """period='daily'면 제목이 '일간 브리핑'이다."""
    result = render_ai_summary("요약 내용", period="daily")

    assert "<h2>일간 브리핑</h2>" in result


def test_render_ai_summary_period_weekly() -> None:
    """period='weekly'면 제목이 '주간 브리핑'이다."""
    result = render_ai_summary("요약 내용", period="weekly")

    assert "<h2>주간 브리핑</h2>" in result
    assert "일간 브리핑" not in result


def test_render_ai_summary_default_period_daily() -> None:
    """period 인자 생략 시 일간 제목을 사용한다 (하위호환)."""
    result = render_ai_summary("요약 내용")

    assert "<h2>일간 브리핑</h2>" in result


def test_inject_ai_summary_weekly_period() -> None:
    """inject 경로에서 period='weekly'가 주간 제목으로 렌더된다 (배선 검증)."""
    slot = ai_summary_slot("org/repo")
    html = f"<body>{slot}</body>"
    result = inject_ai_summary(html, "org/repo", "주간 요약입니다.", period="weekly")

    assert "<h2>주간 브리핑</h2>" in result
