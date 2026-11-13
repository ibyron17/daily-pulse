"""Renderer assemble 라운드 5 확장 테스트: histogram, generated_at, 조인."""

from datetime import date, datetime
from pathlib import Path

from pulse.config.loader import Config, GroupingHints, StagnationThresholds
from pulse.grouper.signals import commit_histogram_by_date
from pulse.models import CommitInfo, FeatureGroup
from pulse.renderer.assemble import build_dashboard_model


class TestCommitHistogram:
    """commit_histogram_by_date 테스트."""

    def test_commit_histogram_by_date_7day_window(self) -> None:
        """7일 윈도우."""
        commits = (
            CommitInfo(
                sha="abc",
                author_name="user",
                authored_at=datetime(2024, 1, 1, 10, 0),
                message="Commit",
                branch="main",
                changed_files=(),
                web_url="",
            ),
            CommitInfo(
                sha="def",
                author_name="user",
                authored_at=datetime(2024, 1, 3, 10, 0),
                message="Commit",
                branch="main",
                changed_files=(),
                web_url="",
            ),
        )
        histogram = commit_histogram_by_date(commits, 7, date(2024, 1, 7))
        assert len(histogram) == 7
        # 과거→최신 순서 확인
        assert histogram[0][0] == "2024-01-01"
        assert histogram[-1][0] == "2024-01-07"

    def test_commit_histogram_excludes_merge_commits(self) -> None:
        """머지 커밋 제외."""
        commits = (
            CommitInfo(
                sha="abc",
                author_name="user",
                authored_at=datetime(2024, 1, 1, 10, 0),
                message="Merge branch 'develop'",
                branch="main",
                changed_files=(),
                web_url="",
            ),
            CommitInfo(
                sha="def",
                author_name="user",
                authored_at=datetime(2024, 1, 1, 11, 0),
                message="Regular commit",
                branch="main",
                changed_files=(),
                web_url="",
            ),
        )
        histogram = commit_histogram_by_date(commits, 1, date(2024, 1, 1))
        # 1건만 카운트 (머지 커밋 제외)
        assert histogram[0][1] == 1

    def test_commit_histogram_zero_days_included(self) -> None:
        """활동 없는 날도 0으로 포함."""
        commits = (
            CommitInfo(
                sha="abc",
                author_name="user",
                authored_at=datetime(2024, 1, 1, 10, 0),
                message="Commit",
                branch="main",
                changed_files=(),
                web_url="",
            ),
        )
        histogram = commit_histogram_by_date(commits, 3, date(2024, 1, 3))
        # 3일 모두 포함
        assert len(histogram) == 3
        # 1월2일은 0
        assert histogram[1][1] == 0


class TestGeneratedAt:
    """generated_at 필드 테스트."""

    def test_build_dashboard_model_sets_generated_at(self) -> None:
        """generated_at이 now 값으로 설정됨."""
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        now = datetime(2024, 1, 1, 12, 0, 0)
        config = Config(
            team_name="Test",
            repos=(),
            lookback_hours=24,
            weekend_catchup=True,
            timezone_name="UTC",
            output_dir=Path("."),
            data_dir=Path("."),
            stagnation=StagnationThresholds(),
            exclude_bot_authors=(),
            retention_days=90,
            grouping_hints=GroupingHints(),
        )
        model = build_dashboard_model(
            groups=(group,),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=config,
            report_date=date(2024, 1, 1),
            now=now,
            period="daily",
        )
        assert model.generated_at == now


class TestHistogramJoin:
    """히스토그램 조인 테스트."""

    def test_daily_groups_join_weekly_histogram(self) -> None:
        """daily는 맵에서 조인."""
        weekly_histogram = tuple((f"2024-01-0{i}", i) for i in range(1, 8))
        weekly_histogram_map = {("org/repo", "Test"): weekly_histogram}
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        config = Config(
            team_name="Test",
            repos=(),
            lookback_hours=24,
            weekend_catchup=True,
            timezone_name="UTC",
            output_dir=Path("."),
            data_dir=Path("."),
            stagnation=StagnationThresholds(),
            exclude_bot_authors=(),
            retention_days=90,
            grouping_hints=GroupingHints(),
        )
        model = build_dashboard_model(
            groups=(group,),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=config,
            report_date=date(2024, 1, 7),
            now=datetime(2024, 1, 7),
            period="daily",
            weekly_histogram_map=weekly_histogram_map,
        )
        assert model.groups[0].daily_commit_counts == weekly_histogram

    def test_daily_group_without_weekly_match_empty_histogram(self) -> None:
        """daily에 매칭이 없으면 빈 히스토그램."""
        group = FeatureGroup(
            name="Test",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        )
        config = Config(
            team_name="Test",
            repos=(),
            lookback_hours=24,
            weekend_catchup=True,
            timezone_name="UTC",
            output_dir=Path("."),
            data_dir=Path("."),
            stagnation=StagnationThresholds(),
            exclude_bot_authors=(),
            retention_days=90,
            grouping_hints=GroupingHints(),
        )
        model = build_dashboard_model(
            groups=(group,),
            warnings=(),
            new_work=(),
            unclassified_ratio=0.0,
            activities=(),
            config=config,
            report_date=date(2024, 1, 7),
            now=datetime(2024, 1, 7),
            period="daily",
            weekly_histogram_map={},
        )
        assert model.groups[0].daily_commit_counts == ()
