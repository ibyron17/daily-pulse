"""커밋 태그 파싱·집계·fix 급증 감지 테스트."""

from datetime import date

from pulse.grouper.commit_tags import (
    build_tag_distribution,
    build_week_fix_ratios,
    detect_fix_surge,
    is_merge_title,
    parse_tag,
    week_start_of,
)


class TestParseTag:
    """세 형식을 모두 인식해야 한다 — 실측에서 조직 안에 두 관례가 공존했다."""

    def test_bracket_format(self) -> None:
        assert parse_tag("[feat] 토큰 교환 구현") == "feat"

    def test_plain_conventional_format(self) -> None:
        assert parse_tag("feat: add token exchange") == "feat"

    def test_scoped_conventional_format(self) -> None:
        assert parse_tag("feat(api): add token exchange") == "feat"

    def test_breaking_change_marker(self) -> None:
        assert parse_tag("feat!: drop legacy endpoint") == "feat"
        assert parse_tag("feat(api)!: drop legacy endpoint") == "feat"

    def test_case_is_normalized(self) -> None:
        assert parse_tag("[FIX] 오류 수정") == "fix"
        assert parse_tag("Refactor: 정리") == "refactor"

    def test_merge_commit_is_not_a_tag(self) -> None:
        assert parse_tag("Merge branch 'develop' into feature/x") is None

    def test_free_form_title_is_unrecognized(self) -> None:
        assert parse_tag("로그인 화면 정리") is None

    def test_bracket_wins_over_merge_wording(self) -> None:
        # 접두가 태그면 본문에 merge가 있어도 태그로 인식한다
        assert parse_tag("[fix] merge conflict 해결") == "fix"

    def test_url_like_prefix_is_not_a_tag(self) -> None:
        # "https://..."의 https가 태그로 오인되지 않아야 한다
        assert parse_tag("https://example.com 참고해 수정") is None


class TestIsMergeTitle:
    def test_detects_merge_variants(self) -> None:
        assert is_merge_title("Merge branch 'a' into b")
        assert is_merge_title("merged release into develop")
        assert is_merge_title("Revert merge of feature/x")

    def test_regular_commit_is_not_merge(self) -> None:
        assert not is_merge_title("[feat] 기능 추가")


class TestTagDistribution:
    def test_merge_commits_excluded_from_population(self) -> None:
        titles = (
            "[feat] a",
            "[feat] b",
            "[fix] c",
            "자유 서술 d",
            "Merge branch 'x'",
            "Merge branch 'y'",
        )
        distribution = build_tag_distribution(titles)
        # merge 2건은 total에서 제외 → 모집단 4건, 인식 3건
        assert distribution.total == 4
        assert distribution.recognized == 3
        assert distribution.coverage == 0.75

    def test_counts_sorted_by_frequency_then_name(self) -> None:
        titles = ("[fix] a", "[feat] b", "[feat] c", "[docs] d")
        distribution = build_tag_distribution(titles)
        assert distribution.counts == (("feat", 2), ("docs", 1), ("fix", 1))

    def test_coverage_half(self) -> None:
        titles = ("[feat] a", "feat: b", "자유 c", "자유 d")
        distribution = build_tag_distribution(titles)
        assert distribution.coverage == 0.5

    def test_empty_titles_yield_zero_coverage(self) -> None:
        distribution = build_tag_distribution(())
        assert distribution.total == 0
        assert distribution.coverage == 0.0
        assert distribution.counts == ()

    def test_only_merge_commits_yield_zero_population(self) -> None:
        distribution = build_tag_distribution(("Merge branch 'a'", "Merge branch 'b'"))
        assert distribution.total == 0
        assert distribution.coverage == 0.0


class TestWeekStart:
    def test_monday_maps_to_itself(self) -> None:
        assert week_start_of(date(2026, 7, 27)) == date(2026, 7, 27)

    def test_sunday_maps_to_prior_monday(self) -> None:
        assert week_start_of(date(2026, 7, 26)) == date(2026, 7, 20)


class TestWeekFixRatios:
    def test_groups_by_week_and_counts_fix(self) -> None:
        dated_titles = (
            (date(2026, 7, 20), "[fix] a"),
            (date(2026, 7, 21), "[feat] b"),
            (date(2026, 7, 26), "[fix] c"),  # 같은 주(월 7/20)
            (date(2026, 7, 27), "[feat] d"),  # 다음 주
        )
        assert build_week_fix_ratios(dated_titles) == (
            ("2026-07-20", 2, 3),
            ("2026-07-27", 0, 1),
        )

    def test_unrecognized_titles_are_ignored(self) -> None:
        dated_titles = (
            (date(2026, 7, 20), "자유 서술"),
            (date(2026, 7, 20), "Merge branch 'x'"),
            (date(2026, 7, 20), "[fix] a"),
        )
        assert build_week_fix_ratios(dated_titles) == (("2026-07-20", 1, 1),)


class TestDetectFixSurge:
    def test_surge_detected(self) -> None:
        # 이전 3주 fix 약 10% → 최근 주 35%
        weeks = (
            ("2026-06-29", 1, 10),
            ("2026-07-06", 1, 10),
            ("2026-07-13", 1, 10),
            ("2026-07-20", 7, 20),
        )
        assert detect_fix_surge(weeks) is True

    def test_uniform_composition_is_not_a_surge(self) -> None:
        """기각된 가설의 실측 패턴 — 전 구간 균일하면 신호를 내지 않는다."""
        weeks = (
            ("2026-05-25", 4, 18),
            ("2026-06-01", 1, 11),
            ("2026-06-08", 5, 30),
            ("2026-06-15", 1, 11),
            ("2026-06-22", 5, 31),
            ("2026-07-20", 17, 50),
        )
        assert detect_fix_surge(weeks) is False

    def test_insufficient_history_returns_false(self) -> None:
        assert detect_fix_surge((("2026-07-20", 9, 10),)) is False
        assert detect_fix_surge((("2026-07-13", 0, 10), ("2026-07-20", 9, 10))) is False

    def test_small_latest_sample_returns_false(self) -> None:
        # 최근 주 표본이 하한 미만이면 비중이 높아도 신호를 내지 않는다
        weeks = (
            ("2026-07-06", 0, 10),
            ("2026-07-13", 0, 10),
            ("2026-07-20", 3, 3),
        )
        assert detect_fix_surge(weeks) is False

    def test_no_prior_recognized_commits_returns_false(self) -> None:
        weeks = (
            ("2026-07-06", 0, 0),
            ("2026-07-13", 0, 0),
            ("2026-07-20", 8, 10),
        )
        assert detect_fix_surge(weeks) is False

    def test_empty_input_returns_false(self) -> None:
        assert detect_fix_surge(()) is False
