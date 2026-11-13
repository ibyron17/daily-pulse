"""파이프라인 오케스트레이션: 수집 → 그룹핑 → diff → 렌더링."""

import logging
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from math import ceil
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.branch_history import (
    BranchHistoryStore,
    build_history_view,
    entries_as_dict,
    history_key,
    needs_refresh,
)
from pulse.branch_history import load_store as load_history_store
from pulse.branch_history import save_store as save_history_store
from pulse.branch_history import store_path as history_store_path
from pulse.branch_history import update_store as update_history_store
from pulse.business_calendar import (
    HOURS_PER_DAY,
    MAX_CATCHUP_DAYS,
    builtin_holiday_years,
    holiday_coverage_warnings,
    holiday_dates,
    previous_business_day,
)
from pulse.collector import collect_histories, collect_repos
from pulse.collector.storage import load_raw_activity, save_raw_activity
from pulse.config import Config
from pulse.diff import compute_diff
from pulse.grouper import filter_activities_to_window, group_activities
from pulse.grouper.release_train import build_release_train
from pulse.grouper.signals import commit_histogram_by_date, generate_new_work_signals
from pulse.lifecycle import (
    build_lifecycle_view,
    load_registry,
    registry_path,
    save_registry,
    update_registry,
)
from pulse.models import (
    BranchHistoryRequest,
    BranchHistoryView,
    DashboardModel,
    DiffSummary,
    FeatureGroup,
    GroupLifecycleView,
    ReleaseTrain,
    RepoActivity,
)
from pulse.renderer import build_dashboard_model
from pulse.retention import cleanup_retention
from pulse.state_io import save_optional_state
from pulse.weekly_branches import find_weekly_baseline_snapshots, weekly_created_branches

logger = logging.getLogger(__name__)

# 주간 뷰용 수집 범위 (고정)
WEEKLY_LOOKBACK_HOURS = 168


def _enrich_groups_with_histogram(
    groups: tuple[FeatureGroup, ...],
    report_date: date,
) -> tuple[FeatureGroup, ...]:
    """그룹들에 7일 히스토그램을 주입한다 (순수).

    각 그룹의 daily_commit_counts를 계산하고 주입해서
    등록부 갱신용 enriched 그룹 튜플을 반환한다.

    Args:
        groups: 그룹 튜플
        report_date: 리포트 날짜 (히스토그램 기준)

    Returns:
        daily_commit_counts가 주입된 그룹 튜플
    """
    enriched = []
    for group in groups:
        histogram = commit_histogram_by_date(group.commits, 7, report_date)
        enriched_group = replace(group, daily_commit_counts=histogram)
        enriched.append(enriched_group)
    return tuple(enriched)


class AllReposFailedError(Exception):
    """모든 레포 수집이 실패했을 때 발생하는 예외."""

    pass


def get_effective_now(config: Config) -> datetime:
    """config의 timezone을 기준으로 현재 시각을 반환.

    Args:
        config: 설정

    Returns:
        timezone 적용된 현재 시각
    """
    tz = ZoneInfo(config.timezone_name)
    return datetime.now(tz=tz)


def _local_date(config: Config, now: datetime) -> date:
    """now를 config 시간대로 바꾼 날짜. 입력 시간대와 무관하게 같은 순간이면 같은 날짜다."""
    return now.astimezone(ZoneInfo(config.timezone_name)).date()


def config_holiday_dates(config: Config) -> frozenset[date]:
    """설정의 달력(holiday_calendar)과 extra_holidays 로 휴무일 집합을 만든다.

    일간 창·주간 발행 게이트·달력 경고가 모두 이 함수를 거쳐야 셋이 같은 휴무일을 본다.
    """
    return holiday_dates(config.extra_holidays, config.holiday_calendar)


def resolve_lookback_hours(config: Config, now: datetime) -> int:
    """일간 조회 폭(시간): 직전 영업일의 같은 시각부터 now까지, 설정값보다 좁아지지 않는다.

    weekend_catchup이 False면 공휴일을 보지 않고 lookback_hours 그대로다.
    00:00 운용에서는 창이 정확히 「직전 영업일 00:00 ~ 오늘 00:00」이 된다.

    Args:
        config: 설정 (weekend_catchup, lookback_hours, holiday_calendar, extra_holidays,
            timezone_name)
        now: 기준 시각

    Returns:
        일간 조회 폭 (시간)
    """
    if not config.weekend_catchup:
        return config.lookback_hours

    today = _local_date(config, now)
    previous = previous_business_day(today, config_holiday_dates(config))
    return max(config.lookback_hours, (today - previous).days * HOURS_PER_DAY)


def calendar_warnings(config: Config, today: date) -> tuple[str, ...]:
    """영업일 계산이 믿을 수 없을 때의 경고 문장들. weekend_catchup이 False면 비어 있다.

    내장 공휴일 표에 없는 해(표를 쓰는 kr 달력일 때만), 그리고 휴무일이 상한
    (MAX_CATCHUP_DAYS)까지 이어진 경우를 알린다.
    """
    if not config.weekend_catchup:
        return ()

    warnings: list[str] = []
    if config.holiday_calendar == "kr":
        warnings.extend(holiday_coverage_warnings(today, builtin_holiday_years()))
    previous = previous_business_day(today, config_holiday_dates(config))
    if (today - previous).days >= MAX_CATCHUP_DAYS:
        warnings.append(
            f"휴무일이 {MAX_CATCHUP_DAYS}일 이상 연속입니다 — "
            "공휴일 표와 extra_holidays 를 확인하세요"
        )
    return tuple(warnings)


def report_date_from_now(now: datetime) -> date:
    """현재 시각으로부터 리포트 날짜 생성.

    Args:
        now: 현재 시각

    Returns:
        리포트 날짜 (오늘 날짜)
    """
    return now.date()


def _collect_past_date_dirs(raw_dir: Path, today: date) -> list[tuple[date, Path]]:
    """raw 디렉토리에서 오늘 이전의 날짜 형식(YYYY-MM-DD) 하위 디렉토리를 수집한다."""
    date_dirs = []
    for item in raw_dir.iterdir():
        if not item.is_dir():
            continue
        try:
            item_date = date.fromisoformat(item.name)
        except ValueError:
            logger.debug("날짜 형식이 아닌 디렉토리 무시: %s", item.name)
            continue
        if item_date < today:
            date_dirs.append((item_date, item))
    return date_dirs


def find_previous_raw_dir(data_dir: Path, today: date) -> tuple[date, Path] | None:
    """가장 최근의 과거 raw 디렉토리를 찾는다.

    오늘보다 이전인 날짜 디렉토리 중 가장 최근 것을 반환 —
    주말 공백 시 금요일 디렉토리가 선택된다. 없으면 None (diff 생략).
    """
    raw_dir = data_dir / "raw"
    if not raw_dir.exists():
        return None
    date_dirs = _collect_past_date_dirs(raw_dir, today)
    if not date_dirs:
        return None
    return max(date_dirs, key=lambda pair: pair[0])


def _map_raw_date_to_data_basis(
    raw_date: date,
    previous_now: datetime,
) -> date:
    """이전 raw 디렉토리의 날짜를 "데이터 기준일"로 사상한다.

    previous_now가 자정(00:00:00)이면 raw_date - 1일,
    아니면 raw_date를 그대로 반환한다.

    이렇게 함으로써:
    - 달력 정렬 운용 (--now T00:00)에서 자신의 데이터 날짜와
      다른 날짜가 "비교 기준"으로 표시된다.

    Args:
        raw_date: 이전 raw 디렉토리의 YYYY-MM-DD
        previous_now: 이전 수집 시각 (collected_at)

    Returns:
        diff.compared_to에 저장할 데이터 기준일
    """
    # previous_now.time() == time(0, 0, 0) 체크 (마이크로초 무시)
    if previous_now.hour == 0 and previous_now.minute == 0 and previous_now.second == 0:
        # 자정 수집 → 1일 전 데이터 기준
        return raw_date - timedelta(days=1)
    else:
        # 비자정 수집 → 그대로 (어제 데이터는 어제 기준)
        return raw_date


def load_previous_activities(raw_dir: Path) -> tuple[RepoActivity, ...]:
    """raw 디렉토리의 모든 JSON 파일로부터 RepoActivity를 로드.

    Args:
        raw_dir: 날짜별 raw 디렉토리 (예: data/raw/2026-07-15)

    Returns:
        RepoActivity 튜플
    """
    activities = []
    if not raw_dir.exists():
        return ()

    for json_file in raw_dir.glob("*.json"):
        try:
            activity = load_raw_activity(json_file)
            activities.append(activity)
        except Exception as e:
            logger.warning("Failed to load %s: %s", json_file, e)

    return tuple(activities)


def has_full_collection(activities: tuple[RepoActivity, ...]) -> bool:
    """모든 활동이 성공적으로 수집되었는지 확인.

    Args:
        activities: 수집된 활동들

    Returns:
        모든 활동의 status가 'ok'이면 True
    """
    if not activities:
        return True

    return all(activity.status == "ok" for activity in activities)


def _collect_activities(
    config: Config, now: datetime, save_snapshots: bool = True
) -> tuple[RepoActivity, ...]:
    """레포 활동을 수집하고 전 레포 실패 여부를 판정한다."""
    activities = tuple(collect_repos(config=config, now=now, save_snapshots=save_snapshots))

    # 전부 실패 여부를 먼저 확인해야 한다
    # (일부 실패 분기가 먼저 오면 이 예외는 도달 불가능해진다)
    if len(activities) > 0 and all(a.status == "failed" for a in activities):
        reasons = ", ".join(a.failure_reason or "알 수 없음" for a in activities)
        raise AllReposFailedError(f"모든 {len(activities)}개 레포 수집 실패: {reasons}")
    if not has_full_collection(activities):
        # 일부 실패는 대시보드에 표시하고 계속
        logger.warning("일부 레포 수집 실패, 대시보드 생성 계속")
    return activities


def _save_raw_activities(activities: tuple[RepoActivity, ...], data_dir: Path) -> None:
    """성공 수집분을 레포별 raw JSON으로 저장한다.

    레포 하나의 저장 실패가 나머지 레포와 발행을 막지 않는다 — 수집 실패를
    레포 단위로 격리하는 프로젝트 규칙을 저장에도 같이 적용한다.
    """
    save_optional_state("raw 디렉토리 생성", lambda: data_dir.mkdir(parents=True, exist_ok=True))
    for activity in activities:
        if activity.status == "ok":
            # partial 로 활동을 즉시 캡처한다 — lambda 기본 인자로 늦은 바인딩을 피하려 하면
            # 타입 추론이 깨지고, 그냥 lambda 로 닫으면 모든 항목이 마지막 활동으로 저장된다
            save_optional_state(
                f"raw 활동({activity.repo.full_path})",
                partial(save_raw_activity, activity, data_dir / "raw"),
            )


def _group_previous_activities(
    config: Config,
    previous_activities: tuple[RepoActivity, ...],
) -> tuple[FeatureGroup, ...]:
    """비교 기준일 activities를 그 시점의 now로 그룹핑한다 (G1).

    previous_now는 항상 collected_at 최댓값으로 내부 계산.
    필터 폭은 resolve_lookback_hours(config, previous_now)로 그 시점 기준 계산.
    이렇게 하면 어제 24h 수집분에 어제 24h 필터를 적용하게 되어 diff가 정확해진다.

    Args:
        config: 설정 (원본 config, lookback_hours 168로 교체되지 않음)
        previous_activities: 이전 raw로부터 로드한 activities

    Returns:
        그룹핑된 기능 그룹들
    """
    previous_now = max(a.collected_at for a in previous_activities)

    # 이전 시점 기준 lookback_hours 계산 (그 시점의 직전 영업일 규칙)
    previous_lookback = resolve_lookback_hours(config, previous_now)

    # 이전 시점 기준으로 필터링
    activities_to_group = filter_activities_to_window(
        previous_activities, previous_lookback, previous_now
    )

    groups, _, _, _ = group_activities(
        activities=activities_to_group, config=config, now=previous_now
    )
    return groups


def _compute_diff_summary(
    config: Config,
    today_groups: tuple[FeatureGroup, ...],
    report_date: date,
) -> DiffSummary | None:
    """전일(가장 최근 과거) raw가 있으면 diff 요약을 계산한다. 없으면 None (G1).

    previous_activities의 필터링은 _group_previous_activities 내부에서
    collected_at 기준으로 자동 수행된다. 오늘 now를 주입하면 안 된다.

    Args:
        config: 설정
        today_groups: 현재의 그룹들
        report_date: 리포트 날짜

    Returns:
        DiffSummary 또는 None
    """
    prev_raw_result = find_previous_raw_dir(config.data_dir, report_date)
    if not prev_raw_result:
        return None
    prev_date, prev_raw_dir = prev_raw_result

    previous_activities = load_previous_activities(prev_raw_dir)
    if not previous_activities:
        return None

    previous_groups = _group_previous_activities(config, previous_activities)
    new_groups, stage_changes = compute_diff(today_groups, previous_groups)

    # 데이터 기준일 사상
    previous_now = max(a.collected_at for a in previous_activities)
    compared_date = _map_raw_date_to_data_basis(prev_date, previous_now)

    logger.info(
        "diff 완료 (수집: %s, 데이터기준: %s): 신규=%d건, 변화=%d건",
        prev_date,
        compared_date,
        len(new_groups),
        len(stage_changes),
    )
    return DiffSummary(
        compared_to=compared_date,
        new_groups=new_groups,
        stage_changes=stage_changes,
    )


@dataclass(frozen=True)
class PipelineContext:
    """파이프라인 1회 실행의 기준 시각과 조회 폭."""

    now: datetime
    report_date: date
    weekly_end: datetime  # 주간 창의 끝 — 주간 HTML 을 쓰는 실행은 그 주 월요일 00:00, 아니면 now
    collection_hours: int  # 수집 폭: 일간 창과 주간 창(weekly_end − 168h ~ now)을 모두 덮는다
    daily_hours: int  # 일간 필터 폭 (직전 영업일 규칙)


def _prepare_pipeline_context(
    config: Config,
    now_override: datetime | None = None,
    weekly_window_end: datetime | None = None,
) -> PipelineContext:
    """파이프라인 실행 컨텍스트를 준비하고 로깅한다.

    주간 필터·주간 config는 계속 WEEKLY_LOOKBACK_HOURS(168h)를 쓴다.
    수집 폭은 올림(ceil)으로 잡는다 — 내림이면 화 14:30 실행이 지난주 월 00:00~00:30 을 놓친다.

    Args:
        config: 설정
        now_override: 기준 시각 오버라이드 (None이면 현재 시각 사용)
        weekly_window_end: 주간 대시보드 창의 끝 (None이면 now — 롤링 168h). now 이하여야 한다

    Returns:
        수집 폭·일간 폭·주간 창 끝이 담긴 컨텍스트
    """
    now = now_override if now_override else get_effective_now(config)
    report_date = report_date_from_now(now)
    weekly_end = weekly_window_end if weekly_window_end is not None else now
    daily_hours = resolve_lookback_hours(config, now)
    weekly_collection_hours = WEEKLY_LOOKBACK_HOURS + ceil((now - weekly_end) / timedelta(hours=1))
    collection_hours = max(daily_hours, weekly_collection_hours)
    logger.info(
        "파이프라인 시작: now=%s, weekly_end=%s, collection=%dh, weekly_filter=%dh, "
        "daily_filter=%dh, tz=%s",
        now.isoformat(),
        weekly_end.isoformat(),
        collection_hours,
        WEEKLY_LOOKBACK_HOURS,
        daily_hours,
        config.timezone_name,
    )
    for warning in calendar_warnings(config, _local_date(config, now)):
        logger.warning("%s", warning)
    return PipelineContext(
        now=now,
        report_date=report_date,
        weekly_end=weekly_end,
        collection_hours=collection_hours,
        daily_hours=daily_hours,
    )


def _history_requests(
    activities: tuple[RepoActivity, ...],
    store: BranchHistoryStore,
) -> dict[str, tuple[BranchHistoryRequest, ...]]:
    """활동 브랜치 중 히스토리 재조회가 필요한 것만 골라낸다.

    head SHA는 이미 수집된 active_branches에서 얻으므로 판정에 추가 API 호출이 없다.
    캐시된 SHA와 같으면 과거는 변하지 않았으므로 조회를 건너뛴다.
    """
    entries = entries_as_dict(store)
    requests: dict[str, tuple[BranchHistoryRequest, ...]] = {}

    for activity in activities:
        if activity.status != "ok":
            continue
        targets = [
            BranchHistoryRequest(branch_name=branch.name, head_sha=branch.last_commit_sha)
            for branch in activity.active_branches
            if needs_refresh(
                entries.get(history_key(activity.repo.full_path, branch.name)),
                branch.last_commit_sha,
            )
        ]
        if targets:
            requests[activity.repo.full_path] = tuple(targets)

    return requests


def _update_branch_histories(
    config: Config,
    activities: tuple[RepoActivity, ...],
    store: BranchHistoryStore,
    run_date: date,
    now: datetime,
    persist_state: bool,
) -> BranchHistoryStore:
    """변경된 브랜치만 히스토리를 조회해 저장소를 갱신한다."""
    requests = _history_requests(activities, store)
    if not requests:
        logger.info("브랜치 히스토리: 변경된 브랜치 없음 — 조회 생략")
        return store

    target_count = sum(len(items) for items in requests.values())
    logger.info("브랜치 히스토리: %d개 브랜치 조회", target_count)

    fetched = collect_histories(config, requests, config.history.max_history_commits)
    updated = store
    for repo_full_path, fetches in fetched.items():
        updated = update_history_store(updated, repo_full_path, fetches, run_date, updated_at=now)

    if persist_state:
        save_optional_state(
            "브랜치 히스토리",
            lambda: save_history_store(updated, history_store_path(config.data_dir)),
        )
    return updated


def _history_branch_candidates(group: FeatureGroup) -> tuple[str, ...]:
    """그룹의 대표 브랜치 후보를 우선순위대로 만든다.

    실측(2026-07-27)에서 세 경우가 모두 나타났다:
    1. branch_names에 명시된 경우
    2. branch_names가 비고 group.name이 브랜치명인 경우 (6차 등록부도 이 키를 쓴다)
    3. 둘 다 브랜치가 아닌 경우 — 디렉터리·라벨 규칙으로 묶인 그룹. 이때는 커밋이
       올라간 브랜치를 커밋 수가 많은 순으로 후보에 넣는다(가장 큰 그룹이 이 경우였다).
    """
    candidates = list(group.branch_names)
    if group.name not in candidates:
        candidates.append(group.name)

    commit_branches = Counter(commit.branch for commit in group.commits if commit.branch)
    for branch_name, _count in commit_branches.most_common():
        if branch_name not in candidates:
            candidates.append(branch_name)

    return tuple(candidates)


def _reconcile_lifecycle_start(
    lifecycle: GroupLifecycleView | None,
    history: BranchHistoryView,
) -> GroupLifecycleView | None:
    """수명주기 시작일을 브랜치 생애 이력으로 보정한다 (순수).

    등록부의 first_seen은 도구가 그룹을 처음 관측한 날이라 관측 시작 이전의 작업을
    알지 못한다. 브랜치 이력이 더 이른 작업 시작일을 알면 그쪽이 진실이다 —
    보정하지 않으면 관측 기준 "11일째"와 실작업 기준 "24일차"가 한 seed에 공존한다.
    """
    if lifecycle is None or history.started_on >= lifecycle.first_seen:
        return lifecycle
    return replace(lifecycle, first_seen=history.started_on, total_days=history.total_days)


def _join_branch_history(
    groups: tuple[FeatureGroup, ...],
    store: BranchHistoryStore,
    today: date,
    min_tag_coverage: float,
) -> tuple[FeatureGroup, ...]:
    """기능 그룹에 브랜치 생애 히스토리 뷰를 조인한다.

    라인 그룹에는 조인하지 않는다 — 상시 존재하는 통로에는 "며칠째 진행"이라는
    누적 서사가 의미를 갖지 않는다(6차에서 확인).
    그룹의 브랜치 중 저장소에 기록이 있는 첫 번째를 대표로 삼는다.
    조인하면서 수명주기 시작일도 이력 기준으로 보정한다.
    """
    entries = entries_as_dict(store)
    joined: list[FeatureGroup] = []

    for group in groups:
        if group.group_kind == "line":
            joined.append(group)
            continue
        view = None
        for branch_name in _history_branch_candidates(group):
            entry = entries.get(history_key(group.repo_full_path, branch_name))
            if entry:
                view = build_history_view(entry, today, min_tag_coverage)
                break
        if view is None:
            joined.append(group)
            continue
        joined.append(
            replace(
                group,
                branch_history=view,
                lifecycle=_reconcile_lifecycle_start(group.lifecycle, view),
            )
        )

    return tuple(joined)


def run_pipeline(
    config: Config,
    now_override: datetime | None = None,
    persist_state: bool = True,
    weekly_window_end: datetime | None = None,
) -> tuple[DashboardModel, DashboardModel]:
    """전체 파이프라인 실행: 수집 → raw 저장 → 그룹핑 → diff → 조립 → 보존 정리 (G2, G3).

    config는 용도별로 분리:
    - collection_config: 수집용 (일간 창과 주간 창을 모두 덮는 폭)
    - daily_config: 일간 분석용 (직전 영업일부터, 평일 24h)
    - weekly_config: 주간 분석용 (168h)

    주간 신규 브랜치는 스냅샷 비교로 주입 (G3).

    Args:
        config: 설정
        now_override: 기준 시각 오버라이드 (None이면 현재 시각 사용). 이름표(report_date)·
            수명주기 등록부·일간 스파크라인·오늘 스냅샷이 모두 이 값에 묶인다
        persist_state: False면 raw·브랜치 스냅샷·수명주기 등록부·브랜치 이력 저장과 보존 정리를
            모두 건너뛴다. ad-hoc 조회와 주간 강제 재발행(plan_collect 가 persist_state=False 로
            정한 경우)에서 쓰인다
        weekly_window_end: 주간 대시보드 창의 끝(그 주 월요일 00:00). None 이면 now(롤링 168h —
            레거시·비발행). now 이하여야 한다. 등록부 갱신·일간 스파크라인은 이 값과 무관하게
            now 기준 롤링 168h 를 쓴다

    Returns:
        (daily_dashboard, weekly_dashboard)
    """
    ctx = _prepare_pipeline_context(config, now_override, weekly_window_end)
    now, report_date = ctx.now, ctx.report_date
    weekly_lookback_hours = WEEKLY_LOOKBACK_HOURS
    daily_lookback_hours = ctx.daily_hours

    # G2: 수집용 config (일간 창과 주간 창을 모두 덮는 폭)
    collection_config = replace(config, lookback_hours=ctx.collection_hours)
    activities = _collect_activities(collection_config, now, save_snapshots=persist_state)
    if persist_state:
        _save_raw_activities(activities, config.data_dir)

    # G2: 일간 분석용 config (직전 영업일부터)
    daily_config = replace(config, lookback_hours=daily_lookback_hours)

    # G2: 주간 분석용 config (168h)
    weekly_config = replace(config, lookback_hours=weekly_lookback_hours)

    # 주간 대시보드 (168h 필터링) — 신규 작업 신호는 스냅샷 비교로 별도 생성하므로 버린다
    weekly_activities = filter_activities_to_window(activities, weekly_lookback_hours, now)
    weekly_groups, weekly_warnings, _, weekly_unclassified_ratio = group_activities(
        activities=weekly_activities, config=weekly_config, now=now
    )

    # 주간 그룹 히스토그램 맵 생성 (일간 조인용) + 그룹에 histogram 주입 (등록부 갱신용)
    weekly_histogram_map: dict[tuple[str, str], tuple[tuple[str, int], ...]] = {}
    weekly_groups_enriched = _enrich_groups_with_histogram(weekly_groups, report_date)
    for group in weekly_groups_enriched:
        key = (group.repo_full_path, group.name)
        histogram = group.daily_commit_counts or ()
        weekly_histogram_map[key] = histogram

    # Phase A: 수명주기 등록부 갱신 (lifecycle.enabled가 True일 때만)
    # 이 시점에서 weekly_groups_enriched는 daily_commit_counts가 주입됨
    today = report_date
    lifecycle_registry = load_registry(registry_path(config.data_dir))
    lifecycle_config = getattr(config, "lifecycle", None)
    if lifecycle_config and lifecycle_config.enabled:
        lifecycle_registry = update_registry(
            lifecycle_registry, weekly_groups_enriched, today, updated_at=now
        )
        if persist_state:
            save_optional_state(
                "수명주기 등록부",
                lambda: save_registry(lifecycle_registry, registry_path(config.data_dir)),
            )

    # Phase B: 릴리스 열차 계산 (레포별 recent_merge_requests에서 사다리 유도)
    repo_release_trains: list[tuple[str, ReleaseTrain]] = []
    for activity in activities:
        if activity.status == "ok":
            train = build_release_train(
                activity.recent_merge_requests, config.grouping_hints.release_line_patterns
            )
            repo_release_trains.append((activity.repo.full_path, train))

    # Phase C: 브랜치 생애 히스토리 (history.enabled가 True일 때만)
    history_store = load_history_store(history_store_path(config.data_dir))
    history_config = getattr(config, "history", None)
    if history_config and history_config.enabled:
        history_store = _update_branch_histories(
            config, activities, history_store, today, now, persist_state
        )

    # 발행 주간은 달력 주 창 [weekly_end − 168h, weekly_end] 로 다시 묶는다.
    # 위 롤링 그룹(now 기준)은 수명주기 등록부 갱신과 일간 스파크라인 조인 전용이다.
    if ctx.weekly_end != now:
        weekly_groups, weekly_warnings, _, weekly_unclassified_ratio = group_activities(
            activities=filter_activities_to_window(
                activities, weekly_lookback_hours, ctx.weekly_end
            ),
            config=weekly_config,
            now=ctx.weekly_end,
        )

    # 주간 그룹(원본 — histogram 주입 전)에 lifecycle 뷰 조인
    weekly_groups_with_lifecycle = []
    for group in weekly_groups:
        group_key = f"{group.repo_full_path}::{group.name}"
        lifecycle_view = build_lifecycle_view(lifecycle_registry, group_key, today)
        updated_group = replace(group, lifecycle=lifecycle_view)
        weekly_groups_with_lifecycle.append(updated_group)
    weekly_groups = _join_branch_history(
        tuple(weekly_groups_with_lifecycle),
        history_store,
        today,
        history_config.min_tag_coverage if history_config else 0.5,
    )

    # 일간 대시보드 (직전 영업일부터 필터링)
    daily_activities = filter_activities_to_window(activities, daily_lookback_hours, now)
    daily_groups, warnings, new_work, unclassified_ratio = group_activities(
        activities=daily_activities, config=daily_config, now=now
    )
    # 원본 config 를 넘긴다 — 이전 raw 의 창은 그 수집 시점의 규칙값으로 다시 계산해야 하는데,
    # daily_config 는 lookback_hours 가 오늘의 일간 폭으로 덮여 있고 그 값이 하한으로 쓰이면
    # 이전 창이 오늘 폭 이상으로 부풀어 「신규/변화」가 과소 집계된다
    diff_summary = _compute_diff_summary(config, daily_groups, report_date)

    # 일간 그룹에도 lifecycle 뷰 조인
    daily_groups_with_lifecycle = []
    for group in daily_groups:
        group_key = f"{group.repo_full_path}::{group.name}"
        lifecycle_view = build_lifecycle_view(lifecycle_registry, group_key, today)
        updated_group = replace(group, lifecycle=lifecycle_view)
        daily_groups_with_lifecycle.append(updated_group)
    daily_groups = _join_branch_history(
        tuple(daily_groups_with_lifecycle),
        history_store,
        today,
        history_config.min_tag_coverage if history_config else 0.5,
    )

    daily_dashboard = build_dashboard_model(
        groups=daily_groups,
        warnings=warnings,
        new_work=new_work,
        unclassified_ratio=unclassified_ratio,
        activities=daily_activities,
        config=daily_config,
        report_date=report_date,
        now=now,
        diff=diff_summary,
        period="daily",
        weekly_histogram_map=weekly_histogram_map,
        repo_release_trains=tuple(repo_release_trains),
    )

    # G3: 주간 신규 브랜치를 스냅샷 비교로 주입 (창 끝 날짜 기준)
    weekly_end_date = ctx.weekly_end.date()
    baseline_map, baseline_date_for_display = find_weekly_baseline_snapshots(
        config, weekly_end_date
    )
    activities_with_weekly_branches = weekly_created_branches(
        config, activities, weekly_end_date, baseline_map
    )

    # 주간 신규 작업 신호 생성 (updated activities 사용 → created_branches는 주간 스냅샷 비교 결과)
    weekly_new_work = tuple(
        generate_new_work_signals(
            activities_with_weekly_branches, ctx.weekly_end, lookback_hours=WEEKLY_LOOKBACK_HOURS
        )
    )

    weekly_dashboard = build_dashboard_model(
        groups=weekly_groups,
        warnings=weekly_warnings,
        new_work=weekly_new_work,
        unclassified_ratio=weekly_unclassified_ratio,
        activities=activities,
        config=weekly_config,
        report_date=report_date,
        now=ctx.weekly_end,
        diff=None,  # 주간 뷰는 diff 없음
        period="weekly",
        new_work_baseline_date=baseline_date_for_display,
        repo_release_trains=tuple(repo_release_trains),
    )

    if persist_state:
        cleanup_retention(config.data_dir, config.retention_days, report_date, config.output_dir)
    logger.info("파이프라인 완주 (일간+주간)")
    return daily_dashboard, weekly_dashboard
