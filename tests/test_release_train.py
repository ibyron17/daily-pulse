"""릴리스 열차(승격 사다리) 구축 테스트."""

from datetime import datetime, timezone

import pytest

from pulse.grouper.release_train import build_release_train
from pulse.models import MergeRequestInfo, MRState, PromotionRung


@pytest.fixture
def release_line_patterns() -> tuple[str, ...]:
    """표준 라인 패턴."""
    return ("main", "master", "develop", "dev", "test", "sqa", "devqa", "release", "hotfix")


def make_mr(
    iid: int,
    source_branch: str,
    target_branch: str,
    state: MRState = "merged",
    merged_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MergeRequestInfo:
    """테스트용 MergeRequestInfo 생성."""
    if created_at is None:
        created_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    if updated_at is None:
        updated_at = created_at
    return MergeRequestInfo(
        iid=iid,
        title=f"MR {iid}",
        state=state,
        is_draft=False,
        labels=(),
        source_branch=source_branch,
        target_branch=target_branch,
        author_name="test-author",
        created_at=created_at,
        updated_at=updated_at,
        merged_at=merged_at,
        reviews=(),
        is_external=False,
        web_url=f"http://example.com/mr/{iid}",
    )


class TestRealWorldPattern:
    """4단 승격 사다리 예시: develop→devqa→sqa→master."""

    def test_develop_to_devqa_to_sqa_to_master(
        self, release_line_patterns: tuple[str, ...]
    ) -> None:
        """개발 흐름: develop → devqa → sqa → master."""
        tz = timezone.utc
        mrs = [
            # develop → devqa (최근)
            make_mr(101, "develop", "devqa", merged_at=datetime(2026, 7, 24, 10, 0, tzinfo=tz)),
            make_mr(100, "develop", "devqa", merged_at=datetime(2026, 7, 23, 15, 0, tzinfo=tz)),
            # devqa → sqa (최근)
            make_mr(201, "devqa", "sqa", merged_at=datetime(2026, 7, 24, 12, 0, tzinfo=tz)),
            make_mr(200, "devqa", "sqa", merged_at=datetime(2026, 7, 22, 10, 0, tzinfo=tz)),
            # sqa → master (최근)
            make_mr(301, "sqa", "master", merged_at=datetime(2026, 7, 22, 9, 0, tzinfo=tz)),
            make_mr(300, "sqa", "master", merged_at=datetime(2026, 7, 15, 14, 0, tzinfo=tz)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 3
        # 체인 순서 확인: develop → devqa → sqa → master
        assert train.rungs[0].source == "develop"
        assert train.rungs[0].target == "devqa"
        assert train.rungs[1].source == "devqa"
        assert train.rungs[1].target == "sqa"
        assert train.rungs[2].source == "sqa"
        assert train.rungs[2].target == "master"

    def test_merged_count_aggregation(self, release_line_patterns: tuple[str, ...]) -> None:
        """칸별 merged_count 집계."""
        tz = timezone.utc
        mrs = [
            make_mr(1, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=tz)),
            make_mr(2, "develop", "devqa", merged_at=datetime(2026, 7, 23, tzinfo=tz)),
            make_mr(3, "develop", "devqa", merged_at=datetime(2026, 7, 22, tzinfo=tz)),
            make_mr(4, "devqa", "sqa", merged_at=datetime(2026, 7, 24, tzinfo=tz)),
            make_mr(5, "devqa", "sqa", merged_at=datetime(2026, 7, 20, tzinfo=tz)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 2
        # develop → devqa: 3개
        assert train.rungs[0].merged_count == 3
        # devqa → sqa: 2개
        assert train.rungs[1].merged_count == 2

    def test_open_count_aggregation(self, release_line_patterns: tuple[str, ...]) -> None:
        """칸별 open_count 집계."""
        tz = timezone.utc
        mrs = [
            make_mr(
                1, "develop", "devqa", state="merged", merged_at=datetime(2026, 7, 24, tzinfo=tz)
            ),
            make_mr(2, "develop", "devqa", state="open"),  # open 상태
            make_mr(3, "develop", "devqa", state="open"),  # open 상태
            make_mr(4, "devqa", "sqa", state="merged", merged_at=datetime(2026, 7, 24, tzinfo=tz)),
            make_mr(5, "devqa", "sqa", state="open"),  # open 상태
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 2
        # develop → devqa: open 2개
        assert train.rungs[0].open_count == 2
        # devqa → sqa: open 1개
        assert train.rungs[1].open_count == 1

    def test_last_merged_at_iid(self, release_line_patterns: tuple[str, ...]) -> None:
        """각 칸의 최근 merged 시각과 IID."""
        mrs = [
            make_mr(
                1, "develop", "devqa", merged_at=datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
            ),
            make_mr(
                2, "develop", "devqa", merged_at=datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
            ),  # 최신
            make_mr(
                3, "develop", "devqa", merged_at=datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
            ),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 1
        assert train.rungs[0].last_merged_at == datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
        assert train.rungs[0].last_mr_iid == 2

    def test_merged_at_none_handling(self, release_line_patterns: tuple[str, ...]) -> None:
        """merged_at이 None인 MR 처리 (skip)."""
        mrs = [
            make_mr(1, "develop", "devqa", state="merged", merged_at=None),  # merged_at 없음
            make_mr(
                2, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 정상
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 1
        assert train.rungs[0].merged_count == 2  # 둘 다 카운트
        assert train.rungs[0].last_merged_at == datetime(2026, 7, 24, tzinfo=timezone.utc)
        assert train.rungs[0].last_mr_iid == 2


class TestFeatureBranchExclusion:
    """기능 브랜치 → 라인 MR 제외."""

    def test_feature_to_line_excluded(self, release_line_patterns: tuple[str, ...]) -> None:
        """기능 브랜치에서 라인으로의 MR은 사다리에 미포함."""
        mrs = [
            make_mr(
                1, "feat/auth", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),
            make_mr(2, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 1
        assert train.rungs[0].source == "develop"
        assert train.rungs[0].target == "devqa"

    def test_feature_source_and_target_mixed(self, release_line_patterns: tuple[str, ...]) -> None:
        """기능 브랜치 관련 MR 전부 제외."""
        mrs = [
            make_mr(
                1, "feat/auth", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 기능 → 라인
            make_mr(
                2, "hotfix/x", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 기능 → 라인
            make_mr(
                3, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 라인 → 라인 (포함)
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 1
        assert train.rungs[0].source == "develop"


class TestEmptyInputs:
    """빈 입력 처리."""

    def test_empty_mrs(self, release_line_patterns: tuple[str, ...]) -> None:
        """MR 없음 → 빈 ReleaseTrain."""
        train = build_release_train((), release_line_patterns)

        assert train.rungs == ()
        assert len(train.rungs) == 0

    def test_no_line_to_line_mrs(self, release_line_patterns: tuple[str, ...]) -> None:
        """라인→라인 MR이 없음 → 빈 ReleaseTrain."""
        mrs = [
            make_mr(
                1, "feat/auth", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),
            make_mr(2, "feat/api", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert train.rungs == ()


class TestLinePatternMatching:
    """라인 패턴 판별 (대소문자 무시)."""

    def test_case_insensitive_matching(self, release_line_patterns: tuple[str, ...]) -> None:
        """대소문자 무시로 패턴 판별."""
        mrs = [
            make_mr(1, "DEVELOP", "DEVQA", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
            make_mr(2, "Develop", "DevQA", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # 둘 다 라인 패턴으로 인식 → 사다리 1칸
        assert len(train.rungs) == 1

    def test_pattern_not_matching(self, release_line_patterns: tuple[str, ...]) -> None:
        """패턴에 없는 브랜치는 제외."""
        mrs = [
            make_mr(
                1,
                "release/2026-q3",
                "develop",
                merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            ),
            make_mr(
                2, "develop", "custom-test", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # 둘 다 라인 패턴 미포함 → 빈 사다리
        assert train.rungs == ()


class TestBranchingAndCyclic:
    """분기·순환 처리 (폴백)."""

    def test_branching_fallback(self, release_line_patterns: tuple[str, ...]) -> None:
        """분기(한 source가 여러 target): 폴백."""
        mrs = [
            make_mr(1, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
            make_mr(
                2, "develop", "test", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 분기
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # 두 칸이 있지만 분기라서 정렬 불가 → merged_count 내림차순 폴백
        assert len(train.rungs) == 2
        # 두 칸의 merged_count가 같으면 순서는 보장 안 함, 하지만 칸 모두 포함
        sources = {r.source for r in train.rungs}
        targets = {r.target for r in train.rungs}
        assert "develop" in sources
        assert "devqa" in targets or "test" in targets

    def test_cyclic_fallback(self, release_line_patterns: tuple[str, ...]) -> None:
        """순환(a→b, b→a): 폴백."""
        mrs = [
            make_mr(1, "develop", "devqa", merged_at=datetime(2026, 7, 20, tzinfo=timezone.utc)),
            make_mr(
                2, "devqa", "develop", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)
            ),  # 순환
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # 순환으로 인해 정렬 불가 → merged_count 내림차순 폴백
        assert len(train.rungs) == 2
        # 최신 merged_at을 가진 칸이 앞에 올 수 있음
        assert all(isinstance(r, PromotionRung) for r in train.rungs)

    def test_multiple_start_points_fallback(self, release_line_patterns: tuple[str, ...]) -> None:
        """여러 시작점(분기된 체인들): 폴백."""
        mrs = [
            # 체인 1: develop → devqa
            make_mr(1, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
            # 체인 2: test → sqa (독립적)
            make_mr(2, "test", "sqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # 두 개의 독립 체인 → 단일 체인 정렬 불가 → 폴백
        assert len(train.rungs) == 2


class TestClosedState:
    """closed 상태 MR 처리."""

    def test_closed_not_counted(self, release_line_patterns: tuple[str, ...]) -> None:
        """closed MR은 merged_count·open_count 미포함, 칸 판정에만 사용."""
        mrs = [
            make_mr(1, "develop", "devqa", state="closed"),  # closed
            make_mr(
                2,
                "develop",
                "devqa",
                state="merged",
                merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            ),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        assert len(train.rungs) == 1
        assert train.rungs[0].merged_count == 1
        assert train.rungs[0].open_count == 0


class TestDataIntegrity:
    """데이터 무결성."""

    def test_result_is_frozen(self, release_line_patterns: tuple[str, ...]) -> None:
        """ReleaseTrain과 PromotionRung은 frozen."""
        mrs = [
            make_mr(1, "develop", "devqa", merged_at=datetime(2026, 7, 24, tzinfo=timezone.utc)),
        ]

        train = build_release_train(tuple(mrs), release_line_patterns)

        # frozen dataclass 확인
        with pytest.raises(AttributeError):
            train.rungs = ()  # type: ignore

        if train.rungs:
            with pytest.raises(AttributeError):
                train.rungs[0].source = "other"  # type: ignore
