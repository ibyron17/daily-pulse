"""base(개발 기준선) 브랜치 결정 순수 로직 테스트."""

import logging
from datetime import datetime, timezone

from pulse.collector.base_branch import (
    BASE_BRANCH_CANDIDATES,
    build_base_candidates,
    pick_closest_base,
)


def at(month: int, day: int) -> datetime:
    """테스트용 시각."""
    return datetime(2026, month, day, tzinfo=timezone.utc)


class TestPickClosestBase:
    def test_picks_most_recent_branch_point(self) -> None:
        """분기점이 가장 최근인 브랜치가 실제 개발 기준선이다."""
        candidates = (("master", at(1, 10)), ("develop", at(7, 1)))
        assert pick_closest_base(candidates) == "develop"

    def test_ignores_candidates_without_branch_point(self) -> None:
        candidates = (("develop", None), ("master", at(1, 10)))
        assert pick_closest_base(candidates) == "master"

    def test_all_unresolved_returns_none(self) -> None:
        assert pick_closest_base((("develop", None), ("master", None))) is None

    def test_empty_returns_none(self) -> None:
        assert pick_closest_base(()) is None

    def test_tie_prefers_conventional_order(self) -> None:
        """같은 시각이면 관례 순서(develop 우선)를 따른다."""
        same = at(7, 1)
        assert pick_closest_base((("master", same), ("develop", same))) == "develop"
        assert BASE_BRANCH_CANDIDATES.index("develop") < BASE_BRANCH_CANDIDATES.index("master")

    def test_unknown_name_ranks_last_on_tie(self) -> None:
        same = at(7, 1)
        assert pick_closest_base((("custom-line", same), ("master", same))) == "master"


class TestBuildBaseCandidates:
    def test_hint_is_used_alone(self) -> None:
        """config 지정이 있으면 후보를 1개로 줄여 merge_base 조회를 1회로 만든다."""
        candidates = build_base_candidates(
            "feature/x",
            base_hint="develop",
            existing_branches=frozenset({"develop", "master", "feature/x"}),
            default_branch="master",
        )
        assert candidates == ("develop",)

    def test_missing_hint_falls_back_with_warning(self, caplog: object) -> None:
        with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
            candidates = build_base_candidates(
                "feature/x",
                base_hint="nonexistent",
                existing_branches=frozenset({"develop", "master"}),
                default_branch="master",
            )
        assert candidates == ("develop", "master")
        assert "nonexistent" in caplog.text  # type: ignore[attr-defined]

    def test_gitflow_repo_offers_both_lines(self) -> None:
        """실측 레포 형태 — develop과 master가 함께 있으면 둘 다 후보다."""
        candidates = build_base_candidates(
            "feature/x",
            base_hint=None,
            existing_branches=frozenset({"develop", "master", "feature/x", "hotfix/y"}),
            default_branch="master",
        )
        assert candidates == ("develop", "master")

    def test_default_branch_appended_when_not_conventional(self) -> None:
        candidates = build_base_candidates(
            "feature/x",
            base_hint=None,
            existing_branches=frozenset({"release-line", "feature/x"}),
            default_branch="release-line",
        )
        assert candidates == ("release-line",)

    def test_self_is_excluded(self) -> None:
        """base 후보에서 자기 자신은 제외한다 (develop 자체를 분석할 때)."""
        candidates = build_base_candidates(
            "develop",
            base_hint=None,
            existing_branches=frozenset({"develop", "master"}),
            default_branch="master",
        )
        assert candidates == ("master",)

    def test_hint_equal_to_self_yields_nothing(self) -> None:
        candidates = build_base_candidates(
            "develop",
            base_hint="develop",
            existing_branches=frozenset({"develop"}),
            default_branch="develop",
        )
        assert candidates == ()

    def test_single_branch_repo_yields_nothing(self) -> None:
        """브랜치가 default 하나뿐인 레포는 분석 대상이 없다 (실측: sample-docs)."""
        candidates = build_base_candidates(
            "main",
            base_hint=None,
            existing_branches=frozenset({"main"}),
            default_branch="main",
        )
        assert candidates == ()


class TestPrefixParentCandidates:
    """브랜치에서 파생된 브랜치는 부모 브랜치가 base 후보에 올라야 한다.

    실측(2026-07-30): feature/ai_visualize에서 파생된 feature/ai_visualize_poc를
    develop과 비교하면 부모의 커밋이 섞여 시작일이 1년 일찍 잡혔다.
    """

    def test_prefix_parent_is_first_candidate(self) -> None:
        candidates = build_base_candidates(
            "feature/ai_visualize_poc",
            base_hint=None,
            existing_branches=frozenset(
                {"develop", "master", "feature/ai_visualize", "feature/ai_visualize_poc"}
            ),
            default_branch="master",
        )
        assert candidates == ("feature/ai_visualize", "develop", "master")

    def test_parent_requires_separator(self) -> None:
        """단순 접두사 일치(developqa ⊃ develop)는 파생 관계가 아니다."""
        candidates = build_base_candidates(
            "developqa",
            base_hint=None,
            existing_branches=frozenset({"develop", "developqa", "master"}),
            default_branch="master",
        )
        assert candidates == ("develop", "master")

    def test_longest_parent_comes_first(self) -> None:
        """중첩 파생이면 가장 가까운(긴 이름의) 부모가 앞선다."""
        candidates = build_base_candidates(
            "feature/ai_visualize_poc_v2",
            base_hint=None,
            existing_branches=frozenset(
                {
                    "develop",
                    "feature/ai_visualize",
                    "feature/ai_visualize_poc",
                    "feature/ai_visualize_poc_v2",
                }
            ),
            default_branch="develop",
        )
        assert candidates == ("feature/ai_visualize_poc", "feature/ai_visualize", "develop")

    def test_hint_does_not_hide_parent(self) -> None:
        """hint는 레포 관례일 뿐 — 파생 브랜치에는 부모도 함께 후보로 남긴다."""
        candidates = build_base_candidates(
            "feature/ai_visualize_poc",
            base_hint="develop",
            existing_branches=frozenset(
                {"develop", "feature/ai_visualize", "feature/ai_visualize_poc"}
            ),
            default_branch="develop",
        )
        assert candidates == ("feature/ai_visualize", "develop")

    def test_line_branch_child_keeps_conventional_bases(self) -> None:
        """release/1.0 같은 브랜치에서 release가 없으면 후보는 기존과 동일하다."""
        candidates = build_base_candidates(
            "release/1.0",
            base_hint=None,
            existing_branches=frozenset({"develop", "master", "release/1.0"}),
            default_branch="master",
        )
        assert candidates == ("develop", "master")
