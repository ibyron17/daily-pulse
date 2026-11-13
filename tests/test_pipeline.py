"""파이프라인 E2E 시나리오 테스트 (8개 케이스)."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from pulse.business_calendar import builtin_holiday_years
from pulse.config import Config, GroupingHints, StagnationThresholds
from pulse.models import (
    CommitInfo,
    RepoActivity,
    RepoRef,
)
from pulse.pipeline import (
    find_previous_raw_dir,
    get_effective_now,
    has_full_collection,
    load_previous_activities,
    resolve_lookback_hours,
)


@pytest.fixture
def base_config(tmp_path: Path) -> Config:
    """기본 설정."""
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
        stagnation=StagnationThresholds(
            review_waiting_days=3,
            no_push_days=7,
        ),
        exclude_bot_authors=(),
        retention_days=90,
        grouping_hints=GroupingHints(),
    )


@pytest.fixture
def base_activity() -> RepoActivity:
    """기본 활동."""
    return RepoActivity(
        repo=RepoRef(
            provider="gitlab",
            base_url="http://test",
            namespace="test",
            name="repo",
            web_url="http://test/test/repo",
        ),
        status="ok",
        failure_reason=None,
        commits=(
            CommitInfo(
                sha="abc123",
                author_name="alice",
                authored_at=datetime.now(tz=timezone.utc),
                message="test commit",
                branch="main",
                changed_files=("file.py",),
                web_url="http://test/commit",
            ),
        ),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=datetime.now(tz=timezone.utc),
    )


def test_get_effective_now_seoul_timezone(base_config: Config) -> None:
    """현재 시간을 Seoul 타임존으로 계산."""
    now = get_effective_now(base_config)

    assert now.tzinfo is not None
    # Seoul TZ는 UTC+9
    assert now.utcoffset() == timedelta(hours=9)


def test_resolve_lookback_hours_weekday(base_config: Config) -> None:
    """평일: 24시간."""
    # 화요일 오후 2시 설정
    wednesday = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)

    with patch("pulse.pipeline.get_effective_now", return_value=wednesday):
        hours = resolve_lookback_hours(base_config, wednesday)

    assert hours == 24


def test_resolve_lookback_hours_monday(base_config: Config) -> None:
    """월요일: 72시간."""
    # 월요일 오전 9시 설정 (2026-07-13은 월요일)
    monday = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)

    with patch("pulse.pipeline.get_effective_now", return_value=monday):
        hours = resolve_lookback_hours(base_config, monday)

    assert hours == 72


def test_find_previous_raw_dir_exists(tmp_path: Path) -> None:
    """이전 raw 디렉토리 찾기."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    # 3개 날짜의 디렉토리 생성
    (raw_dir / "2026-07-13").mkdir()
    (raw_dir / "2026-07-14").mkdir()
    (raw_dir / "2026-07-15").mkdir()

    today = date(2026, 7, 16)
    result = find_previous_raw_dir(tmp_path / "data", today)

    assert result is not None
    prev_date, prev_path = result
    assert prev_date == date(2026, 7, 15)
    assert prev_path == raw_dir / "2026-07-15"


def test_find_previous_raw_dir_weekend_gap(tmp_path: Path) -> None:
    """주말 공백: 월요일에 금요일 데이터 반환."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    # 금요일 데이터만 있음
    (raw_dir / "2026-07-10").mkdir()

    today = date(2026, 7, 13)  # 월요일
    result = find_previous_raw_dir(raw_dir.parent, today)

    assert result is not None
    prev_date, prev_path = result
    assert prev_date == date(2026, 7, 10)


def test_find_previous_raw_dir_none(tmp_path: Path) -> None:
    """이전 데이터 없음."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    today = date(2026, 7, 15)
    result = find_previous_raw_dir(tmp_path / "data", today)

    assert result is None


def test_load_previous_activities(tmp_path: Path) -> None:
    """이전 활동 로드 — 저장 후 로드해서 일치하는지 확인."""
    from pulse.collector.storage import save_raw_activity

    # 2026-07-15 시간대의 활동 생성
    activity = RepoActivity(
        repo=RepoRef(
            provider="gitlab",
            base_url="http://test",
            namespace="test",
            name="repo",
            web_url="http://test/test/repo",
        ),
        status="ok",
        failure_reason=None,
        commits=(
            CommitInfo(
                sha="abc123",
                author_name="alice",
                authored_at=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
                message="test commit",
                branch="main",
                changed_files=("file.py",),
                web_url="http://test/commit",
            ),
        ),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
    )

    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)

    # 활동 저장
    save_raw_activity(activity, raw_dir)

    # 저장된 파일이 올바르게 로드되는지 확인
    date_dir = raw_dir / "2026-07-15"
    activities = load_previous_activities(date_dir)

    # 저장한 활동이 올바르게 로드되었는지 확인
    assert len(activities) == 1
    loaded = activities[0]
    assert loaded.repo == activity.repo
    assert loaded.status == activity.status
    assert len(loaded.commits) == len(activity.commits)


def test_has_full_collection_all_ok(base_activity: RepoActivity) -> None:
    """모든 활동이 성공."""
    activities = (base_activity,)

    assert has_full_collection(activities) is True


def test_has_full_collection_partial_failure(
    base_activity: RepoActivity,
) -> None:
    """일부 활동이 실패."""
    failed_activity = RepoActivity(
        repo=base_activity.repo,
        status="failed",
        failure_reason="Network error",
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=base_activity.collected_at,
    )
    activities = (base_activity, failed_activity)

    assert has_full_collection(activities) is False


@pytest.mark.parametrize("weekend_catchup,expected", [(True, 72), (False, 24)])
def test_resolve_lookback_hours_weekend_catchup_config(
    base_config: Config,
    weekend_catchup: bool,
    expected: int,
) -> None:
    """weekend_catchup 설정 확인 (월요일)."""
    config = Config(
        team_name=base_config.team_name,
        repos=base_config.repos,
        lookback_hours=base_config.lookback_hours,
        weekend_catchup=weekend_catchup,
        timezone_name="Asia/Seoul",
        output_dir=base_config.output_dir,
        data_dir=base_config.data_dir,
        stagnation=base_config.stagnation,
        exclude_bot_authors=base_config.exclude_bot_authors,
        retention_days=base_config.retention_days,
        grouping_hints=base_config.grouping_hints,
    )

    monday = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)

    with patch("pulse.pipeline.get_effective_now", return_value=monday):
        hours = resolve_lookback_hours(config, monday)

    assert hours == expected


KST = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("now", "expected_hours"),
    [
        pytest.param(datetime(2026, 7, 15, 0, 0, tzinfo=KST), 24, id="평일(수) 24h"),
        pytest.param(datetime(2026, 7, 13, 0, 0, tzinfo=KST), 72, id="월요일 72h(금~일)"),
        pytest.param(datetime(2026, 10, 6, 0, 0, tzinfo=KST), 96, id="10/6 화: 10/2~10/5 96h"),
        pytest.param(datetime(2026, 10, 4, 0, 0, tzinfo=KST), 48, id="일요일 48h(금·토)"),
        pytest.param(datetime(2026, 10, 3, 0, 0, tzinfo=KST), 24, id="토요일 24h(금)"),
        pytest.param(datetime(2026, 10, 5, 0, 0, tzinfo=KST), 72, id="공휴일 월요일 당일 72h"),
        pytest.param(datetime(2026, 9, 28, 0, 0, tzinfo=KST), 120, id="추석 뒤 월요일 120h"),
        pytest.param(
            datetime(2026, 10, 12, 0, 0, tzinfo=KST), 96, id="공휴일 금요일 뒤 월요일 96h"
        ),
        pytest.param(
            datetime(2026, 10, 6, 14, 0, tzinfo=KST), 96, id="시각 있는 수동 실행도 일수x24"
        ),
        pytest.param(
            datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc), 96, id="UTC 입력은 KST 날짜로 판정"
        ),
    ],
)
def test_resolve_lookback_hours_business_day_rule(
    base_config: Config, now: datetime, expected_hours: int
) -> None:
    """일간 폭 = 직전 영업일의 같은 시각부터 now까지 (PRP §11 결정표)."""
    assert resolve_lookback_hours(base_config, now) == expected_hours


def test_resolve_lookback_hours_keeps_larger_configured_value(base_config: Config) -> None:
    """lookback_hours는 하한이다 — 평상 화요일에 48을 설정하면 48."""
    config = replace(base_config, lookback_hours=48)

    assert resolve_lookback_hours(config, datetime(2026, 7, 14, 0, 0, tzinfo=KST)) == 48


def test_resolve_lookback_hours_larger_setting_is_not_shrunk_on_monday(
    base_config: Config,
) -> None:
    """lookback_hours=96 설정이 월요일에 72로 줄던 기존 어색함이 사라진다."""
    config = replace(base_config, lookback_hours=96)

    assert resolve_lookback_hours(config, datetime(2026, 7, 13, 0, 0, tzinfo=KST)) == 96


def test_resolve_lookback_hours_ignores_holidays_when_catchup_is_off(base_config: Config) -> None:
    """weekend_catchup=False 면 공휴일 다음 날에도 설정값 그대로."""
    config = replace(base_config, weekend_catchup=False)

    assert resolve_lookback_hours(config, datetime(2026, 10, 6, 0, 0, tzinfo=KST)) == 24


def test_resolve_lookback_hours_counts_extra_holidays(base_config: Config) -> None:
    """config.extra_holidays(회사 휴무)도 영업일에서 빠진다."""
    # 10/5 대체공휴일은 내장 표에 기대지 않고 명시한다 (합집합이라 무해).
    # 이 테스트의 관심사는 10/2 추가분이다
    config = replace(base_config, extra_holidays=(date(2026, 10, 2), date(2026, 10, 5)))

    assert resolve_lookback_hours(config, datetime(2026, 10, 6, 0, 0, tzinfo=KST)) == 120


def test_resolve_lookback_hours_uses_config_timezone_not_input_timezone(
    base_config: Config,
) -> None:
    """같은 순간이면 입력 시간대와 무관하게 config 시간대의 날짜로 판정한다."""
    config = replace(base_config, timezone_name="Asia/Tokyo")
    instant_kst = datetime(2026, 10, 6, 0, 0, tzinfo=KST)
    instant_utc = instant_kst.astimezone(timezone.utc)

    assert resolve_lookback_hours(config, instant_kst) == resolve_lookback_hours(
        config, instant_utc
    )


def test_diff_previous_window_follows_business_day_rule(
    base_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diff의 이전 raw도 그 수집 시점의 직전 영업일 창으로 다시 잘라 비교한다 (PRP §9.2)."""
    from pulse.pipeline import _group_previous_activities
    from tests.conftest import make_commit, make_repo_activity

    previous_now = datetime(2026, 10, 6, 0, 0, tzinfo=KST)  # 96h: 10/2 00:00 ~ 10/6 00:00
    inside = make_commit(sha="inside", authored_at=datetime(2026, 10, 2, 0, 30, tzinfo=KST))
    outside = make_commit(sha="outside", authored_at=datetime(2026, 10, 1, 23, 30, tzinfo=KST))
    previous = make_repo_activity(
        commits=(inside, outside),
        active_branches=(),
        merge_requests=(),
        collected_at=previous_now,
    )
    grouped_commit_shas: list[str] = []

    def fake_group_activities(**kwargs: object) -> tuple[tuple[()], tuple[()], tuple[()], float]:
        activities = kwargs["activities"]
        assert isinstance(activities, tuple)
        grouped_commit_shas.extend(c.sha for a in activities for c in a.commits)
        return (), (), (), 0.0

    monkeypatch.setattr("pulse.pipeline.group_activities", fake_group_activities)

    # 이 수집 시점(10/6)의 96h 는 10/5 대체공휴일 때문이다 — 내장 표에 기대지 않고 명시한다
    config = replace(base_config, extra_holidays=(date(2026, 10, 5),))
    _group_previous_activities(config, (previous,))

    assert grouped_commit_shas == ["inside"]


# 내장 공휴일 표에 없는 해 / 표가 담은 마지막 해 — 표를 갱신해도 의미가 유지되게 표에서 구한다
YEAR_MISSING_FROM_TABLE = max(builtin_holiday_years()) + 1
YEAR_COVERED_BY_TABLE = max(builtin_holiday_years())
MONDAY_AFTER_HANGUL_DAY_FRIDAY = datetime(2026, 10, 12, 0, 0, tzinfo=KST)  # 금요일 10/9 가 한글날


def test_resolve_lookback_hours_with_calendar_none_treats_korean_holiday_as_workday(
    base_config: Config,
) -> None:
    """holiday_calendar=none 이면 10/5 대체공휴일이 평일이라 10/6 화요일은 24h 다 (kr 은 96h)."""
    config = replace(base_config, holiday_calendar="none")

    assert resolve_lookback_hours(config, datetime(2026, 10, 6, 0, 0, tzinfo=KST)) == 24


@pytest.mark.parametrize(
    ("extra_holidays", "expected_hours"),
    [
        pytest.param((), 72, id="extra 없음: 한글날 금요일도 평일 → 금~일 72h"),
        pytest.param((date(2026, 10, 9),), 96, id="extra 로 10/9 를 쉬는 날로: 목~일 96h"),
    ],
)
def test_resolve_lookback_hours_with_calendar_none_still_counts_extra_holidays(
    base_config: Config, extra_holidays: tuple[date, ...], expected_hours: int
) -> None:
    """none 은 내장 표만 끈다 — 설정의 extra_holidays 는 그대로 쉬는 날이다."""
    config = replace(base_config, holiday_calendar="none", extra_holidays=extra_holidays)

    assert resolve_lookback_hours(config, MONDAY_AFTER_HANGUL_DAY_FRIDAY) == expected_hours


def test_config_holiday_dates_with_calendar_none_returns_only_extra_holidays(
    base_config: Config,
) -> None:
    """휴무일 집합이 설정의 달력을 따른다 — none 이면 추가분만 남는다."""
    from pulse.pipeline import config_holiday_dates

    extra_day = date(2026, 10, 2)
    config = replace(base_config, holiday_calendar="none", extra_holidays=(extra_day,))

    assert config_holiday_dates(config) == frozenset({extra_day})


def test_config_holiday_dates_with_default_calendar_includes_builtin_table(
    base_config: Config,
) -> None:
    """기본(kr)은 내장 표 ∪ extra 다."""
    from pulse.pipeline import config_holiday_dates

    extra_day = date(2026, 10, 2)
    config = replace(base_config, extra_holidays=(extra_day,))

    holidays = config_holiday_dates(config)

    assert date(2026, 10, 5) in holidays
    assert extra_day in holidays


@pytest.mark.parametrize(
    "today",
    [
        pytest.param(date(YEAR_MISSING_FROM_TABLE, 1, 2), id="표에 없는 해"),
        pytest.param(date(YEAR_COVERED_BY_TABLE, 12, 1), id="12월: 다음 해 표가 아직 없음"),
    ],
)
class TestCalendarWarningsBySelectedCalendar:
    """표 갱신 경고는 내장 표를 쓰는 kr 에만 의미가 있다 (PRP §5.3 권장 A)."""

    def test_kr_calendar_reports_table_gap(self, base_config: Config, today: date) -> None:
        from pulse.pipeline import calendar_warnings

        warnings = calendar_warnings(base_config, today)

        assert len(warnings) == 1
        assert "pulse/kr_holidays.py" in warnings[0]

    def test_none_calendar_has_no_table_warning(self, base_config: Config, today: date) -> None:
        from pulse.pipeline import calendar_warnings

        config = replace(base_config, holiday_calendar="none")

        assert calendar_warnings(config, today) == ()


def test_calendar_warnings_with_calendar_none_still_warn_about_long_extra_holiday_run(
    base_config: Config,
) -> None:
    """none 이어도 extra_holidays 가 14일 넘게 이어지면 연속 휴무 경고는 남는다."""
    from pulse.pipeline import calendar_warnings

    start = date(2026, 11, 16)
    extra_holidays = tuple(date.fromordinal(start.toordinal() + offset) for offset in range(20))
    config = replace(base_config, holiday_calendar="none", extra_holidays=extra_holidays)

    warnings = calendar_warnings(config, date(2026, 12, 7))

    assert len(warnings) == 1
    assert "연속" in warnings[0]


def test_calendar_warnings_with_calendar_none_does_not_let_builtin_table_extend_the_holiday_run(
    base_config: Config,
) -> None:
    """none 이면 연속 휴무 판정에도 내장 표가 끼지 않는다.

    9/28~10/8 의 평일 중 10/5(대체공휴일)와 10/9(한글날)만 extra 에서 일부러 뺀다. 내장 표가 끼면
    두 날이 모두 쉬는 날이 되어 14일 연속이 되지만, none 이면 10/9 가 직전 영업일이라 3일일 뿐이다.
    """
    from pulse.pipeline import calendar_warnings

    extra_holidays = (
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
    )
    config = replace(base_config, holiday_calendar="none", extra_holidays=extra_holidays)

    assert calendar_warnings(config, date(2026, 10, 12)) == ()
