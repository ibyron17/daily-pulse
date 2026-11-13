"""collect 1회의 주간 발행·주간 창·운영 상태 기록 여부를 정한다 (★순수).

파일·시계·환경변수에 닿지 않는다 — 요청 시각·휴무일·마지막 발행 기록은 인자로만 받는다.
계약 상대: pulse/publish.py(_cmd_collect 가 CollectPlan 으로 run_pipeline·발행·pending 범위를
정한다), pulse/business_calendar.py(영업일·주 기준점).

디자인 결정표 하나(plan_collect)가 전부다. 핵심 규칙:
- 주간은 영업일에, 그 주(월~일)에 아직 발행되지 않았을 때만 정기 발행한다. 월요일이 공휴일이면
  그 주 다음 영업일에 나가고, 월요일 실행이 실패해 빠진 주도 다음 영업일 실행이 채운다.
- 「이번 주 발행됨」은 마지막 발행 기록의 창 끝(window_end)이 이번 주 월요일 00:00 이상인지로 본다.
  창 끝은 「어느 주를 냈는가」를 직접 가리키므로 이름표(발행일) 규칙이 바뀌어도 흔들리지 않는다.
- 주간 창은 언제나 그 주 월요일 00:00 기준 지난주 월~일이고, 이름표(report_date)는 실행일이다.
  한 실행 안의 now 는 하나로 유지한다 — 옮기는 것은 발행 주간의 창 끝(weekly_window_end)뿐이다.
- 강제 재발행(--force-weekly)과 ad-hoc 은 운영 상태(raw·스냅샷·등록부·이력)를 쓰지 않는다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pulse.business_calendar import is_business_day, week_anchor

Period = Literal["daily", "weekly", "both"]


class CollectPlanError(ValueError):
    """옵션 조합이 성립하지 않을 때 (CLI는 exit 2) — --force-weekly 는 --period weekly 전용."""


@dataclass(frozen=True)
class CollectPlan:
    """collect 1회의 주간 발행·주간 창·운영 상태 기록 결정 (순수 계산 결과)."""

    publish_weekly: bool  # 주간 HTML·latest-weekly·발행 기록·pending weekly 를 쓰는가
    weekly_window_end: datetime | None  # 주간 HTML 을 쓰는 실행(발행·ad-hoc)의 창 끝, 아니면 None
    persist_state: bool  # raw·브랜치 스냅샷·수명주기 등록부·브랜치 이력·보존 정리를 쓰는가


def last_published_window_end(snapshot: Mapping[str, object] | None) -> datetime | None:
    """주간 발행 기록(latest.json)의 window_end. 없음·문자열 아님·형식 오류·시간대 없음이면 None.

    시간대 없는 값은 버린다 — 통과시키면 시간대 있는 이번 주 월요일과 비교할 때 TypeError 가 난다.
    """
    if snapshot is None:
        return None
    value = snapshot.get("window_end")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _is_weekly_due(
    today: date,
    anchor: datetime,
    holidays: frozenset[date],
    last_window_end: datetime | None,
) -> bool:
    """영업일이면서 이번 주(anchor 가 월요일)에 아직 주간이 발행되지 않았으면 True."""
    if not is_business_day(today, holidays):
        return False
    already_published = last_window_end is not None and last_window_end >= anchor
    return not already_published


def plan_collect(
    requested_now: datetime,
    period: Period,
    force_weekly: bool,
    ad_hoc: bool,
    holidays: frozenset[date],
    last_window_end: datetime | None,
) -> CollectPlan:
    """요청 시각·옵션·휴무일·마지막 발행 창으로 이번 수집의 주간 결정을 내린다.

    Args:
        requested_now: --now 또는 현재 시각 (config 시간대로 바꾼 값) — 이름표(발행일)가 된다
        period: 발행 대상
        force_weekly: --force-weekly (게이트 우회 재발행, --period weekly 전용)
        ad_hoc: 단발성 조회 모드 (주간은 발행하지 않고 운영 상태를 바꾸지 않는다)
        holidays: 설정 달력(holiday_calendar)과 extra_holidays 를 합친 휴무일 집합
        last_window_end: 마지막으로 발행된 주간의 창 끝 (last_published_window_end 결과)

    Returns:
        이번 실행의 계획

    Raises:
        CollectPlanError: period 가 weekly 가 아닌데 force_weekly 를 준 경우
    """
    if force_weekly and period != "weekly":
        raise CollectPlanError(
            f"--force-weekly 는 --period {period} 와 함께 쓸 수 없습니다 — "
            "주간 재발행은 --period weekly --force-weekly 로 따로 실행하세요"
        )

    persist_state = not (ad_hoc or force_weekly)
    if period == "daily":
        return CollectPlan(
            publish_weekly=False, weekly_window_end=None, persist_state=persist_state
        )

    anchor = week_anchor(requested_now)
    if ad_hoc:
        return CollectPlan(publish_weekly=False, weekly_window_end=anchor, persist_state=False)

    is_publishing = force_weekly or _is_weekly_due(
        requested_now.date(), anchor, holidays, last_window_end
    )
    return CollectPlan(
        publish_weekly=is_publishing,
        weekly_window_end=anchor if is_publishing else None,
        persist_state=persist_state,
    )


def pending_period(period: Period, publish_weekly: bool) -> Period | None:
    """pending.json에 지문을 기록할 섹션을 정한다 (None이면 기록하지 않음).

    pending 의 weekly 섹션은 언제나 「마지막으로 발행된 주간 HTML」의 지문이어야
    일간·주간을 어떤 순서로 수집해도 inject --period weekly 가 맞는 지문을 쓴다.
    """
    if period == "daily":
        return "daily"
    if period == "weekly":
        return "weekly" if publish_weekly else None
    return "both" if publish_weekly else "daily"
