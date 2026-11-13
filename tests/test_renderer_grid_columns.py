"""프로젝트 현황 카드 그리드의 최대 3컬럼 규칙 테스트 (문자열 단언 — 렌더러 테스트 관례)."""

from pulse.models import FeatureGroup, TaskSummary
from pulse.renderer.sections import render_feature_cards
from pulse.renderer.styles import CSS


def _make_group(name: str) -> FeatureGroup:
    """그리드 렌더 검증용 최소 그룹 생성."""
    return FeatureGroup(
        name=name,
        source_rule="branch",
        evidence="",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=(name,),
        participants=(),
        task_summary=TaskSummary(
            commit_titles=(),
            open_mr_titles=(),
            active_branch_names=(),
        ),
    )


def test_feature_cards_container_uses_feature_list_class() -> None:
    """기능 리스트 컨테이너가 feature-list 클래스를 사용한다."""
    html = render_feature_cards((_make_group("feature/a"), _make_group("feature/b")))

    assert '<div class="feature-list">' in html
    assert '<details class="feature-row">' in html


def test_css_has_no_dead_cards_grid_rules() -> None:
    """기능 목록은 카드 그리드가 아니라 확장형 리스트다 — .cards-grid는 죽은 규칙이다.

    렌더러가 이 클래스를 만들지 않는데도 CSS와 이 테스트가 서로를 지탱하고 있었다.
    (`grep -rn 'class="cards-grid' pulse/` → 0건)
    """
    assert ".cards-grid" not in CSS


def test_css_fixes_participation_map_columns() -> None:
    """팀 참여 그리드도 컬럼 수 고정 규칙을 사용한다 (auto-fit 가변 폭 금지)."""
    assert "repeat(4, 1fr)" in CSS  # 데스크톱: 4컬럼 고정
    assert "minmax(200px, 1fr)" not in CSS  # 기존 auto-fit 규칙 제거됨
    # 기본 + 1024px + 768px — 최소 3개 규칙 블록
    assert CSS.count(".participation-map") >= 3
