"""YAML 설정 파일 로딩 및 검증."""

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from pulse.business_calendar import DEFAULT_HOLIDAY_CALENDAR, HOLIDAY_CALENDARS, HolidayCalendar
from pulse.models import RepoRef

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 24
WEEKEND_LOOKBACK_HOURS = 72
DEFAULT_TIMEZONE = "Asia/Seoul"
DEFAULT_RETENTION_DAYS = 90
DEFAULT_REVIEW_WAITING_DAYS = 3
DEFAULT_NO_PUSH_DAYS = 7
DEFAULT_RELEASE_LINE_PATTERNS = (
    "main",
    "master",
    "develop",
    "dev",
    "test",
    "sqa",
    "devqa",
    "release",
    "hotfix",
)
DEFAULT_RECENT_MR_LIMIT = 50
DEFAULT_MAX_HISTORY_COMMITS = 1000  # 브랜치당 히스토리 수집 상한 (오래된 브랜치 폭주 방지)
DEFAULT_MIN_TAG_COVERAGE = 0.5  # 태그 구성 UI를 표시할 최소 인식률
# date.fromisoformat 은 3.11부터 "20261002" 같은 다른 표기도 받는다 —
# 지원 하한(3.10)과 같은 엄격함을 유지해 파이썬 버전에 따라 설정 해석이 달라지지 않게 한다
ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class ConfigError(Exception):
    """config.yaml 로딩/검증 실패. 메시지에 필드 경로와 원인을 포함한다."""

    pass


@dataclass(frozen=True)
class IssueTracking:
    """이슈 추적 설정 (선택)."""

    url_template: str | None = None  # "https://jira.example.com/browse/{key}"


@dataclass(frozen=True)
class LifecycleConfig:
    """수명주기 등록부 설정 (선택)."""

    enabled: bool = True
    recent_mr_limit: int = DEFAULT_RECENT_MR_LIMIT


@dataclass(frozen=True)
class HistoryConfig:
    """브랜치 생애 히스토리 설정 (선택).

    max_history_commits는 브랜치당 수집 상한 — 1년 전 갈라진 브랜치가 활동을 재개하면
    히스토리가 수천 건이 될 수 있다. 상한 도달은 "N건 이상"으로 표시하고 경고를 남긴다.
    min_tag_coverage 미만이면 태그 구성 UI를 렌더하지 않는다(자유 서술 관례 레포).
    """

    enabled: bool = True
    max_history_commits: int = DEFAULT_MAX_HISTORY_COMMITS
    min_tag_coverage: float = DEFAULT_MIN_TAG_COVERAGE


@dataclass(frozen=True)
class StagnationThresholds:
    """정체 감지 임계값."""

    review_waiting_days: int = DEFAULT_REVIEW_WAITING_DAYS
    no_push_days: int = DEFAULT_NO_PUSH_DAYS


@dataclass(frozen=True)
class GroupingHints:
    """그룹핑 수동 힌트 (dict 입력을 tuple 쌍으로 변환)."""

    branch_prefixes: tuple[tuple[str, str], ...] = ()
    directories: tuple[tuple[str, str], ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    release_line_patterns: tuple[str, ...] = DEFAULT_RELEASE_LINE_PATTERNS


@dataclass(frozen=True)
class Config:
    """검증된 설정."""

    team_name: str
    repos: tuple[RepoRef, ...]
    lookback_hours: int
    weekend_catchup: bool
    timezone_name: str
    output_dir: Path
    data_dir: Path
    stagnation: StagnationThresholds
    exclude_bot_authors: tuple[str, ...]
    retention_days: int
    grouping_hints: GroupingHints
    issue_tracking: IssueTracking = field(default_factory=lambda: IssueTracking())
    lifecycle: LifecycleConfig = field(default_factory=lambda: LifecycleConfig())
    history: HistoryConfig = field(default_factory=lambda: HistoryConfig())
    extra_holidays: tuple[date, ...] = ()  # 내장 공휴일 표에 없는 휴무일 (임시공휴일·회사 휴무)
    # kr: 내장 한국 공휴일 표를 쓴다, none: 표를 쓰지 않는다 (휴무일은 주말과 extra_holidays 만)
    holiday_calendar: HolidayCalendar = DEFAULT_HOLIDAY_CALENDAR


def _require_str(data: Any, key: str) -> str:
    """dict에서 문자열 필드를 추출한다. 없거나 타입이 다르면 에러."""
    if not isinstance(data, dict):
        raise ConfigError(f"{key}: dict이어야 합니다")
    value = data.get(key)
    if value is None:
        raise ConfigError(f"{key}: 필수 필드입니다")
    if not isinstance(value, str):
        raise ConfigError(f"{key}: 문자열이어야 합니다")
    return value


def _optional_positive_int(data: Any, key: str, default: int) -> int:
    """dict에서 양수 정수 필드를 추출한다. 없으면 기본값."""
    if not isinstance(data, dict):
        return default
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key}: 양수이어야 합니다")
    return value


def _optional_bool(data: Any, key: str, default: bool) -> bool:
    """dict에서 boolean 필드를 추출한다. 없으면 기본값."""
    if not isinstance(data, dict):
        return default
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{key}: 불린이어야 합니다")
    return value


def _optional_ratio(data: Any, key: str, default: float) -> float:
    """dict에서 0.0~1.0 범위의 비율 필드를 추출한다. 없으면 기본값."""
    if not isinstance(data, dict):
        return default
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key}: 0.0~1.0 사이의 숫자이어야 합니다")
    if not 0.0 <= float(value) <= 1.0:
        raise ConfigError(f"{key}: 0.0~1.0 사이의 숫자이어야 합니다")
    return float(value)


def _optional_list_str(data: Any, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """dict에서 문자열 리스트 필드를 추출한다. 없으면 기본값. tuple로 변환."""
    if not isinstance(data, dict):
        return default
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, list):
        raise ConfigError(f"{key}: 리스트이어야 합니다")
    if not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{key}: 모든 항목이 문자열이어야 합니다")
    return tuple(value)


def _parse_iso_date(value: Any) -> date | None:
    """YAML이 파싱한 날짜 또는 YYYY-MM-DD 문자열을 date로 바꾼다. 그 외는 None.

    PyYAML은 따옴표 없는 2026-10-02 를 date로 만든다. 시각이 붙은 값은 datetime
    (date의 하위 클래스)이라 먼저 걸러야 시각이 조용히 버려지지 않는다.
    """
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str) and ISO_DATE_PATTERN.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _optional_date_list(data: Any, key: str) -> tuple[date, ...]:
    """YYYY-MM-DD 목록 필드를 date 튜플로 읽는다. 없으면 빈 튜플."""
    if not isinstance(data, dict):
        return ()
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{key}: 리스트이어야 합니다")
    parsed: list[date] = []
    for index, item in enumerate(value):
        parsed_date = _parse_iso_date(item)
        if parsed_date is None:
            raise ConfigError(f"{key}[{index}]: YYYY-MM-DD 형식이어야 합니다: {item!r}")
        parsed.append(parsed_date)
    return tuple(parsed)


def _optional_holiday_calendar(data: dict[str, Any]) -> HolidayCalendar:
    """holiday_calendar 를 읽는다. 키가 없으면 kr, 허용값이 아니면(null 포함) ConfigError."""
    if "holiday_calendar" not in data:
        return DEFAULT_HOLIDAY_CALENDAR
    value = data["holiday_calendar"]
    for calendar in HOLIDAY_CALENDARS:
        if value == calendar:
            return calendar
    allowed = " 또는 ".join(repr(name) for name in HOLIDAY_CALENDARS)
    raise ConfigError(f"holiday_calendar: {allowed} 이어야 합니다: {value!r}")


def _dict_to_tuples(d: Any) -> tuple[tuple[str, str], ...]:
    """dict를 tuple 쌍으로 변환한다. 타입 검증 포함."""
    if not isinstance(d, dict):
        return ()
    items = []
    for k, v in d.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ConfigError("grouping_hints의 모든 항목이 문자열 → 문자열이어야 합니다")
        items.append((k, v))
    return tuple(items)


def _parse_full_url(entry: str) -> RepoRef:
    """전체 URL을 파싱해 RepoRef를 반환한다."""
    parsed = urlsplit(entry)
    netloc = parsed.netloc
    path = parsed.path.strip("/")

    # .git 접미사 제거
    if path.endswith(".git"):
        path = path[:-4]

    path_parts = path.split("/")
    if len(path_parts) < 2:
        raise ConfigError("레포 URL의 경로 부분이 최소 namespace/name 형식이어야 합니다")

    namespace = path_parts[0]
    name = path_parts[1]
    provider: Any = "github" if netloc == "github.com" else "gitlab"
    base_url = f"{parsed.scheme}://{netloc}"
    web_url = f"{base_url}/{namespace}/{name}"

    return RepoRef(
        provider=provider,
        base_url=base_url,
        namespace=namespace,
        name=name,
        web_url=web_url,
    )


def _parse_short_repo(entry: str, default_gitlab_url: str | None) -> RepoRef:
    """축약형 repo (namespace/name)를 파싱한다."""
    if default_gitlab_url is None:
        raise ConfigError("전체 URL이 아니면 최상위 gitlab_url이 필요합니다")
    parts = entry.split("/", 1)
    namespace, name = parts[0], parts[1]
    return RepoRef(
        provider="gitlab",
        base_url=default_gitlab_url,
        namespace=namespace,
        name=name,
        web_url=f"{default_gitlab_url}/{namespace}/{name}",
    )


def _parse_subtree_path(raw: Any) -> str | None:
    """subtree_path 선택 필드를 검증·정규화한다. 미설정/빈 값이면 None.

    정규화: 선행·후행 '/' 제거. provider(gitlab 전용) 검증은 URL 파싱 후
    repo.provider를 알아야 하므로 이 함수가 아니라 _parse_repo_entry에서 수행한다.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ConfigError("subtree_path: 문자열이어야 합니다")

    value = raw.strip()
    if not value:
        return None

    if "/-/" in value:
        raise ConfigError(
            "subtree_path: 웹 URL이 아니라 디렉토리 경로만 적으세요 (예: 'sample-model')"
        )

    normalized = value.strip("/")
    if not normalized:
        return None
    if ".." in normalized.split("/"):
        raise ConfigError("subtree_path: '..' 세그먼트를 포함할 수 없습니다")

    return normalized


def _parse_repo_entry(entry: str | dict[str, Any], gitlab_url: str | None) -> RepoRef:
    """문자열 또는 dict 형식의 레포 항목을 파싱하여 RepoRef 반환."""
    if isinstance(entry, str):
        # 문자열 형식 (기존 호환)
        url = entry
        nickname = None
        base_branch = None
        subtree_path = None
    elif isinstance(entry, dict):
        # dict 형식 (신규)
        url = _require_str(entry, "url")
        nickname = entry.get("nickname")
        if nickname is not None and not isinstance(nickname, str):
            raise ConfigError("nickname: 문자열이어야 합니다")
        # 공백 처리: strip 후 빈 문자열이면 None
        if nickname is not None:
            nickname = nickname.strip()
            if not nickname:
                nickname = None
        base_branch = entry.get("base_branch")
        if base_branch is not None and not isinstance(base_branch, str):
            raise ConfigError("base_branch: 문자열이어야 합니다")
        if base_branch is not None:
            base_branch = base_branch.strip() or None
        subtree_path = _parse_subtree_path(entry.get("subtree_path"))
    else:
        raise ConfigError("문자열 또는 dict이어야 합니다")

    # URL 파싱
    if url.startswith(("http://", "https://")):
        repo = _parse_full_url(url)
    elif "/" in url:
        repo = _parse_short_repo(url, gitlab_url)
    else:
        raise ConfigError("알 수 없는 레포 형식")

    if subtree_path is not None and repo.provider != "gitlab":
        # 조용히 무시하면 "범위가 좁혀진 줄 알고 전체 데이터를 보는" 최악의 실패가 난다.
        raise ConfigError(
            "subtree_path: GitLab 레포에서만 지원합니다 (provider가 gitlab이 아닙니다)"
        )

    # 선택 필드 반영 (URL 파싱 결과에 덧붙인다)
    if nickname:
        repo = replace(repo, nickname=nickname)
    if base_branch:
        repo = replace(repo, base_branch=base_branch)
    if subtree_path:
        repo = replace(repo, subtree_path=subtree_path)

    return repo


def _load_repos(data: Any, gitlab_url: str | None) -> tuple[RepoRef, ...]:
    """repos 필드를 로드하고 검증한다. 문자열/dict 혼합 지원."""
    repos_raw = data.get("repos")
    if not isinstance(repos_raw, list) or len(repos_raw) == 0:
        raise ConfigError("repos: 최소 1개 이상의 레포가 필요합니다")

    repos = []
    for i, entry in enumerate(repos_raw):
        try:
            repo = _parse_repo_entry(entry, gitlab_url)
            repos.append(repo)
        except ConfigError as error:
            raise ConfigError(f"repos[{i}]: {error}") from error

    return tuple(repos)


def _validate_timezone(name: str) -> str:
    """timezone 필드를 검증한다."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ConfigError(f"timezone: 알 수 없는 시간대입니다: {name!r}") from error
    return name


def _load_stagnation(data: Any) -> StagnationThresholds:
    """stagnation_thresholds 필드를 로드한다."""
    stagnation_data = data.get("stagnation_thresholds", {})
    if not isinstance(stagnation_data, dict):
        raise ConfigError("stagnation_thresholds: dict이어야 합니다")
    review_waiting = _optional_positive_int(
        stagnation_data, "review_waiting_days", DEFAULT_REVIEW_WAITING_DAYS
    )
    no_push = _optional_positive_int(stagnation_data, "no_push_days", DEFAULT_NO_PUSH_DAYS)
    return StagnationThresholds(review_waiting_days=review_waiting, no_push_days=no_push)


def _load_grouping_hints(data: Any) -> GroupingHints:
    """grouping_hints 필드를 로드한다."""
    hints_data = data.get("grouping_hints", {})
    if not isinstance(hints_data, dict):
        raise ConfigError("grouping_hints: dict이어야 합니다")

    branch_prefixes = _dict_to_tuples(hints_data.get("branch_prefixes", {}))
    directories = _dict_to_tuples(hints_data.get("directories", {}))
    labels = _dict_to_tuples(hints_data.get("labels", {}))
    release_line_patterns = _optional_list_str(
        hints_data,
        "release_line_patterns",
        DEFAULT_RELEASE_LINE_PATTERNS,
    )
    return GroupingHints(
        branch_prefixes=branch_prefixes,
        directories=directories,
        labels=labels,
        release_line_patterns=release_line_patterns,
    )


def _load_issue_tracking(data: Any) -> IssueTracking:
    """issue_tracking 필드를 로드한다 (선택)."""
    tracking_data = data.get("issue_tracking", {})
    if not isinstance(tracking_data, dict):
        return IssueTracking()
    url_template = tracking_data.get("url_template")
    if url_template is not None and not isinstance(url_template, str):
        raise ConfigError("issue_tracking.url_template: 문자열이어야 합니다")
    return IssueTracking(url_template=url_template)


def _load_lifecycle(data: Any) -> LifecycleConfig:
    """lifecycle 필드를 로드한다 (선택)."""
    lifecycle_data = data.get("lifecycle", {})
    if not isinstance(lifecycle_data, dict):
        return LifecycleConfig()
    enabled = _optional_bool(lifecycle_data, "enabled", True)
    recent_mr_limit = _optional_positive_int(
        lifecycle_data, "recent_mr_limit", DEFAULT_RECENT_MR_LIMIT
    )
    return LifecycleConfig(enabled=enabled, recent_mr_limit=recent_mr_limit)


def _load_history(data: Any) -> HistoryConfig:
    """history 필드를 로드한다 (선택)."""
    history_data = data.get("history", {})
    if not isinstance(history_data, dict):
        return HistoryConfig()
    return HistoryConfig(
        enabled=_optional_bool(history_data, "enabled", True),
        max_history_commits=_optional_positive_int(
            history_data, "max_history_commits", DEFAULT_MAX_HISTORY_COMMITS
        ),
        min_tag_coverage=_optional_ratio(
            history_data, "min_tag_coverage", DEFAULT_MIN_TAG_COVERAGE
        ),
    )


def _load_raw_yaml(path: Path) -> dict[str, Any]:
    """파일에서 YAML을 로드하고 dict 타입을 확인한다."""
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")

    try:
        with open(path) as f:
            raw_data = yaml.safe_load(f)
    except yaml.YAMLError as error:
        raise ConfigError(f"YAML 파싱 오류: {error}") from error

    if not isinstance(raw_data, dict):
        raise ConfigError("설정의 최상위는 dict이어야 합니다")
    return raw_data


def _load_output_paths(data: Any) -> tuple[Path, Path]:
    """output_dir과 data_dir을 로드한다."""
    output_dir_str: str | None = data.get("output_dir")
    output_dir = Path(output_dir_str) if output_dir_str else Path("./reports")

    data_dir_str: str | None = data.get("data_dir")
    data_dir = Path(data_dir_str) if data_dir_str else Path("./data")
    return output_dir, data_dir


def _warn_unknown_keys(data: dict[str, Any]) -> None:
    """알 수 없는 설정 키에 대해 경고한다."""
    known_keys = {
        "team_name",
        "gitlab_url",
        "repos",
        "lookback_hours",
        "weekend_catchup",
        "timezone",
        "output_dir",
        "data_dir",
        "stagnation_thresholds",
        "exclude_bot_authors",
        "retention_days",
        "grouping_hints",
        "issue_tracking",
        "lifecycle",
        "history",
        "extra_holidays",
        "holiday_calendar",
    }
    for key in data:
        if key not in known_keys:
            logger.warning("알 수 없는 설정 키를 무시합니다: %s", key)


def _load_required_fields(data: Any) -> tuple[str, str | None, tuple[RepoRef, ...]]:
    """필수 필드(team_name, gitlab_url, repos)를 로드한다."""
    team_name = _require_str(data, "team_name")
    if not team_name:
        raise ConfigError("team_name: 비어있지 않아야 합니다")

    gitlab_url: str | None = data.get("gitlab_url")
    repos = _load_repos(data, gitlab_url)
    return team_name, gitlab_url, repos


def _load_optional_fields(data: Any) -> tuple[int, bool, str, tuple[str, ...], int]:
    """선택 필드를 로드한다."""
    lookback_hours = _optional_positive_int(data, "lookback_hours", DEFAULT_LOOKBACK_HOURS)
    weekend_catchup = _optional_bool(data, "weekend_catchup", True)
    timezone_name = _validate_timezone(data.get("timezone", DEFAULT_TIMEZONE))
    exclude_bot_authors = _optional_list_str(data, "exclude_bot_authors", ())
    retention_days = _optional_positive_int(data, "retention_days", DEFAULT_RETENTION_DAYS)
    return lookback_hours, weekend_catchup, timezone_name, exclude_bot_authors, retention_days


def load_config(path: Path) -> Config:
    """config.yaml을 읽어 검증된 Config를 반환한다. 실패 시 ConfigError."""
    raw_data = _load_raw_yaml(path)

    team_name, gitlab_url, repos = _load_required_fields(raw_data)
    lookback_hours, weekend_catchup, timezone_name, exclude_bot_authors, retention_days = (
        _load_optional_fields(raw_data)
    )

    output_dir, data_dir = _load_output_paths(raw_data)
    stagnation = _load_stagnation(raw_data)
    grouping_hints = _load_grouping_hints(raw_data)
    issue_tracking = _load_issue_tracking(raw_data)
    lifecycle = _load_lifecycle(raw_data)
    history = _load_history(raw_data)
    extra_holidays = _optional_date_list(raw_data, "extra_holidays")
    holiday_calendar = _optional_holiday_calendar(raw_data)

    _warn_unknown_keys(raw_data)

    return Config(
        team_name=team_name,
        repos=repos,
        lookback_hours=lookback_hours,
        weekend_catchup=weekend_catchup,
        timezone_name=timezone_name,
        output_dir=output_dir,
        data_dir=data_dir,
        stagnation=stagnation,
        exclude_bot_authors=exclude_bot_authors,
        retention_days=retention_days,
        grouping_hints=grouping_hints,
        issue_tracking=issue_tracking,
        lifecycle=lifecycle,
        history=history,
        extra_holidays=extra_holidays,
        holiday_calendar=holiday_calendar,
    )
