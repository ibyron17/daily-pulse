"""그룹 AI 제목·분석의 end-to-end 주입 검증.

카드 렌더가 만든 slot을 실제 발행 플로우(`_inject_into_saved_reports`)가
채우는지 확인한다 — 단위 함수는 통과해도 배선이 빠지면 카드가 영원히 비는
회귀를 이 테스트가 잡는다.
"""

from pathlib import Path

from pulse.publish import _inject_into_saved_reports
from pulse.renderer.sections import (
    group_ai_title_slot,
    group_analysis_slot,
    render_feature_cards,
)
from tests.conftest import make_feature_group

_REPO = "sample-group/sample-repo"
_GROUP_NAME = "feature/ai-assistant"


def _write_daily_report(dir_path: Path, body: str) -> Path:
    """카드 body를 latest.html(일간)로 저장한다."""
    path = dir_path / "latest.html"
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return path


def _daily_summaries(title: str, analysis: str) -> dict[str, object]:
    """groups.daily에 제목·분석을 담은 summary.json 형태 dict."""
    return {
        "daily": {_REPO: ""},
        "groups": {"daily": {f"{_REPO}::{_GROUP_NAME}": {"title": title, "analysis": analysis}}},
    }


def test_card_render_emits_slots_matching_inject_markers() -> None:
    """카드가 emit한 slot 마커가 inject가 찾는 마커와 정확히 일치한다 (render↔inject 배선)."""
    group = make_feature_group(name=_GROUP_NAME, repo_full_path=_REPO)

    card_html = render_feature_cards((group,), repo_filter=_REPO)

    assert group_ai_title_slot(_REPO, _GROUP_NAME) in card_html
    assert group_analysis_slot(_REPO, _GROUP_NAME) in card_html


def test_inject_fills_group_title_and_analysis(tmp_path: Path) -> None:
    """실제 발행 플로우가 그룹 AI 제목·분석 slot을 채운다."""
    group = make_feature_group(name=_GROUP_NAME, repo_full_path=_REPO)
    card_html = render_feature_cards((group,), repo_filter=_REPO)
    _write_daily_report(tmp_path, card_html)

    _inject_into_saved_reports(
        tmp_path, _daily_summaries("AI 어시스턴트 통합", "채팅 기반 편집 도우미")
    )

    result = (tmp_path / "latest.html").read_text(encoding="utf-8")
    assert '<div class="group-ai-title">' in result
    assert "AI 어시스턴트 통합" in result
    assert '<div class="group-analysis">' in result
    assert "채팅 기반 편집 도우미" in result
    # slot 마커는 소진되어 사라진다
    assert group_ai_title_slot(_REPO, _GROUP_NAME) not in result
    assert group_analysis_slot(_REPO, _GROUP_NAME) not in result


def test_inject_without_groups_leaves_branch_name(tmp_path: Path) -> None:
    """groups 미제공 시 slot은 비고 브랜치명(.group-name)이 제목으로 유지된다 (우아한 저하)."""
    group = make_feature_group(name=_GROUP_NAME, repo_full_path=_REPO)
    card_html = render_feature_cards((group,), repo_filter=_REPO)
    _write_daily_report(tmp_path, card_html)

    _inject_into_saved_reports(tmp_path, {"daily": {_REPO: ""}})

    result = (tmp_path / "latest.html").read_text(encoding="utf-8")
    assert '<div class="group-ai-title">' not in result
    assert '<div class="group-name">' in result
    assert _GROUP_NAME in result


def test_inject_escapes_group_title_and_analysis(tmp_path: Path) -> None:
    """주입되는 제목·분석의 HTML 특수문자는 escape된다 (마크업 주입 방지)."""
    group = make_feature_group(name=_GROUP_NAME, repo_full_path=_REPO)
    card_html = render_feature_cards((group,), repo_filter=_REPO)
    _write_daily_report(tmp_path, card_html)

    _inject_into_saved_reports(tmp_path, _daily_summaries("<script>x</script>", "a & b < c"))

    result = (tmp_path / "latest.html").read_text(encoding="utf-8")
    assert "<script>x</script>" not in result
    assert "&lt;script&gt;" in result
    assert "a &amp; b &lt; c" in result
