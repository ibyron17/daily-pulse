"""collect 실행 계획(pulse/run_plan.py) 결정표 테스트 — PRP weekly-publish-on-business-day §11.1.

휴무일은 내장 표에 기대지 않고 케이스마다 명시 주입한다(표를 갱신해도 깨지지 않게).
표의 「파생값」(이름표·파일명·수집 폭)은 계획에서 결정되므로 publish·pipeline 테스트가 단언한다.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from pulse.run_plan import (
    CollectPlan,
    CollectPlanError,
    Period,
    last_published_window_end,
    pending_period,
    plan_collect,
)

KST = ZoneInfo("Asia/Seoul")

# 2026-10: 개천절 대체공휴일(10/5 월) 포함 — 오늘 사고 주간
OCT = frozenset({date(2026, 10, 3), date(2026, 10, 5), date(2026, 10, 9)})
NO_HOLIDAYS: frozenset[date] = frozenset()


def _kst(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _plan(
    requested: datetime,
    period: Period,
    last_window_end: datetime | None,
    holidays: frozenset[date] = NO_HOLIDAYS,
    force: bool = False,
    ad_hoc: bool = False,
) -> CollectPlan:
    return plan_collect(
        requested,
        period,
        force_weekly=force,
        ad_hoc=ad_hoc,
        holidays=holidays,
        last_window_end=last_window_end,
    )


def _expected(publish: bool, window_end: datetime | None, persist: bool) -> CollectPlan:
    return CollectPlan(publish_weekly=publish, weekly_window_end=window_end, persist_state=persist)


class TestRegularGate:
    """정기 발행 ⇔ period∈{weekly,both} ∧ ¬ad_hoc ∧ 영업일 ∧ ¬이번 주 발행됨."""

    def test_monday_business_day_publishes_with_window_ending_that_monday(self) -> None:
        """G1: 월요일 정상 영업일 — 창 끝은 그 월요일 00:00."""
        plan = _plan(_kst(2026, 7, 20), "both", _kst(2026, 7, 13), frozenset({date(2026, 7, 17)}))

        assert plan == _expected(True, _kst(2026, 7, 20), True)

    def test_holiday_monday_does_not_publish(self) -> None:
        """G2: 월요일이 공휴일이면 그날 주간은 없다."""
        plan = _plan(_kst(2026, 10, 5), "both", _kst(2026, 9, 28), OCT)

        assert plan == _expected(False, None, True)

    def test_tuesday_after_holiday_monday_fills_in_with_monday_window_end(self) -> None:
        """G3: 화요일 보완 — 창 끝은 이번 주 월요일(10/5) 00:00, 요청 시각(10/6)이 아니다."""
        plan = _plan(_kst(2026, 10, 6), "both", _kst(2026, 9, 28), OCT)

        assert plan == _expected(True, _kst(2026, 10, 5), True)

    def test_already_published_this_week_is_recognized_from_todays_record(self) -> None:
        """G4(R5): 오늘 실측 기록(창 끝 = 이번 주 월요일 00:00)이면 수요일은 주간을 내지 않는다."""
        recorded = datetime.fromisoformat("2026-10-05T00:00:00+09:00")

        plan = _plan(_kst(2026, 10, 7), "both", recorded, OCT)

        assert plan == _expected(False, None, True)

    def test_record_in_utc_notation_is_the_same_instant(self) -> None:
        """G4b: 시간대 표기가 달라도 같은 순간이면 이번 주 발행으로 본다."""
        recorded = datetime.fromisoformat("2026-10-04T15:00:00+00:00")

        plan = _plan(_kst(2026, 10, 7), "both", recorded, OCT)

        assert plan.publish_weekly is False

    def test_same_day_rerun_does_not_publish_again(self) -> None:
        """G4c: 같은 날 재실행(14:30)은 첫 실행의 기록 때문에 멱등이다."""
        recorded = datetime.fromisoformat("2026-10-05T00:00:00+09:00")

        plan = _plan(_kst(2026, 10, 6, 14, 30), "both", recorded, OCT)

        assert plan == _expected(False, None, True)

    @pytest.mark.parametrize("requested", [_kst(2026, 10, 10), _kst(2026, 10, 11)])
    def test_weekend_never_publishes_even_if_week_is_unpublished(self, requested: datetime) -> None:
        """G5: 토·일은 미발행 주여도 내지 않는다."""
        plan = _plan(requested, "both", _kst(2026, 9, 28), OCT)

        assert plan == _expected(False, None, True)

    def test_next_monday_publishes_new_week(self) -> None:
        """G5b: 다음 월요일 — 창 10/5~10/12."""
        plan = _plan(_kst(2026, 10, 12), "both", _kst(2026, 10, 5), OCT)

        assert plan == _expected(True, _kst(2026, 10, 12), True)

    def test_monday_daytime_manual_run_uses_midnight_window_end(self) -> None:
        """G9: 월요일 낮(09:00) 수동 실행 — 미발행이면 발행하되 창 끝은 00:00."""
        plan = _plan(_kst(2026, 7, 20, 9), "both", _kst(2026, 7, 13))

        assert plan == _expected(True, _kst(2026, 7, 20), True)

    def test_monday_daytime_manual_run_after_publish_does_not_publish(self) -> None:
        """G9: 월요일 낮 수동 실행도 이번 주 발행됨이면 내지 않는다."""
        plan = _plan(_kst(2026, 7, 20, 9), "both", _kst(2026, 7, 20))

        assert plan == _expected(False, None, True)


class TestWeekWithoutBusinessDay:
    """결정 2: 월~금이 통째로 쉬는 주는 그 직전 주 주간을 만들지 않는다."""

    FULL_WEEK_OFF = frozenset(date(2026, 11, day) for day in range(16, 21))

    @pytest.mark.parametrize("day", range(16, 23))
    def test_no_day_of_the_off_week_publishes(self, day: int) -> None:
        """G6: 11/16(월)~11/22(일) 어느 날에도 발행하지 않는다."""
        plan = _plan(_kst(2026, 11, day), "both", _kst(2026, 11, 9), self.FULL_WEEK_OFF)

        assert plan.publish_weekly is False

    def test_monday_after_off_week_publishes_the_off_week_window(self) -> None:
        """G6': 다음 월요일에는 연휴 주(11/16~11/23)가 나가고, 11/9~11/16 주는 영영 없다."""
        plan = _plan(_kst(2026, 11, 23), "both", _kst(2026, 11, 9), self.FULL_WEEK_OFF)

        assert plan == _expected(True, _kst(2026, 11, 23), True)


class TestSeollHoliday:
    """G6b: 설 연휴(2027-02-06~09) — 월·화는 쉬고 수요일에 지난주 주간이 나간다."""

    HOLIDAYS = frozenset(date(2027, 2, day) for day in range(6, 10))
    LAST = _kst(2027, 2, 1)

    @pytest.mark.parametrize("day", [8, 9])
    def test_holiday_days_do_not_publish(self, day: int) -> None:
        plan = _plan(_kst(2027, 2, day), "both", self.LAST, self.HOLIDAYS)

        assert plan.publish_weekly is False

    def test_first_business_day_after_holiday_publishes_with_monday_window_end(self) -> None:
        plan = _plan(_kst(2027, 2, 10), "both", self.LAST, self.HOLIDAYS)

        assert plan == _expected(True, _kst(2027, 2, 8), True)


class TestYearBoundary:
    """G7: 연말·연초·해를 넘는 주 기준점."""

    HOLIDAYS = frozenset({date(2026, 12, 25), date(2027, 1, 1)})

    def test_year_end_monday_publishes(self) -> None:
        plan = _plan(_kst(2026, 12, 28), "both", _kst(2026, 12, 21), self.HOLIDAYS)

        assert plan == _expected(True, _kst(2026, 12, 28), True)

    def test_new_year_friday_does_not_publish_even_if_the_week_is_unpublished(self) -> None:
        """G7b: 월요일(12/28) 실행이 빠져 이번 주가 미발행이어도 공휴일 금요일에는 내지 않는다."""
        plan = _plan(_kst(2027, 1, 1), "both", _kst(2026, 12, 21), self.HOLIDAYS)

        assert plan.publish_weekly is False

    def test_new_year_first_monday_publishes_year_crossing_week(self) -> None:
        plan = _plan(_kst(2027, 1, 4), "both", _kst(2026, 12, 28), self.HOLIDAYS)

        assert plan == _expected(True, _kst(2027, 1, 4), True)

    def test_anchor_before_new_year_when_published_on_wednesday_after(self) -> None:
        """G7d: 2030-01-02(수) 보완 — 창 끝은 해를 넘어 2029-12-31(월) 00:00."""
        holidays = frozenset({date(2029, 12, 31), date(2030, 1, 1)})

        plan = _plan(_kst(2030, 1, 2), "both", _kst(2029, 12, 24), holidays)

        assert plan == _expected(True, _kst(2029, 12, 31), True)

    def test_forced_republish_on_saturday_keeps_previous_year_anchor_and_skips_state(self) -> None:
        """G7e: 강제 재발행(2027-01-02 토) — 창 끝은 2026-12-28, 운영 기록은 쓰지 않는다."""
        plan = _plan(_kst(2027, 1, 2), "weekly", _kst(2026, 12, 28), force=True)

        assert plan == _expected(True, _kst(2026, 12, 28), False)


class TestForceWeekly:
    """강제 발행 ⇔ period=weekly ∧ --force-weekly — 게이트를 우회하고 운영 기록은 쓰지 않는다."""

    def test_republish_in_published_week_bypasses_gate(self) -> None:
        """G8a."""
        plan = _plan(_kst(2026, 10, 7), "weekly", _kst(2026, 10, 5), OCT, force=True)

        assert plan == _expected(True, _kst(2026, 10, 5), False)

    def test_weekend_is_allowed(self) -> None:
        """G8b."""
        plan = _plan(_kst(2026, 10, 10), "weekly", _kst(2026, 10, 5), OCT, force=True)

        assert plan == _expected(True, _kst(2026, 10, 5), False)

    @pytest.mark.parametrize("requested", [_kst(2026, 7, 20), _kst(2026, 7, 21)])
    def test_both_with_force_is_rejected_at_any_time(self, requested: datetime) -> None:
        """G8c: 월 00:00 예외가 없다 — 어느 시각이든 거부하고 --period weekly 를 안내한다."""
        with pytest.raises(CollectPlanError, match="--period weekly"):
            _plan(requested, "both", None, force=True)

    def test_daily_with_force_is_rejected(self) -> None:
        """G8d."""
        with pytest.raises(CollectPlanError, match="--period weekly"):
            _plan(_kst(2026, 7, 21), "daily", None, force=True)


class TestWeeklyPeriodWithoutForce:
    """G10: period=weekly 비강제도 같은 게이트를 쓴다."""

    def test_already_published_this_week_does_not_publish(self) -> None:
        plan = _plan(_kst(2026, 7, 21), "weekly", _kst(2026, 7, 20))

        assert plan == _expected(False, None, True)

    def test_unpublished_week_publishes(self) -> None:
        plan = _plan(_kst(2026, 7, 21), "weekly", _kst(2026, 7, 13))

        assert plan == _expected(True, _kst(2026, 7, 20), True)


class TestAdHoc:
    """G11: ad-hoc 은 발행하지 않고 운영 기록도 쓰지 않지만, 주간 창은 지난주 월~일로 맞춘다."""

    @pytest.mark.parametrize("period", ["weekly", "both"])
    def test_weekly_window_end_is_that_weeks_monday(self, period: Period) -> None:
        plan = _plan(_kst(2026, 7, 22, 12), period, None, ad_hoc=True)

        assert plan == _expected(False, _kst(2026, 7, 20), False)

    def test_daily_has_no_weekly_window(self) -> None:
        """G11b."""
        plan = _plan(_kst(2026, 7, 22, 12), "daily", None, ad_hoc=True)

        assert plan == _expected(False, None, False)


class TestDailyPeriod:
    """G12: period=daily 는 주간을 건드리지 않는다."""

    def test_monday_midnight_does_not_publish_weekly(self) -> None:
        plan = _plan(_kst(2026, 7, 20), "daily", None)

        assert plan == _expected(False, None, True)


class TestLastPublishedWindowEnd:
    """G13: 발행 기록(latest.json)에서 창 끝을 읽는 순수 파서 — 못 읽으면 None."""

    @pytest.mark.parametrize(
        "snapshot",
        [
            None,
            {},
            {"window_end": None},
            {"window_end": 5},
            {"window_end": "garbage"},
            # 시간대 없는 값을 통과시키면 aware 인 이번 주 월요일과의 비교에서 TypeError 가 난다
            {"window_end": "2026-10-05T00:00:00"},
        ],
    )
    def test_unreadable_record_is_none(self, snapshot: dict[str, object] | None) -> None:
        assert last_published_window_end(snapshot) is None

    def test_aware_iso_string_is_parsed(self) -> None:
        parsed = last_published_window_end({"window_end": "2026-10-05T00:00:00+09:00"})

        assert parsed == _kst(2026, 10, 5)
        assert parsed is not None and parsed.tzinfo is not None


class TestPendingPeriod:
    """G14: pending.json 의 weekly 섹션은 언제나 「마지막으로 발행된 주간 HTML」의 지문이다."""

    @pytest.mark.parametrize(
        ("period", "publish_weekly", "expected"),
        [
            ("daily", False, "daily"),
            ("daily", True, "daily"),
            ("weekly", True, "weekly"),
            ("weekly", False, None),
            ("both", True, "both"),
            ("both", False, "daily"),
        ],
    )
    def test_scope_table(
        self, period: Period, publish_weekly: bool, expected: Period | None
    ) -> None:
        assert pending_period(period, publish_weekly) == expected
