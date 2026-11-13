"""영업일 달력(pulse/business_calendar.py) 순수 함수 테스트 — PRP §11.1 결정표."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pulse.business_calendar import (
    DEFAULT_HOLIDAY_CALENDAR,
    HOLIDAY_CALENDARS,
    HOURS_PER_DAY,
    MAX_CATCHUP_DAYS,
    builtin_holiday_years,
    holiday_coverage_warnings,
    holiday_dates,
    is_business_day,
    previous_business_day,
    week_anchor,
)

KST = ZoneInfo("Asia/Seoul")
BUILTIN = holiday_dates()
WEDNESDAY = 2  # date.weekday()


def _catchup_hours(today: date, holidays: frozenset[date]) -> int:
    """직전 영업일부터 today까지의 시간 폭 (00:00 운용 기준)."""
    return (today - previous_business_day(today, holidays)).days * HOURS_PER_DAY


class TestPreviousBusinessDay:
    """내장 표 기준 직전 영업일과 일간 폭 (PRP §11.1)."""

    @pytest.mark.parametrize(
        ("today", "expected_previous", "expected_hours"),
        [
            pytest.param(
                date(2026, 10, 6), date(2026, 10, 2), 96, id="요구 사례: 대체공휴일 다음 날"
            ),
            pytest.param(date(2026, 7, 14), date(2026, 7, 13), 24, id="평상 화요일"),
            pytest.param(date(2026, 7, 13), date(2026, 7, 10), 72, id="기존 월요일 72h 회귀"),
            pytest.param(date(2026, 10, 5), date(2026, 10, 2), 72, id="공휴일 월요일 당일"),
            pytest.param(date(2026, 10, 3), date(2026, 10, 2), 24, id="토요일"),
            pytest.param(date(2026, 10, 4), date(2026, 10, 2), 48, id="일요일"),
            pytest.param(date(2026, 9, 28), date(2026, 9, 23), 120, id="추석 연휴 뒤 월요일"),
            pytest.param(date(2026, 5, 6), date(2026, 5, 4), 48, id="화요일 공휴일 다음 날"),
            pytest.param(date(2026, 2, 19), date(2026, 2, 13), 144, id="설 연휴(월~수) 다음 날"),
            pytest.param(date(2026, 8, 18), date(2026, 8, 14), 96, id="토 공휴일+대체 월요일"),
            pytest.param(date(2026, 10, 12), date(2026, 10, 8), 96, id="공휴일 금요일 뒤 월요일"),
            pytest.param(date(2026, 12, 28), date(2026, 12, 24), 96, id="연말: 12/25 금요일"),
        ],
    )
    def test_builtin_table(self, today: date, expected_previous: date, expected_hours: int) -> None:
        previous = previous_business_day(today, BUILTIN)

        assert previous == expected_previous
        assert _catchup_hours(today, BUILTIN) == expected_hours

    def test_year_boundary_with_injected_holiday(self) -> None:
        holidays = frozenset({date(2027, 1, 1)})

        previous = previous_business_day(date(2027, 1, 4), holidays)

        assert previous == date(2026, 12, 31)
        assert _catchup_hours(date(2027, 1, 4), holidays) == 96

    def test_year_boundary_with_builtin_2027_table(self) -> None:
        # 2027-01-01(금)이 내장 표에 있으므로 주입 없이도 같은 결과가 나온다
        assert previous_business_day(date(2027, 1, 4), BUILTIN) == date(2026, 12, 31)

    def test_year_missing_from_table_falls_back_to_weekends_only(self) -> None:
        # 표의 마지막 해 다음 해(= 표에 없는 해)의 첫 수요일 — 표를 늘려도 계속 「없는 해」다
        missing_year = max(builtin_holiday_years()) + 1
        january_first = date(missing_year, 1, 1)
        today = january_first + timedelta(days=(WEDNESDAY - january_first.weekday()) % 7)

        previous = previous_business_day(today, BUILTIN)

        assert previous == today - timedelta(days=1)  # 주말 규칙만: 화요일이 직전 영업일
        assert _catchup_hours(today, BUILTIN) == 24
        warnings = holiday_coverage_warnings(today, builtin_holiday_years())
        assert len(warnings) == 1
        assert str(missing_year) in warnings[0]

    def test_extra_holidays_extend_the_window(self) -> None:
        holidays = holiday_dates((date(2026, 10, 2),))

        previous = previous_business_day(date(2026, 10, 6), holidays)

        assert previous == date(2026, 10, 1)
        assert _catchup_hours(date(2026, 10, 6), holidays) == 120

    def test_search_is_capped_at_max_catchup_days(self) -> None:
        today = date(2026, 11, 30)
        endless_holidays = frozenset(today - timedelta(days=offset) for offset in range(1, 31))

        previous = previous_business_day(today, endless_holidays)

        assert previous == today - timedelta(days=MAX_CATCHUP_DAYS)

    def test_today_itself_is_never_the_answer(self) -> None:
        # 직전 영업일은 오늘보다 "엄격히" 이전이다 — 오늘이 평상 영업일이어도 어제부터 센다
        assert previous_business_day(date(2026, 7, 15), BUILTIN) == date(2026, 7, 14)


class TestIsBusinessDay:
    """월~금이면서 휴무일이 아닌 날만 영업일."""

    @pytest.mark.parametrize(
        ("day", "expected"),
        [
            pytest.param(date(2026, 10, 7), True, id="평일"),
            pytest.param(date(2026, 10, 10), False, id="토요일"),
            pytest.param(date(2026, 10, 11), False, id="일요일"),
            pytest.param(date(2026, 10, 9), False, id="공휴일 평일(한글날)"),
        ],
    )
    def test_cases(self, day: date, expected: bool) -> None:
        assert is_business_day(day, BUILTIN) is expected


class TestWeekAnchor:
    """now 이하의 가장 최근 월요일 00:00 (같은 tzinfo)."""

    @pytest.mark.parametrize(
        ("moment", "expected"),
        [
            pytest.param(
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
                id="월 00:00은 그대로",
            ),
            pytest.param(
                datetime(2026, 10, 5, 9, 0, tzinfo=KST),
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
                id="월 09:00",
            ),
            pytest.param(
                datetime(2026, 10, 6, 0, 0, tzinfo=KST),
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
                id="화 00:00(오늘 사고 날짜)",
            ),
            pytest.param(
                datetime(2026, 10, 11, 23, 59, tzinfo=KST),
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
                id="일 23:59",
            ),
        ],
    )
    def test_cases(self, moment: datetime, expected: datetime) -> None:
        anchor = week_anchor(moment)

        assert anchor == expected
        assert anchor.tzinfo is moment.tzinfo
        assert anchor.weekday() == 0

    def test_drops_seconds_and_microseconds(self) -> None:
        anchor = week_anchor(datetime(2026, 10, 7, 13, 45, 59, 123456, tzinfo=KST))

        assert anchor == datetime(2026, 10, 5, 0, 0, 0, 0, tzinfo=KST)


class TestHolidayCoverageWarnings:
    """표가 담지 않은 해를 사람이 읽을 경고로 알린다 (canary 판정에도 쓰인다)."""

    def test_no_warning_when_year_is_covered(self) -> None:
        assert holiday_coverage_warnings(date(2026, 10, 6), frozenset({2026})) == ()

    def test_december_warns_about_missing_next_year(self) -> None:
        warnings = holiday_coverage_warnings(date(2026, 12, 1), frozenset({2026}))

        assert len(warnings) == 1
        assert "2027" in warnings[0]

    def test_missing_current_year_warns(self) -> None:
        warnings = holiday_coverage_warnings(date(2028, 1, 3), frozenset({2026, 2027}))

        assert len(warnings) == 1
        assert "2028" in warnings[0]

    def test_december_without_current_and_next_year_warns_twice(self) -> None:
        warnings = holiday_coverage_warnings(date(2028, 12, 1), frozenset({2026, 2027}))

        assert len(warnings) == 2

    def test_builtin_table_is_judged_by_its_latest_year(self) -> None:
        # 표의 마지막 해 12월부터 다음 해 표를 요구한다 (canary 가 울리는 시점)
        covered = builtin_holiday_years()
        latest = max(covered)

        assert holiday_coverage_warnings(date(min(covered), 10, 6), covered) == ()
        assert holiday_coverage_warnings(date(latest - 1, 12, 1), covered) == ()
        assert holiday_coverage_warnings(date(latest, 11, 30), covered) == ()
        december_warnings = holiday_coverage_warnings(date(latest, 12, 1), covered)
        assert len(december_warnings) == 1
        assert str(latest + 1) in december_warnings[0]

    def test_missing_year_warning_points_only_to_the_table_not_extra_holidays(self) -> None:
        """extra_holidays 를 채워도 이 경고는 사라지지 않는다 — 안내가 그쪽을 가리키면 안 된다."""
        covered = builtin_holiday_years()

        warnings = holiday_coverage_warnings(date(max(covered) + 1, 1, 2), covered)

        assert len(warnings) == 1
        assert "pulse/kr_holidays.py" in warnings[0]
        assert "extra_holidays" not in warnings[0]


class TestHolidayDates:
    """내장 표와 설정 추가분의 합집합."""

    def test_extra_holidays_are_added(self) -> None:
        extra = date(2026, 10, 2)

        assert extra not in holiday_dates()
        assert extra in holiday_dates((extra,))

    def test_builtin_holidays_are_kept_when_extra_is_given(self) -> None:
        assert date(2026, 10, 5) in holiday_dates((date(2026, 10, 2),))


class TestHolidayCalendarSelection:
    """holiday_dates 의 calendar 인자 — 내장 표를 쓸지(kr), 추가분만 쓸지(none) (T2)."""

    def test_none_calendar_drops_builtin_table(self) -> None:
        assert holiday_dates((), "none") == frozenset()

    def test_none_calendar_keeps_extra_holidays(self) -> None:
        extra = date(2026, 10, 2)

        assert holiday_dates((extra,), "none") == frozenset({extra})

    def test_none_calendar_counts_korean_public_holiday_as_business_day(self) -> None:
        """한국 공휴일(2026-10-05 대체공휴일)이 none 이면 평일, 기본(kr)이면 휴무다."""
        holiday_monday = date(2026, 10, 5)

        assert is_business_day(holiday_monday, holiday_dates(calendar="none")) is True
        assert is_business_day(holiday_monday, holiday_dates()) is False

    def test_default_calendar_is_kr_and_matches_explicit_kr(self) -> None:
        extra = (date(2026, 10, 2),)

        assert DEFAULT_HOLIDAY_CALENDAR == "kr"
        assert holiday_dates() == holiday_dates(calendar="kr")
        assert holiday_dates(extra) == holiday_dates(extra, "kr")

    def test_allowed_calendars_are_kr_and_none(self) -> None:
        assert HOLIDAY_CALENDARS == ("kr", "none")
