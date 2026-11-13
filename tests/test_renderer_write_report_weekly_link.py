"""write_report의 주간 링크 통일 테스트."""

from datetime import date
from pathlib import Path

from pulse.renderer.html import PULSE_SWITCH_HREF_PLACEHOLDER, write_report


def test_write_report_dated_daily_links_to_latest_weekly(tmp_path: Path) -> None:
    """dated daily의 주간 전환 링크는 항상 latest-weekly.html을 가리킨다."""
    html = f"""<html>
<header>
  <a href="{PULSE_SWITCH_HREF_PLACEHOLDER}" class="period-switch">주간 보기</a>
</header>
<body>content</body>
</html>"""

    report_date = date(2026, 7, 22)
    dated_path, latest_path = write_report(html, tmp_path, report_date)

    # dated 파일 확인
    dated_content = dated_path.read_text()
    assert "latest-weekly.html" in dated_content
    assert PULSE_SWITCH_HREF_PLACEHOLDER not in dated_content

    # latest 파일 확인
    assert latest_path is not None
    latest_content = latest_path.read_text()
    assert "latest-weekly.html" in latest_content
    assert PULSE_SWITCH_HREF_PLACEHOLDER not in latest_content


def test_write_report_non_monday_dated_still_links_to_latest_weekly(tmp_path: Path) -> None:
    """비월요일 발행 시에도 dated daily는 latest-weekly.html을 가리킨다."""
    html = f"""<html>
<a href="{PULSE_SWITCH_HREF_PLACEHOLDER}">주간</a>
</html>"""

    # 화요일 (비월요일)
    report_date = date(2026, 7, 21)
    dated_path, latest_path = write_report(html, tmp_path, report_date)

    dated_content = dated_path.read_text()
    # dated 파일도 latest-weekly.html을 가리켜야 함
    assert "latest-weekly.html" in dated_content


def test_write_report_creates_both_files(tmp_path: Path) -> None:
    """write_report는 dated와 latest 두 파일을 생성한다."""
    html = f"""<html>
<a href="{PULSE_SWITCH_HREF_PLACEHOLDER}">주간</a>
</html>"""

    report_date = date(2026, 7, 22)
    dated_path, latest_path = write_report(html, tmp_path, report_date)

    # 두 파일이 모두 존재해야 함
    assert dated_path.exists()
    assert latest_path is not None
    assert latest_path.exists()

    # 파일명 확인
    assert dated_path.name == "pulse-2026-07-22.html"
    assert latest_path.name == "latest.html"
