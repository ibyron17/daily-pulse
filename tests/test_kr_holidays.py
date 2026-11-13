"""내장 공휴일 표(pulse/kr_holidays.py) 정합성 테스트.

표는 사람이 옮겨 적은 데이터라 오타가 조용히 영업일 계산을 틀리게 만든다.
그래서 요일·대체공휴일 규칙·보도된 발표 건수를 계산으로 대조해 고정한다.

canary 테스트(test_current_year_is_covered)는 의도적으로 시계에 의존한다 —
표를 갱신하지 않은 채 12월(다음 해 표가 필요한 시점)이 오면 실패해
"전년 6월에 발표되는 다음 해 표를 넣어라"는 정비 알림 역할을 한다.
"""

from collections import defaultdict
from datetime import date, timedelta

import pytest

from pulse.business_calendar import builtin_holiday_years, holiday_coverage_warnings
from pulse.kr_holidays import KR_PUBLIC_HOLIDAYS

SUBSTITUTE_SUFFIX = " 대체공휴일"
CHAIN_SUFFIX = " 연휴"
SATURDAY = 5
SUNDAY = 6
WEEKDAY_NAMES = ("월", "화", "수", "목", "금", "토", "일")

# 토·일 어느 쪽에 겹쳐도 다음 평일로 대체되는 공휴일 (2027 보도 기준 노동절·제헌절 포함)
WEEKEND_SUBSTITUTED = frozenset(
    {
        "삼일절",
        "광복절",
        "개천절",
        "한글날",
        "성탄절",
        "어린이날",
        "부처님오신날",
        "노동절",
        "제헌절",
    }
)
# 연휴 중 하루가 일요일과 겹칠 때만 대체가 생기는 명절
SUNDAY_ONLY_SUBSTITUTED = frozenset({"설날", "추석"})

# PRP §6.2 의 2026년 표 — (날짜, 요일). 요일은 PRP 문서가 적은 값을 그대로 옮겼다.
PRP_2026_WEEKDAYS = (
    (date(2026, 1, 1), "목"),
    (date(2026, 2, 16), "월"),
    (date(2026, 2, 17), "화"),
    (date(2026, 2, 18), "수"),
    (date(2026, 3, 1), "일"),
    (date(2026, 3, 2), "월"),
    (date(2026, 5, 1), "금"),
    (date(2026, 5, 5), "화"),
    (date(2026, 5, 24), "일"),
    (date(2026, 5, 25), "월"),
    (date(2026, 6, 3), "수"),
    (date(2026, 6, 6), "토"),
    (date(2026, 7, 17), "금"),
    (date(2026, 8, 15), "토"),
    (date(2026, 8, 17), "월"),
    (date(2026, 9, 24), "목"),
    (date(2026, 9, 25), "금"),
    (date(2026, 9, 26), "토"),
    (date(2026, 10, 3), "토"),
    (date(2026, 10, 5), "월"),
    (date(2026, 10, 9), "금"),
    (date(2026, 12, 25), "금"),
)

# 2027년 — 공식 발표를 다룬 보도 기준(월력요항 원문 대조 전, 확인일 2026-10-06)의 24일과 건수.
# 표와 같은 값을 한 번 더 적어 옮겨 적기 오타(요일이 안 바뀌는 날짜 오타 포함)를 잡는다.
REPORTED_2027_TABLE = (
    (date(2027, 1, 1), "신정"),
    (date(2027, 2, 6), "설날 연휴"),
    (date(2027, 2, 7), "설날"),
    (date(2027, 2, 8), "설날 연휴"),
    (date(2027, 2, 9), "설날 대체공휴일"),
    (date(2027, 3, 1), "삼일절"),
    (date(2027, 5, 1), "노동절"),
    (date(2027, 5, 3), "노동절 대체공휴일"),
    (date(2027, 5, 5), "어린이날"),
    (date(2027, 5, 13), "부처님오신날"),
    (date(2027, 6, 6), "현충일"),
    (date(2027, 7, 17), "제헌절"),
    (date(2027, 7, 19), "제헌절 대체공휴일"),
    (date(2027, 8, 15), "광복절"),
    (date(2027, 8, 16), "광복절 대체공휴일"),
    (date(2027, 9, 14), "추석 연휴"),
    (date(2027, 9, 15), "추석"),
    (date(2027, 9, 16), "추석 연휴"),
    (date(2027, 10, 3), "개천절"),
    (date(2027, 10, 4), "개천절 대체공휴일"),
    (date(2027, 10, 9), "한글날"),
    (date(2027, 10, 11), "한글날 대체공휴일"),
    (date(2027, 12, 25), "성탄절"),
    (date(2027, 12, 27), "성탄절 대체공휴일"),
)
REPORTED_2027_HOLIDAY_COUNT = 24
REPORTED_2027_SUNDAY_HOLIDAYS = frozenset(
    {date(2027, 2, 7), date(2027, 6, 6), date(2027, 8, 15), date(2027, 10, 3)}
)
REPORTED_2027_SATURDAY_HOLIDAYS = frozenset(
    {
        date(2027, 2, 6),
        date(2027, 5, 1),
        date(2027, 7, 17),
        date(2027, 10, 9),
        date(2027, 12, 25),
    }
)
REPORTED_2027_CALENDAR_HOLIDAY_DAYS = 72  # 일요일 ∪ 공휴일
REPORTED_2027_FIVE_DAY_WEEK_OFF_DAYS = 119  # 위 72일 ∪ 토요일


def _entries_in_year(year: int) -> list[tuple[date, str]]:
    return [(day, name) for day, name in KR_PUBLIC_HOLIDAYS if day.year == year]


def _every_day_of_year(year: int) -> list[date]:
    first_day = date(year, 1, 1)
    day_count = (date(year + 1, 1, 1) - first_day).days
    return [first_day + timedelta(days=offset) for offset in range(day_count)]


def _holiday_base_name(name: str) -> str:
    """'설날 연휴'·'삼일절 대체공휴일' 같은 이름에서 공휴일 본래 이름만 남긴다."""
    return name.removesuffix(SUBSTITUTE_SUFFIX).removesuffix(CHAIN_SUFFIX)


class TestTableIntegrity:
    """표 자체의 형식 불변식."""

    def test_dates_are_unique(self) -> None:
        dates = [day for day, _ in KR_PUBLIC_HOLIDAYS]
        assert len(dates) == len(set(dates))

    def test_dates_are_ascending(self) -> None:
        dates = [day for day, _ in KR_PUBLIC_HOLIDAYS]
        assert dates == sorted(dates)

    def test_names_are_not_blank(self) -> None:
        assert all(name.strip() for _, name in KR_PUBLIC_HOLIDAYS)

    def test_table_covers_2026_and_2027_without_gaps(self) -> None:
        """연도 집합은 표에서 파생한다 — 새 해를 덧붙여도 깨지지 않고, 중간에 빈 해만 막는다."""
        years = builtin_holiday_years()

        assert {2026, 2027} <= years
        assert years == frozenset(range(min(years), max(years) + 1))

    @pytest.mark.parametrize(
        "known_day",
        [
            date(2026, 10, 3),
            date(2026, 10, 5),
            date(2026, 9, 24),
            date(2026, 9, 25),
            date(2026, 9, 26),
            date(2026, 3, 2),
            date(2026, 8, 17),
        ],
    )
    def test_known_dates_are_present(self, known_day: date) -> None:
        assert known_day in {day for day, _ in KR_PUBLIC_HOLIDAYS}


class TestTable2026MatchesDesignDocument:
    """PRP §6.2 의 2026년 표와 항목·요일이 어긋나지 않는다."""

    def test_dates_match_prp_table(self) -> None:
        table_dates = [day for day, _ in _entries_in_year(2026)]
        assert table_dates == [day for day, _ in PRP_2026_WEEKDAYS]

    def test_weekdays_match_prp_table(self) -> None:
        actual = [(day, WEEKDAY_NAMES[day.weekday()]) for day, _ in _entries_in_year(2026)]
        assert actual == list(PRP_2026_WEEKDAYS)


class TestTable2027MatchesReportedAnnouncement:
    """2027년 표가 보도된 발표 내용과 맞는다 (요일은 date.weekday()로 계산)."""

    def test_entries_match_reported_table(self) -> None:
        assert _entries_in_year(2027) == list(REPORTED_2027_TABLE)

    def test_entry_count(self) -> None:
        assert len(_entries_in_year(2027)) == REPORTED_2027_HOLIDAY_COUNT

    def test_holidays_on_sunday(self) -> None:
        sundays = {day for day, _ in _entries_in_year(2027) if day.weekday() == SUNDAY}
        assert sundays == REPORTED_2027_SUNDAY_HOLIDAYS

    def test_holidays_on_saturday(self) -> None:
        saturdays = {day for day, _ in _entries_in_year(2027) if day.weekday() == SATURDAY}
        assert saturdays == REPORTED_2027_SATURDAY_HOLIDAYS

    def test_calendar_holiday_days_with_sundays(self) -> None:
        holidays = {day for day, _ in _entries_in_year(2027)}
        sundays = {day for day in _every_day_of_year(2027) if day.weekday() == SUNDAY}
        assert len(sundays) == 52
        assert len(sundays & holidays) == 4  # 일요일과 겹치는 날은 한 번만 센다
        assert len(sundays | holidays) == REPORTED_2027_CALENDAR_HOLIDAY_DAYS

    def test_five_day_week_off_days_with_saturdays(self) -> None:
        holidays = {day for day, _ in _entries_in_year(2027)}
        every_day = _every_day_of_year(2027)
        sundays = {day for day in every_day if day.weekday() == SUNDAY}
        saturdays = {day for day in every_day if day.weekday() == SATURDAY}
        calendar_holidays = sundays | holidays
        assert len(saturdays & calendar_holidays) == 5  # 토요일과 겹친 공휴일
        assert len(saturdays | calendar_holidays) == REPORTED_2027_FIVE_DAY_WEEK_OFF_DAYS


class TestSubstituteHolidayRules:
    """대체공휴일 규칙이 표의 모든 해에서 지켜진다."""

    def test_substitute_holidays_fall_on_weekdays(self) -> None:
        substitutes = [day for day, name in KR_PUBLIC_HOLIDAYS if name.endswith(SUBSTITUTE_SUFFIX)]
        assert substitutes  # 규칙을 검사할 대상이 실제로 있다
        assert all(day.weekday() < SATURDAY for day in substitutes)

    def test_substitute_is_first_free_weekday_after_the_original(self) -> None:
        holiday_by_day = dict(KR_PUBLIC_HOLIDAYS)
        plain_holidays = {
            day for day, name in KR_PUBLIC_HOLIDAYS if not name.endswith(SUBSTITUTE_SUFFIX)
        }
        for day, name in KR_PUBLIC_HOLIDAYS:
            if not name.endswith(SUBSTITUTE_SUFFIX):
                continue
            base = _holiday_base_name(name)
            originals = [
                original_day
                for original_day, original_name in KR_PUBLIC_HOLIDAYS
                if not original_name.endswith(SUBSTITUTE_SUFFIX)
                and _holiday_base_name(original_name) == base
                and 0 < (day - original_day).days <= 5
            ]
            assert originals, f"{day} {name}: 대체 대상 원 공휴일이 표에 없다"
            skipped_days = [
                originals[-1] + timedelta(days=offset)
                for offset in range(1, (day - originals[-1]).days)
            ]
            skipped_weekdays = [d for d in skipped_days if d.weekday() < SATURDAY]
            assert all(d in plain_holidays for d in skipped_weekdays), (
                f"{day} {holiday_by_day[day]}: 원 공휴일과 대체일 사이에 쉬지 않는 평일이 있다"
            )

    def test_every_weekend_overlap_has_exactly_the_substitute_the_rule_requires(self) -> None:
        groups: defaultdict[tuple[int, str], list[date]] = defaultdict(list)
        substitutes: defaultdict[tuple[int, str], list[date]] = defaultdict(list)
        for day, name in KR_PUBLIC_HOLIDAYS:
            key = (day.year, _holiday_base_name(name))
            target = substitutes if name.endswith(SUBSTITUTE_SUFFIX) else groups
            target[key].append(day)

        for (year, base), days in groups.items():
            expected = _expected_substitute_count(base, days)
            assert len(substitutes.get((year, base), [])) == expected, (
                f"{year} {base}: 대체공휴일 개수가 규칙과 다르다"
            )

    def test_memorial_day_never_has_a_substitute(self) -> None:
        # 현충일은 토·일에 겹쳐도 대체공휴일이 없다 (2026-06-06 토 · 2027-06-06 일)
        names = [name for _, name in KR_PUBLIC_HOLIDAYS]
        assert "현충일" in names
        assert not any(
            name.startswith("현충일") and name.endswith(SUBSTITUTE_SUFFIX) for name in names
        )


def _expected_substitute_count(base: str, days: list[date]) -> int:
    """규칙상 이 공휴일(묶음)에 필요한 대체공휴일 수."""
    if base in SUNDAY_ONLY_SUBSTITUTED:
        return 1 if any(day.weekday() == SUNDAY for day in days) else 0
    if base in WEEKEND_SUBSTITUTED:
        return 1 if any(day.weekday() >= SATURDAY for day in days) else 0
    return 0


def test_current_year_is_covered() -> None:
    """canary: 올해(12월이면 다음 해도) 표가 있어야 한다 — 없으면 표를 갱신하라는 알림이다."""
    warnings = holiday_coverage_warnings(date.today(), builtin_holiday_years())
    assert warnings == (), f"공휴일 표 갱신 필요 — {warnings}"
