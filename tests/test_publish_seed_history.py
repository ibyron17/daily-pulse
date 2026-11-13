"""Seed 의 브랜치 생애 직렬화 테스트 (8차).

seed 소비자(발행 스킬의 AI 분석 작성자)는 seed 만 입력으로 받으므로, branch_history 가 seed 에
들어가지 않으면 7차 데이터가 소비자에게 도달할 경로가 없다.
"""

from datetime import date
from typing import Any, cast

from pulse.models import (
    BranchHistoryView,
    BranchTagDistribution,
    DashboardModel,
    FeatureGroup,
)
from pulse.publish import extract_summary_input_by_repo


def make_history(
    *,
    tags: BranchTagDistribution | None = None,
    behind_count: int | None = 90,
    truncated: bool = False,
) -> BranchHistoryView:
    """실측값을 기본으로 둔 생애 뷰."""
    return BranchHistoryView(
        base_branch="develop",
        started_on="2026-05-27",
        total_days=62,
        active_days=46,
        total_commits=211,
        truncated=truncated,
        week_commit_counts=(("2026-07-13", 12), ("2026-07-20", 50)),
        silent_gap_days=3,
        tags=tags,
        fix_surge=True,
        behind_count=behind_count,
    )


def make_model(history: BranchHistoryView | None) -> DashboardModel:
    """생애가 붙은(또는 안 붙은) 그룹 하나를 담은 모델."""
    group = FeatureGroup(
        name="tiptap",
        source_rule="branch",
        evidence="tiptap",
        stage="developing",
        repo_full_path="org/repo",
        commits=(),
        merge_requests=(),
        branch_names=("tiptap",),
        participants=(),
        branch_history=history,
    )
    return DashboardModel(
        team_name="Team",
        report_date=date(2026, 7, 27),
        lookback_hours=168,
        summary_line="",
        groups=(group,),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
        period="weekly",
    )


def seed_for(history: BranchHistoryView | None) -> dict[str, Any]:
    """그룹 seed 를 뽑는다."""
    result = cast(dict[str, Any], extract_summary_input_by_repo(make_model(history)))
    return cast(dict[str, Any], result["groups"]["org/repo::tiptap"])


class TestBranchHistorySeed:
    def test_history_is_serialised(self) -> None:
        seed = seed_for(make_history())
        assert "branch_history" in seed

    def test_all_scalar_fields_are_carried(self) -> None:
        history = seed_for(make_history())["branch_history"]
        assert history["base_branch"] == "develop"
        assert history["started_on"] == "2026-05-27"
        assert history["total_days"] == 62
        assert history["active_days"] == 46
        assert history["total_commits"] == 211
        assert history["truncated"] is False
        assert history["silent_gap_days"] == 3
        assert history["behind_count"] == 90
        assert history["fix_surge"] is True

    def test_tags_are_serialised_as_pairs(self) -> None:
        tags = BranchTagDistribution(counts=(("feat", 106), ("fix", 45)), recognized=151, total=151)
        history = seed_for(make_history(tags=tags))["branch_history"]
        assert history["tags"] == {
            "counts": [["feat", 106], ["fix", 45]],
            "recognized": 151,
            "total": 151,
        }

    def test_absent_tags_serialise_as_none(self) -> None:
        """인식률이 낮아 tags=None 인 경우 — 소비자가 태그 구성을 생략해야 한다."""
        history = seed_for(make_history(tags=None))["branch_history"]
        assert history["tags"] is None

    def test_unknown_behind_survives_as_none(self) -> None:
        history = seed_for(make_history(behind_count=None))["branch_history"]
        assert history["behind_count"] is None

    def test_truncated_flag_is_carried(self) -> None:
        """조용한 절단 금지 — 소비자가 "N건 이상"으로 표기할 근거가 필요하다."""
        history = seed_for(make_history(truncated=True))["branch_history"]
        assert history["truncated"] is True

    def test_week_counts_are_not_carried(self) -> None:
        """주별 추이(week_commit_counts)는 seed 에 싣지 않는다 — 추이는 일별 하나로 둔다."""
        history = seed_for(make_history())["branch_history"]
        assert "week_commit_counts" not in history

    def test_group_without_history_omits_the_key(self) -> None:
        """우아한 저하 — 키 자체가 없어야 소비자가 생애 표기를 건너뛴다."""
        assert "branch_history" not in seed_for(None)

    def test_seed_stays_json_serialisable(self) -> None:
        """seed 는 JSON 으로 stdout 에 나가므로 tuple 이 남아 있으면 안 된다."""
        import json

        tags = BranchTagDistribution(counts=(("feat", 1),), recognized=1, total=1)
        json.dumps(seed_for(make_history(tags=tags)), ensure_ascii=False)
