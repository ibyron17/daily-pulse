"""HTML 대시보드 렌더링 (Phase 4). 순수 로직 + 파일 출력."""

from pulse.renderer.assemble import build_dashboard_model
from pulse.renderer.html import render_html, write_report, write_weekly_report

__all__ = ["build_dashboard_model", "render_html", "write_report", "write_weekly_report"]
