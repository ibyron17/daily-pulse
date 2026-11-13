"""영업일 달력: 직전 영업일·주 기준점·공휴일 표 커버리지 경고 (★순수).

파일·시계·환경변수에 닿지 않는다 — 「오늘」과 「휴무일 집합」은 항상 인자로 받는다.
계약 상대: pulse/kr_holidays.py(내장 표 데이터), pulse/pipeline.py(일간 조회 폭 계산),
pulse/run_plan.py(주 기준점), pulse/config/loader.py(holiday_calendar 허용값 — 이 모듈이 주인).
Config 를 import 하지 않아(휴무일은 date 튜플로 받는다) 순환이 없다.
"""

from datetime import date, datetime, timedelta
from typing import Final, Literal

from pulse.kr_holidays import KR_PUBLIC_HOLIDAYS

HolidayCalendar = Literal["kr", "none"]
# config.yaml holiday_calendar 허용값. 다른 나라는 표 모듈 하나와 이 튜플·holiday_dates 분기를
# 더해 붙인다 (지금은 만들지 않는다).
HOLIDAY_CALENDARS: Final[tuple[HolidayCalendar, ...]] = ("kr", "none")
DEFAULT_HOLIDAY_CALENDAR: Final[HolidayCalendar] = "kr"

HOURS_PER_DAY: Final = 24
# 휴무일이 이보다 길게 이어지면 표가 잘못됐다고 본다 (일간 수집 폭 상한 = 14일 = 336h)
MAX_CATCHUP_DAYS: Final = 14
# 이 달부터 다음 해 표가 없으면 미리 경고한다 (다음 해 월력요항은 전년 6월에 나온다)
NEXT_YEAR_NOTICE_MONTH: Final = 12
# date.weekday(): 월=0 … 금=4, 토=5, 일=6 — 5 이상이 주말
FIRST_WEEKEND_WEEKDAY: Final = 5

_BUILTIN_HOLIDAY_DATES: Final = frozenset(day for day, _ in KR_PUBLIC_HOLIDAYS)


def builtin_holiday_years() -> frozenset[int]:
    """내장 표가 담은 연도 집합을 반환한다."""
    return frozenset(day.year for day in _BUILTIN_HOLIDAY_DATES)


def holiday_dates(
    extra_holidays: tuple[date, ...] = (),
    calendar: HolidayCalendar = DEFAULT_HOLIDAY_CALENDAR,
) -> frozenset[date]:
    """달력의 내장 표와 설정 추가분을 합친 휴무일 집합을 반환한다 (none 이면 추가분만)."""
    builtin: frozenset[date] = frozenset() if calendar == "none" else _BUILTIN_HOLIDAY_DATES
    return builtin | frozenset(extra_holidays)


def is_business_day(day: date, holidays: frozenset[date]) -> bool:
    """월~금이면서 휴무일이 아니면 True."""
    return day.weekday() < FIRST_WEEKEND_WEEKDAY and day not in holidays


def previous_business_day(
    today: date, holidays: frozenset[date], max_days: int = MAX_CATCHUP_DAYS
) -> date:
    """today보다 엄격히 이전인 가장 최근 영업일. max_days 안에 없으면 today - max_days."""
    for days_back in range(1, max_days + 1):
        candidate = today - timedelta(days=days_back)
        if is_business_day(candidate, holidays):
            return candidate
    return today - timedelta(days=max_days)


def week_anchor(moment: datetime) -> datetime:
    """moment 이하의 가장 최근 월요일 00:00을 같은 tzinfo로 반환한다."""
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def holiday_coverage_warnings(today: date, covered_years: frozenset[int]) -> tuple[str, ...]:
    """today의 해(12월이면 다음 해도)가 표에 없으면 사람이 읽을 경고 문장을 반환한다."""
    warnings: list[str] = []
    if today.year not in covered_years:
        warnings.append(
            f"내장 공휴일 표에 {today.year}년이 없습니다 — 이 해는 주말만 휴무로 봅니다. "
            "pulse/kr_holidays.py 표 갱신이 필요합니다"
        )
    next_year = today.year + 1
    if today.month >= NEXT_YEAR_NOTICE_MONTH and next_year not in covered_years:
        warnings.append(
            f"내장 공휴일 표에 {next_year}년이 아직 없습니다 — 새해가 오기 전에 "
            "pulse/kr_holidays.py 에 다음 해 공휴일을 추가하세요"
        )
    return tuple(warnings)
