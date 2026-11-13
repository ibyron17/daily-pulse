"""파이프라인 배선 테스트 — 해석된 값이 하류에 실제로 전달되는지 검증."""

import logging
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pulse.business_calendar import builtin_holiday_years
from pulse.collector.snapshot import BranchSnapshot
from pulse.collector.storage import save_raw_activity
from pulse.config import Config
from pulse.config.loader import HistoryConfig, LifecycleConfig
from pulse.lifecycle import (
    GroupLifecycleEntry,
    GroupLifecycleRegistry,
    StageTransition,
    load_registry,
    registry_path,
    save_registry,
)
from pulse.models import CommitInfo, RepoActivity
from pulse.pipeline import run_pipeline
from pulse.weekly_branches import weekly_created_branches
from tests.conftest import make_commit, make_merge_request, make_repo_activity, make_repo_ref

KST = ZoneInfo("Asia/Seoul")
# 내장 공휴일 표에 없는 해 — 표를 갱신해도 계속 「없는 해」가 되도록 마지막 해 다음 해로 잡는다
YEAR_MISSING_FROM_TABLE = max(builtin_holiday_years()) + 1
# 내장 공휴일 표가 담은 해 — 오래된 해를 표에서 정리해도 깨지지 않게 표의 마지막 해로 잡는다
YEAR_COVERED_BY_TABLE = max(builtin_holiday_years())
MONDAY_MORNING = datetime(2026, 7, 13, 8, 0, tzinfo=KST)  # 월요일 08:00 KST


def _make_config(tmp_path: Path) -> Config:
    """weekend_catchup이 켜진 최소 Config."""
    from pulse.config.loader import GroupingHints, StagnationThresholds
    from pulse.models import RepoRef

    return Config(
        team_name="테스트팀",
        repos=(
            RepoRef(
                provider="gitlab",
                base_url="http://test",
                namespace="test",
                name="repo",
                web_url="http://test/test/repo",
            ),
        ),
        lookback_hours=24,
        weekend_catchup=True,
        timezone_name="Asia/Seoul",
        output_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        stagnation=StagnationThresholds(review_waiting_days=3, no_push_days=7),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


def test_weekend_catchup_lookback_reaches_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """수집은 항상 168h, 일간 대시보드는 72h, 주간은 168h (G2)."""
    # Arrange
    config = _make_config(tmp_path)
    captured_lookback: list[int] = []

    def fake_collect(
        config: Config,
        now: datetime | None = None,
        save_snapshots: bool = True,
    ) -> list[RepoActivity]:
        captured_lookback.append(config.lookback_hours)
        return [make_repo_activity()]

    monkeypatch.setattr("pulse.pipeline.collect_repos", fake_collect)
    monkeypatch.setattr("pulse.pipeline.get_effective_now", lambda config: MONDAY_MORNING)

    # Act
    daily_dashboard, weekly_dashboard = run_pipeline(config)

    # Assert — 수집에 168h가 전달된다 (고정값), 하지만 일간 대시보드는 72h (G2)
    assert captured_lookback == [168]
    assert daily_dashboard.lookback_hours == 72
    assert weekly_dashboard.lookback_hours == 168


def test_weekday_lookback_stays_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """평일(수요일)에도 수집은 항상 168h이다."""
    # Arrange
    config = _make_config(tmp_path)
    wednesday = datetime(2026, 7, 15, 8, 0, tzinfo=KST)
    captured_lookback: list[int] = []

    def fake_collect(
        config: Config,
        now: datetime | None = None,
        save_snapshots: bool = True,
    ) -> list[RepoActivity]:
        captured_lookback.append(config.lookback_hours)
        return [make_repo_activity()]

    monkeypatch.setattr("pulse.pipeline.collect_repos", fake_collect)
    monkeypatch.setattr("pulse.pipeline.get_effective_now", lambda config: wednesday)

    # Act
    daily_dashboard, weekly_dashboard = run_pipeline(config)

    # Assert — 평일에도 수집은 168h, 하지만 일간 대시보드는 24h (G2)
    assert captured_lookback == [168]
    assert daily_dashboard.lookback_hours == 24
    assert weekly_dashboard.lookback_hours == 168


def _capture_collection_width(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """collect_repos 가 받은 수집 폭을 기록하는 스텁을 건다."""
    captured_lookback: list[int] = []

    def fake_collect(
        config: Config,
        now: datetime | None = None,
        save_snapshots: bool = True,
    ) -> list[RepoActivity]:
        captured_lookback.append(config.lookback_hours)
        return [make_repo_activity()]

    monkeypatch.setattr("pulse.pipeline.collect_repos", fake_collect)
    return captured_lookback


def test_collection_width_widens_when_daily_window_exceeds_168h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """일간이 168h를 넘으면 수집 폭이 일간을 따라간다 — 주간 모델은 168h 그대로."""
    # Arrange — 7/13(월)~7/22(수) 사이 평일을 전부 휴무로 만들어 일간 9일(216h).
    # 내장 표의 내용(7/17 제헌절 포함 여부)에 기대지 않도록 평일 휴무를 전부 명시한다
    # (내장 표와의 합집합이라 이미 표에 있어도 무해)
    extra_holidays = tuple(date(2026, 7, day) for day in (14, 15, 16, 17, 20, 21))
    config = replace(_make_config(tmp_path), extra_holidays=extra_holidays)
    captured_lookback = _capture_collection_width(monkeypatch)
    now = datetime(2026, 7, 22, 0, 0, tzinfo=KST)

    # Act
    daily_dashboard, weekly_dashboard = run_pipeline(config, now)

    # Assert
    assert captured_lookback == [216]
    assert daily_dashboard.lookback_hours == 216
    assert weekly_dashboard.lookback_hours == 168


def test_collection_width_stays_168_when_daily_window_is_shorter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """일간이 168h 이하면 수집 폭은 168h 고정 (96h여도 늘어나지 않는다)."""
    # 10/6 일간 96h 는 10/5 대체공휴일 때문이다 — 내장 표에 기대지 않고 명시한다
    config = replace(_make_config(tmp_path), extra_holidays=(date(2026, 10, 5),))
    captured_lookback = _capture_collection_width(monkeypatch)

    daily_dashboard, _ = run_pipeline(config, datetime(2026, 10, 6, 0, 0, tzinfo=KST))

    assert captured_lookback == [168]
    assert daily_dashboard.lookback_hours == 96


def test_warns_when_year_is_missing_from_holiday_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """표에 없는 해에 실행하면 실행 로그에 경고가 남는다 (조용히 틀리지 않게)."""
    _capture_collection_width(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="pulse.pipeline"):
        run_pipeline(
            _make_config(tmp_path), datetime(YEAR_MISSING_FROM_TABLE, 1, 2, 0, 0, tzinfo=KST)
        )

    assert any(str(YEAR_MISSING_FROM_TABLE) in record.getMessage() for record in caplog.records)


def test_no_calendar_warning_when_year_is_covered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """표가 있는 해에는 달력 경고가 없다."""
    _capture_collection_width(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="pulse.pipeline"):
        run_pipeline(
            _make_config(tmp_path), datetime(YEAR_COVERED_BY_TABLE, 7, 21, 0, 0, tzinfo=KST)
        )

    assert not any("공휴일" in record.getMessage() for record in caplog.records)


def test_no_calendar_warning_when_catchup_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """weekend_catchup=False 면 공휴일 표를 쓰지 않으므로 표 경고도 없다."""
    config = replace(_make_config(tmp_path), weekend_catchup=False)
    _capture_collection_width(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="pulse.pipeline"):
        run_pipeline(config, datetime(YEAR_MISSING_FROM_TABLE, 1, 2, 0, 0, tzinfo=KST))

    assert not any(str(YEAR_MISSING_FROM_TABLE) in record.getMessage() for record in caplog.records)


def test_warns_when_holidays_run_to_the_catchup_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """휴무일이 14일 넘게 이어지면 휴무일 목록을 확인하라는 경고가 남는다."""
    start = date(2026, 11, 16)  # 월요일, 내장 표에 공휴일 없는 구간
    extra_holidays = tuple(date.fromordinal(start.toordinal() + offset) for offset in range(20))
    config = replace(_make_config(tmp_path), extra_holidays=extra_holidays)
    captured_lookback = _capture_collection_width(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="pulse.pipeline"):
        run_pipeline(config, datetime(2026, 12, 7, 0, 0, tzinfo=KST))

    assert any("연속" in record.getMessage() for record in caplog.records)
    assert captured_lookback == [336]  # 14일 상한 = 336h


class TestDiffPreviousWindowIsNotWidenedByTodaysWidth:
    """diff 의 이전 raw 창은 그 수집 시점의 규칙값이어야 한다 — 오늘 폭이 하한으로 새면 안 된다.

    resolve_lookback_hours 는 lookback_hours 를 하한으로 쓴다. run_pipeline 이 오늘 폭으로
    덮은 daily_config 를 diff 에 넘기면 이전 창이 오늘 폭 이상으로 부풀어, 이전 창 밖의 옛 커밋이
    이전 그룹을 만들고 오늘 그룹이 「신규」로 잡히지 않는다.
    """

    BRANCH = "feature/payment"
    GROUP_NAME = "payment"  # 브랜치 접두어(feature/)를 뗀 그룹 이름

    @staticmethod
    def _activity(commit_at: datetime, collected_at: datetime) -> RepoActivity:
        commit = make_commit(
            sha=f"sha-{commit_at.isoformat()}",
            authored_at=commit_at,
            branch=TestDiffPreviousWindowIsNotWidenedByTodaysWidth.BRANCH,
        )
        return make_repo_activity(
            commits=(commit,),
            active_branches=(),
            merge_requests=(),
            collected_at=collected_at,
        )

    @pytest.mark.parametrize(
        ("today", "previous_collected", "old_commit_at", "today_commit_at"),
        [
            pytest.param(
                datetime(2026, 10, 6, 0, 0, tzinfo=KST),  # 일간 96h (10/2~10/5)
                datetime(2026, 10, 3, 0, 0, tzinfo=KST),  # 이전 창은 24h (10/2)
                datetime(2026, 9, 30, 10, 0, tzinfo=KST),
                datetime(2026, 10, 5, 10, 0, tzinfo=KST),
                id="10/6 화: 이전 raw 10/3 은 24h",
            ),
            pytest.param(
                datetime(2026, 10, 12, 0, 0, tzinfo=KST),  # 일간 96h (10/8~10/11)
                datetime(2026, 10, 11, 0, 0, tzinfo=KST),  # 이전 창은 72h (10/8~10/10)
                datetime(2026, 10, 7, 10, 0, tzinfo=KST),
                datetime(2026, 10, 10, 10, 0, tzinfo=KST),
                id="10/12 월: 이전 raw 10/11 은 72h",
            ),
        ],
    )
    def test_group_active_only_before_previous_window_is_reported_as_new(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        today: datetime,
        previous_collected: datetime,
        old_commit_at: datetime,
        today_commit_at: datetime,
    ) -> None:
        # Arrange — 이전 raw 에는 이전 창 밖 커밋만, 오늘 창에는 같은 브랜치의 새 커밋이 있다
        config = replace(
            _make_config(tmp_path),
            history=HistoryConfig(enabled=False),
            lifecycle=LifecycleConfig(enabled=False),
            # 두 케이스의 오늘 폭(96h)이 10/5 대체공휴일·10/9 한글날 때문임을
            # 내장 표에 기대지 않고 명시한다
            extra_holidays=(date(2026, 10, 5), date(2026, 10, 9)),
        )
        save_raw_activity(
            self._activity(old_commit_at, previous_collected), config.data_dir / "raw"
        )
        todays_activity = self._activity(today_commit_at, today)
        monkeypatch.setattr(
            "pulse.pipeline.collect_repos",
            lambda config, now=None, save_snapshots=True: [todays_activity],
        )

        # Act
        daily_dashboard, _ = run_pipeline(config, today)

        # Assert — 옛 커밋은 이전 창 밖이라 이전 그룹이 비고, 오늘 그룹은 신규다
        assert daily_dashboard.diff is not None
        new_group_names = [name for _repo, name in daily_dashboard.diff.new_groups]
        assert new_group_names == [self.GROUP_NAME]


class TestWeeklyCreatedBranches:
    """주간 신규 브랜치: 끝 스냅샷(창 끝 날짜 이후 가장 이른 것)과 기준 스냅샷 비교."""

    REPORT_DATE = date(2026, 10, 5)
    BASELINE_DATE = date(2026, 9, 28)

    @staticmethod
    def _save(config: Config, snapshot_date: date, slug: str, branches: set[str]) -> None:
        BranchSnapshot(slug, branches, snapshot_date.isoformat()).save(
            config.data_dir / "snapshots"
        )

    def _run(self, config: Config, baseline_dates: dict[str, date]) -> tuple[RepoActivity, ...]:
        activities = (make_repo_activity(),)
        return weekly_created_branches(config, activities, self.REPORT_DATE, baseline_dates)

    def test_uses_report_date_snapshot_when_present(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        slug = make_repo_activity().repo.slug
        self._save(config, self.BASELINE_DATE, slug, {"main"})
        self._save(config, self.REPORT_DATE, slug, {"main", "feature/a"})
        self._save(config, date(2026, 10, 6), slug, {"main", "feature/a", "feature/b"})

        result = self._run(config, {slug: self.BASELINE_DATE})

        assert result[0].created_branches == ("feature/a",)

    def test_falls_back_to_next_snapshot_when_report_date_has_none(self, tmp_path: Path) -> None:
        """월요일 실행이 빠진 주는 그날 스냅샷이 없다 — 이후 가장 이른 스냅샷을 쓴다."""
        config = _make_config(tmp_path)
        slug = make_repo_activity().repo.slug
        self._save(config, self.BASELINE_DATE, slug, {"main"})
        self._save(config, date(2026, 10, 6), slug, {"main", "feature/b", "feature/a"})
        self._save(config, date(2026, 10, 7), slug, {"main", "feature/c"})

        result = self._run(config, {slug: self.BASELINE_DATE})

        assert result[0].created_branches == ("feature/a", "feature/b")

    def test_empty_when_no_end_snapshot_exists(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        slug = make_repo_activity().repo.slug
        self._save(config, self.BASELINE_DATE, slug, {"main"})
        self._save(config, date(2026, 10, 3), slug, {"main", "feature/old"})  # report_date 이전

        result = self._run(config, {slug: self.BASELINE_DATE})

        assert result[0].created_branches == ()

    def test_empty_when_repo_has_no_baseline(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        slug = make_repo_activity().repo.slug
        self._save(config, self.REPORT_DATE, slug, {"main", "feature/a"})

        result = self._run(config, {})

        assert result[0].created_branches == ()

    def test_corrupt_snapshot_degrades_to_empty_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _make_config(tmp_path)
        slug = make_repo_activity().repo.slug
        self._save(config, self.BASELINE_DATE, slug, {"main"})
        corrupt_dir = config.data_dir / "snapshots" / self.REPORT_DATE.isoformat()
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / f"{slug}.json").write_text("{not json")

        with caplog.at_level(logging.WARNING, logger="pulse.weekly_branches"):
            result = self._run(config, {slug: self.BASELINE_DATE})

        assert result[0].created_branches == ()
        assert any("스냅샷 비교 실패" in record.getMessage() for record in caplog.records)


class TestWeeklyWindowEndIsSeparatedFromRunDate:
    """발행 주간의 창 끝(weekly_window_end)만 따로 받고, 운영 상태는 실행일(now)에 남는다.

    화요일(10/6) 보완 발행: 이름표·등록부·일간 스파크라인·오늘 스냅샷은 10/6 에 묶이고,
    주간 대시보드의 창만 지난주 월~일(9/28~10/5)이다. 10/5 는 대체공휴일이라 일간은 96h 다.
    """

    TUESDAY = datetime(2026, 10, 6, 0, 0, tzinfo=KST)
    HOLIDAY_MONDAY = datetime(2026, 10, 5, 0, 0, tzinfo=KST)
    NEXT_MONDAY = datetime(2026, 10, 12, 0, 0, tzinfo=KST)
    REPO_PATH = make_repo_activity().repo.full_path

    def _config(self, tmp_path: Path) -> Config:
        """이력·수명주기를 끈 설정 — 개천절 대체공휴일(10/5 월)을 내장 표에 기대지 않고 명시한다.

        설정 레포를 활동 레포와 맞춘다 — 기준 스냅샷은 설정의 레포 slug 로 찾는다.
        """
        return replace(
            _make_config(tmp_path),
            repos=(make_repo_ref(),),
            history=HistoryConfig(enabled=False),
            lifecycle=LifecycleConfig(enabled=False),
            extra_holidays=(date(2026, 10, 5),),
        )

    @staticmethod
    def _commit_on_branch(name: str, authored_at: datetime) -> CommitInfo:
        return make_commit(
            sha=f"sha-{name}",
            authored_at=authored_at,
            branch=f"feature/{name}",
            message=f"feat: {name} 작업",
            changed_files=(f"src/{name}/index.ts",),
        )

    def _activity(self) -> RepoActivity:
        """a: 9/28(창 안), c: 10/2, b: 10/5(주간 창 끝 이후 — 일간 창에는 들어간다)."""
        commits = (
            self._commit_on_branch("a", datetime(2026, 9, 28, 10, 0, tzinfo=KST)),
            self._commit_on_branch("c", datetime(2026, 10, 2, 10, 0, tzinfo=KST)),
            self._commit_on_branch("b", datetime(2026, 10, 5, 10, 0, tzinfo=KST)),
        )
        return make_repo_activity(
            commits=commits,
            active_branches=(),
            merge_requests=(),
            collected_at=self.TUESDAY,
        )

    def _stub_collection(
        self, monkeypatch: pytest.MonkeyPatch, activity: RepoActivity | None = None
    ) -> list[int]:
        """collect_repos 를 스텁으로 바꾸고 받은 수집 폭을 기록한다 (activity 생략 시 기본 활동)."""
        widths: list[int] = []
        collected = activity or self._activity()

        def fake_collect(
            config: Config, now: datetime | None = None, save_snapshots: bool = True
        ) -> list[RepoActivity]:
            widths.append(config.lookback_hours)
            return [collected]

        monkeypatch.setattr("pulse.pipeline.collect_repos", fake_collect)
        return widths

    @staticmethod
    def _group_names(model: object) -> set[str]:
        return {group.name for group in model.groups}  # type: ignore[attr-defined]

    def test_make_up_window_regroups_weekly_and_widens_collection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P1: 창 9/28~10/5·이름표 10/6, 일간은 롤링 그대로(b 스파크라인 포함), 수집 폭 192."""
        widths = self._stub_collection(monkeypatch)

        daily, weekly = run_pipeline(
            self._config(tmp_path), self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY
        )

        assert widths == [192]  # 168 + (10/6 00:00 − 10/5 00:00)
        assert weekly.window_start == datetime(2026, 9, 28, 0, 0, tzinfo=KST)
        assert weekly.window_end == self.HOLIDAY_MONDAY
        assert weekly.report_date == date(2026, 10, 6)
        assert self._group_names(weekly) >= {"a", "c"}
        assert "b" not in self._group_names(weekly)
        assert daily.lookback_hours == 96
        assert self._group_names(daily) >= {"b", "c"}
        assert "a" not in self._group_names(daily)
        daily_b = next(group for group in daily.groups if group.name == "b")
        assert ("2026-10-05", 1) in daily_b.daily_commit_counts

    def test_monday_midnight_publish_is_identical_with_or_without_explicit_window_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P2: 창 끝이 now 와 같으면(월 00:00 발행) 재그룹핑 없이 지금과 같은 결과다."""
        widths = self._stub_collection(monkeypatch)

        default_daily, default_weekly = run_pipeline(
            self._config(tmp_path / "default"), self.NEXT_MONDAY
        )
        aligned_daily, aligned_weekly = run_pipeline(
            self._config(tmp_path / "aligned"),
            self.NEXT_MONDAY,
            weekly_window_end=self.NEXT_MONDAY,
        )

        assert widths == [168, 168]
        assert aligned_weekly == default_weekly
        assert aligned_daily == default_daily

    def test_collection_width_is_rounded_up_to_whole_hours(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P3: 화 14:30 수동 실행 — 38.5h 는 39h 로 올림해야 지난주 월 00:00 이 수집에 든다."""
        widths = self._stub_collection(monkeypatch)

        run_pipeline(
            self._config(tmp_path),
            datetime(2026, 10, 6, 14, 30, tzinfo=KST),
            weekly_window_end=self.HOLIDAY_MONDAY,
        )

        assert widths == [207]  # 168 + ceil(38.5)

    def test_weekly_new_branches_are_compared_at_window_end_not_run_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P4: 신규 브랜치는 창 끝(10/5) 스냅샷 기준 — 10/6 스냅샷의 b 는 지난주 신규가 아니다."""
        self._stub_collection(monkeypatch)
        config = self._config(tmp_path)
        slug = make_repo_activity().repo.slug
        for snapshot_date, branches in (
            (date(2026, 9, 28), {"main"}),
            (date(2026, 10, 5), {"main", "feature/a"}),
            (date(2026, 10, 6), {"main", "feature/a", "feature/b"}),
        ):
            BranchSnapshot(slug, branches, snapshot_date.isoformat()).save(
                config.data_dir / "snapshots"
            )

        _, weekly = run_pipeline(config, self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY)

        new_branches = {
            signal.branch_or_mr
            for signal in weekly.new_work
            if not signal.branch_or_mr.startswith("!")
        }
        assert new_branches == {"feature/a"}

    def test_lifecycle_days_follow_run_date_and_registry_follows_rolling_groups(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P5: 진행 N일은 이름표(10/6) 기준, 등록부는 실행일 롤링 그룹으로 갱신된다."""
        self._stub_collection(monkeypatch)
        config = replace(self._config(tmp_path), lifecycle=LifecycleConfig(enabled=True))
        seeded_key = f"{self.REPO_PATH}::a"
        seeded_entry = GroupLifecycleEntry(
            first_seen=date(2026, 10, 1),
            last_seen=date(2026, 10, 1),
            stage_history=(StageTransition(stage="developing", entered_at=date(2026, 10, 1)),),
            date_commit_counts=(),
            group_kind="feature",
        )
        save_registry(
            GroupLifecycleRegistry(
                schema_version=1,
                updated_at=self.TUESDAY,
                groups=((seeded_key, seeded_entry),),
            ),
            registry_path(config.data_dir),
        )

        _, weekly = run_pipeline(config, self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY)

        weekly_a = next(group for group in weekly.groups if group.name == "a")
        assert weekly_a.lifecycle is not None
        assert weekly_a.lifecycle.total_days == 6  # 10/1~10/6 (창 끝 10/5 기준이면 5)
        saved = dict(load_registry(registry_path(config.data_dir)).groups)
        assert saved[f"{self.REPO_PATH}::b"].last_seen == date(2026, 10, 6)  # b 는 주간 창 밖

    def test_weekly_histogram_ends_at_window_end_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """P6: 주간 막대는 창 끝 날짜(10/5)까지 7일 — 이름표(10/6)를 끝으로 쓰면 창 밖이 섞인다."""
        self._stub_collection(monkeypatch)

        _, weekly = run_pipeline(
            self._config(tmp_path), self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY
        )

        weekly_c = next(group for group in weekly.groups if group.name == "c")
        assert weekly_c.daily_commit_counts[-1][0] == "2026-10-05"
        assert ("2026-10-02", 1) in weekly_c.daily_commit_counts

    def test_weekly_new_mr_signal_is_judged_at_window_end_not_run_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """신규 MR 은 창 끝(10/5) 기준 168h 이내 — 실행일(10/6) 기준이면 182h 라 빠진다."""
        merge_request = make_merge_request(
            iid=77, created_at=datetime(2026, 9, 28, 10, 0, tzinfo=KST)
        )  # 창 끝 기준 158h, 실행일 기준 182h
        self._stub_collection(
            monkeypatch, replace(self._activity(), merge_requests=(merge_request,))
        )

        _, weekly = run_pipeline(
            self._config(tmp_path), self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY
        )

        assert "!77" in {signal.branch_or_mr for signal in weekly.new_work}

    def test_weekly_stagnation_is_judged_at_window_end_not_run_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """정체 경고의 기준 시각도 창 끝 — 10/2 12:00 이후 갱신 없는 MR 은 창 끝 2일, 실행일 3일."""
        stale_candidate = make_merge_request(
            iid=78,
            created_at=datetime(2026, 9, 29, 10, 0, tzinfo=KST),
            updated_at=datetime(2026, 10, 2, 12, 0, tzinfo=KST),
        )  # 정체 임계 3일(_make_config): 창 끝 기준 2일 12시간, 실행일 기준 3일 12시간
        self._stub_collection(
            monkeypatch, replace(self._activity(), merge_requests=(stale_candidate,))
        )

        daily, weekly = run_pipeline(
            self._config(tmp_path), self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY
        )

        assert "stale_mr" in {warning.kind for warning in daily.warnings}  # 실행일 기준이면 경고
        assert "stale_mr" not in {warning.kind for warning in weekly.warnings}

    def test_weekly_warnings_come_from_the_window_not_from_rolling_groups(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """창 밖(10/5 10:00)의 Revert 커밋 경고는 주간에 남지 않는다 — 일간(롤링)에는 남는다."""
        activity = self._activity()
        reverted_commits = tuple(
            replace(commit, message='Revert "feat: b 작업"') if commit.sha == "sha-b" else commit
            for commit in activity.commits
        )
        self._stub_collection(monkeypatch, replace(activity, commits=reverted_commits))

        daily, weekly = run_pipeline(
            self._config(tmp_path), self.TUESDAY, weekly_window_end=self.HOLIDAY_MONDAY
        )

        assert "revert_commit" in {warning.kind for warning in daily.warnings}
        assert weekly.warnings == ()
