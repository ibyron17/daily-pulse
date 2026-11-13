"""레이어 간 정규화 데이터 모델."""

import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Provider = Literal["gitlab", "github"]
CollectionStatus = Literal["ok", "failed"]
MRState = Literal["open", "merged", "closed"]
ReviewKind = Literal["approved", "changes_requested", "commented"]
GroupSourceRule = Literal[
    "hints", "branch", "label", "directory", "scope", "branch-name", "unclassified"
]
FeatureStage = Literal["developing", "reviewing", "merged", "other"]
WarningKind = Literal[
    "stale_mr", "stale_branch", "revert_commit", "hotfix_commit", "collection_failure"
]

# 의미 있는 단계: diff 필터링에 사용 (other는 분류 불가 상태이므로 제외)
MEANINGFUL_STAGES = {"developing", "reviewing", "merged"}


@dataclass(frozen=True)
class TaskSummary:
    """기능 그룹의 작업 내용 정리 (표시 포맷은 renderer 소관)."""

    commit_titles: tuple[str, ...]
    open_mr_titles: tuple[str, ...]
    active_branch_names: tuple[str, ...]


@dataclass(frozen=True)
class RepoRef:
    """저장소의 정규화 참조 정보.

    base_branch는 이 레포의 개발 기준선 — 히스토리 분기점 계산에 쓴다.
    None이면 자동 판별한다(default_branch는 gitflow 레포에서 틀린 답을 준다).
    subtree_path는 수집 범위를 레포 내 서브디렉토리 하나로 좁히는 선택 필드다.
    None이면 레포 전체를 수집한다(기본). 값이 있으면 **선행·후행 슬래시가 없는
    정규형**임이 config 로더에서 보장된다 (예: "sample-model").
    """

    provider: Provider
    base_url: str
    namespace: str
    name: str
    web_url: str
    nickname: str | None = None
    base_branch: str | None = None
    subtree_path: str | None = None

    @property
    def full_path(self) -> str:
        """네임스페이스/이름 경로."""
        return f"{self.namespace}/{self.name}"

    @property
    def slug(self) -> str:
        """파일명용 slug (슬래시를 언더스코어 2개로)."""
        return self.full_path.replace("/", "__")

    @property
    def display_name(self) -> str:
        """탭/헤더에 표시할 이름: nickname 또는 full_path."""
        return self.nickname if self.nickname else self.full_path


@dataclass(frozen=True)
class CommitInfo:
    """단일 커밋의 정규화 정보 (provider 비종속)."""

    sha: str
    author_name: str
    authored_at: datetime
    message: str
    branch: str
    changed_files: tuple[str, ...]
    web_url: str
    changed_files_summary: str | None = None

    def __post_init__(self) -> None:
        """author_name을 NFC로 정규화 (macOS NFD 저장 대응)."""
        # macOS 클라이언트가 NFD 형태로 저장해 동일 표기가 중복 집계되는 것을 방지
        object.__setattr__(self, "author_name", unicodedata.normalize("NFC", self.author_name))


@dataclass(frozen=True)
class BranchInfo:
    """브랜치의 정규화 정보."""

    name: str
    last_commit_sha: str
    last_pushed_at: datetime | None
    web_url: str


@dataclass(frozen=True)
class ReviewEvent:
    """MR 리뷰 이벤트."""

    kind: ReviewKind
    actor_name: str
    occurred_at: datetime


@dataclass(frozen=True)
class MergeRequestInfo:
    """MR/PR의 정규화 정보."""

    iid: int
    title: str
    state: MRState
    is_draft: bool
    labels: tuple[str, ...]
    source_branch: str
    target_branch: str
    author_name: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    reviews: tuple[ReviewEvent, ...]
    is_external: bool
    web_url: str
    description: str | None = None

    def __post_init__(self) -> None:
        """author_name을 NFC로 정규화 (macOS NFD 저장 대응)."""
        # macOS 클라이언트가 NFD 형태로 저장해 동일 표기가 중복 집계되는 것을 방지
        object.__setattr__(self, "author_name", unicodedata.normalize("NFC", self.author_name))


@dataclass(frozen=True)
class RepoActivity:
    """레포의 모든 수집된 활동 (collector 출력).

    stale_branches는 lookback 범위와 무관하게 항상 수집한다 —
    PRD 정체 감지 요구("24시간 범위 밖이어도 항상 체크")의 데이터 원천.
    recent_merge_requests는 최근 MR 목록 (릴리스 열차 구축용).
    """

    repo: RepoRef
    status: CollectionStatus
    failure_reason: str | None
    commits: tuple[CommitInfo, ...]
    active_branches: tuple[BranchInfo, ...]
    created_branches: tuple[str, ...]
    deleted_branches: tuple[str, ...]
    merge_requests: tuple[MergeRequestInfo, ...]
    collected_at: datetime
    stale_branches: tuple[BranchInfo, ...] = ()
    recent_merge_requests: tuple[MergeRequestInfo, ...] = ()


@dataclass(frozen=True)
class GroupLifecycleView:
    """등록부 조인 결과 — 렌더·seed가 소비하는 읽기 전용 뷰.

    first_seen: 시작일 (ISO date). 등록부의 첫 관측일이 기본값이나, 브랜치 생애
      이력이 더 이른 작업 시작을 알면 파이프라인 조인에서 그 날짜로 보정된다 —
      관측 시작이 곧 개발 시작이 아니기 때문이다.
    total_days: first_seen부터 오늘까지의 경과일 수.
    current_stage: 현재 단계 (developing/reviewing/merged/other).
    current_stage_days: 현재 단계로 진입한 후 경과일 수.
    active_days: 커밋이 있는 날짜 수.
    cumulative_commits: 누적 커밋 수.
    """

    first_seen: str
    total_days: int
    current_stage: str
    current_stage_days: int
    active_days: int
    cumulative_commits: int


@dataclass(frozen=True)
class PromotionRung:
    """승격 사다리 한 칸 (라인 → 라인).

    source: 원본 브랜치.
    target: 대상 브랜치.
    last_merged_at: 가장 최근 merged 승격 MR의 시각.
    last_mr_iid: 가장 최근 merged 승격 MR의 IID.
    merged_count: 조회 창 내 머지된 승격 MR 수.
    open_count: 현재 대기 중인 승격 MR 수.
    """

    source: str
    target: str
    last_merged_at: datetime | None
    last_mr_iid: int | None
    merged_count: int
    open_count: int


@dataclass(frozen=True)
class ReleaseTrain:
    """레포의 승격 사다리 (라인 간 승격 관계).

    rungs: 승격 사다리 칸들 (체인 순서로 정렬, 상류→하류).
    """

    rungs: tuple[PromotionRung, ...] = ()


@dataclass(frozen=True)
class HistoryCommit:
    """브랜치 히스토리 집계용 경량 커밋.

    CommitInfo와 달리 diff를 조회하지 않는다 — 히스토리는 커밋당 1회의 diff 호출을
    감당할 수 없고(브랜치당 수백 건), 집계에 필요한 것은 시각과 제목뿐이다.

    worked_at은 authored 우선, committed 폴백 — committed는 리베이스마다 실행 시각으로
    리셋돼 브랜치 전체가 "하루에 만들어진" 것처럼 보이지만, authored는 보존된다.
    """

    sha: str
    worked_at: datetime
    title: str


@dataclass(frozen=True)
class BranchHistoryRequest:
    """히스토리 조회 대상 브랜치.

    head_sha는 증분 판정 기준 — 이미 수집된 활동 브랜치 정보에서 얻으므로 추가 호출이 없다.
    """

    branch_name: str
    head_sha: str


@dataclass(frozen=True)
class BranchHistoryFetch:
    """provider가 반환하는 브랜치 히스토리 조회 결과 (정규화 모델).

    GitLab(merge_base + commits + 역방향 compare)과 GitHub(compare 1회 + page)이
    서로 다른 경로로 수집하되 이 모델로 정규화한다.

    total_commits는 provider가 아는 실제 총계 — 상한으로 절단된 경우 len(commits)보다 크다.
    behind_count는 base 대비 뒤처진 커밋 수 (확정 불가 시 None).
    """

    branch_name: str
    base_branch: str
    merge_base_sha: str | None
    head_sha: str
    commits: tuple[HistoryCommit, ...]
    total_commits: int
    truncated: bool
    behind_count: int | None = None


@dataclass(frozen=True)
class BranchTagDistribution:
    """커밋 태그 구성.

    counts는 (태그, 건수) 내림차순. recognized는 태그가 인식된 커밋 수,
    total은 merge 커밋을 제외한 전체 커밋 수.
    인식률이 낮은 레포(자유 서술 관례)에서는 렌더를 건너뛰기 위해 coverage를 제공한다.
    """

    counts: tuple[tuple[str, int], ...]
    recognized: int
    total: int

    @property
    def coverage(self) -> float:
        """태그 인식률 (0.0~1.0). 대상 커밋이 없으면 0.0."""
        return self.recognized / self.total if self.total else 0.0


@dataclass(frozen=True)
class BranchHistoryView:
    """기능 행이 렌더에 쓰는 브랜치 생애 요약 (등록부 집계로부터 계산).

    started_on은 base 대비 고유 커밋의 첫 작업일(authored 기준) — 시스템 관측
    시작일이 아니라 실제 작업이 시작된 날이며, 리베이스에도 흔들리지 않는다.
    본편과 30일 넘게 동떨어진 소수(25% 미만)의 선행 커밋(체리픽 등 전사)은
    시작일·경과일·활동일·추이 계산에서 제외된다.
    truncated면 total_commits를 "N건 이상"으로 표기한다 (조용한 절단 금지).
    tags는 인식률이 기준 미만이면 None (우아한 저하).
    silent_gap_days는 최장 연속 무활동 일수.
    """

    base_branch: str
    started_on: str
    total_days: int
    active_days: int
    total_commits: int
    truncated: bool
    week_commit_counts: tuple[tuple[str, int], ...]
    silent_gap_days: int
    tags: BranchTagDistribution | None = None
    fix_surge: bool = False
    behind_count: int | None = None


@dataclass(frozen=True)
class FeatureGroup:
    """그룹핑된 기능 (grouper 출력).

    participants는 이름만, 사전순(유니코드 코드포인트) 정렬 — 수치·랭킹 금지 (PRD 부록 B).
    branches는 branch_names와 같은 대상의 BranchInfo 상세 — 진행 단계 판정(활성 브랜치)에 사용.
    task_summary는 기능의 상세 내용 (커밋, MR, 브랜치 제목).
    group_kind는 "feature" (기능) 또는 "line" (릴리스/검증 라인).
    issue_keys는 추출된 이슈 키 목록.
    daily_commit_counts는 (ISO date, count) 불변 튜플.
    last_activity_at는 마지막 활동 시각 (커밋 authored_at, MR updated_at/merged_at의 최대값).
    lifecycle은 등록부 조인 결과 — 수명주기 뷰 정보 (None이면 등록부에 미포함).
    branch_history는 분기점부터의 브랜치 생애 요약 (None이면 미수집·비대상).
    """

    name: str
    source_rule: GroupSourceRule
    evidence: str
    stage: FeatureStage
    repo_full_path: str
    commits: tuple[CommitInfo, ...]
    merge_requests: tuple[MergeRequestInfo, ...]
    branch_names: tuple[str, ...]
    participants: tuple[str, ...]
    branches: tuple[BranchInfo, ...] = ()
    task_summary: TaskSummary = field(default_factory=lambda: TaskSummary((), (), ()))
    issue_keys: tuple[str, ...] = ()
    group_kind: Literal["feature", "line"] = "feature"
    daily_commit_counts: tuple[tuple[str, int], ...] = ()
    last_activity_at: datetime | None = None
    lifecycle: GroupLifecycleView | None = None
    branch_history: BranchHistoryView | None = None


@dataclass(frozen=True)
class WarningSignal:
    """주의 신호."""

    kind: WarningKind
    title: str
    description: str
    days: int | None
    web_url: str | None
    repo_full_path: str | None = None


@dataclass(frozen=True)
class RepoSummary:
    """레포 하나의 탭 헤더 요약."""

    repo_full_path: str
    summary_line: str
    display_name: str
    web_url: str | None = None


@dataclass(frozen=True)
class NewWorkSignal:
    """신규 작업 신호."""

    title: str
    repo_full_path: str
    branch_or_mr: str
    web_url: str


@dataclass(frozen=True)
class ParticipationEntry:
    """팀원의 참여 정보."""

    person_name: str
    group_names: tuple[str, ...]


@dataclass(frozen=True)
class GroupStageChange:
    """그룹의 진행 단계 변화 (전일 대비 diff)."""

    group_name: str
    previous_stage: FeatureStage
    current_stage: FeatureStage
    repo_full_path: str


@dataclass(frozen=True)
class DiffSummary:
    """전일 대비 변화 요약.

    compared_to는 **데이터 기준일** — 이전 raw의 데이터가 기준인 날짜.
    previous_now(이전 수집시 collected_at의 최댓값)이 자정(00:00:00)이면
    raw_date - 1일로 사상하고, 아니면 raw_date를 그대로 사용한다.

    예시 (calendar-aligned 운용):
    - 7/23 00:00 발행, 이전 raw: 7/22 collected_at: 7/22 00:00:00
      → previous_now = 2026-07-22 00:00:00 (자정) → 1일 차감
      → compared_to = 7/21 (표시: "7/21 대비" — 2일 전 데이터와 비교)
    - 7/23 09:00 수동 실행, 이전 raw: 7/22 collected_at: 7/22 14:30:00
      → previous_now = 2026-07-22 14:30:00 (비자정) → 그대로
      → compared_to = 7/22 (표시: "7/22 대비" — 어제 데이터와 비교)
    - 월요일 72h 이후, 화요일 조회, 이전 raw: 월요일 수집 (자정)
      → previous_now = 월요일 00:00:00 (자정) → 1일 차감
      → compared_to = 일요일 (표시: "일요일 대비")

    new_groups는 (repo_full_path, group_name) 튜플의 튜플.
    stage_changes는 의미 있는 단계 변화만 포함 (other ↔ X 전이 제외).
    """

    compared_to: date
    new_groups: tuple[tuple[str, str], ...]
    stage_changes: tuple[GroupStageChange, ...]


@dataclass(frozen=True)
class DashboardModel:
    """최종 대시보드 모델 (renderer 입력).

    diff가 None이면 전일 대비 섹션을 렌더하지 않는다 (첫 실행 등).
    repos는 수집된 모든 레포의 full_path 목록 (활동 0건 레포 포함).
    repo_summaries는 각 레포별 한 줄 요약 (프로젝트 수·머지 수·주의 건수).
    period는 일간/주간 뷰 구분 (기본값 "daily", 하위 호환성 유지).
    new_work_baseline_date는 주간 뷰에서 신규 작업 비교 기준 날짜 (None이면 누적 중 표시).
    generated_at은 대시보드 생성 시각 (상대시각 표시 기준).
    issue_url_template은 이슈 URL 템플릿 (선택, 예: "https://jira.example.com/browse/{key}").
    window_start와 window_end는 조회 기간 (UTC-aware datetime).
    repo_release_trains는 레포별 승격 사다리 (repo_full_path, ReleaseTrain) 튜플 쌍.
    """

    team_name: str
    report_date: date
    lookback_hours: int
    summary_line: str
    groups: tuple[FeatureGroup, ...]
    new_work: tuple[NewWorkSignal, ...]
    warnings: tuple[WarningSignal, ...]
    unclassified_ratio: float
    diff: DiffSummary | None = None
    repos: tuple[str, ...] = ()
    repo_summaries: tuple[RepoSummary, ...] = ()
    period: Literal["daily", "weekly"] = "daily"
    new_work_baseline_date: date | None = None
    generated_at: datetime | None = None
    issue_url_template: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    repo_release_trains: tuple[tuple[str, ReleaseTrain], ...] = ()


def _isoformat_datetimes(value: Any) -> Any:
    """datetime 객체를 ISO 8601 문자열로 재귀 변환."""
    if isinstance(value, dict):
        return {k: _isoformat_datetimes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_isoformat_datetimes(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def activity_to_dict(activity: RepoActivity) -> dict[str, Any]:
    """RepoActivity를 JSON 직렬화 가능한 dict로 변환."""
    raw_dict = asdict(activity)
    result = _isoformat_datetimes(raw_dict)
    assert isinstance(result, dict)
    return result


def _repo_ref_from_dict(data: dict[str, Any]) -> RepoRef:
    """dict로부터 RepoRef 복원."""
    return RepoRef(
        provider=data["provider"],
        base_url=data["base_url"],
        namespace=data["namespace"],
        name=data["name"],
        web_url=data["web_url"],
        nickname=data.get("nickname"),
        base_branch=data.get("base_branch"),
        subtree_path=data.get("subtree_path"),
    )


def _commit_from_dict(data: dict[str, Any]) -> CommitInfo:
    """dict로부터 CommitInfo 복원."""
    return CommitInfo(
        sha=data["sha"],
        author_name=data["author_name"],
        authored_at=datetime.fromisoformat(data["authored_at"]),
        message=data["message"],
        branch=data["branch"],
        changed_files=tuple(data["changed_files"]),
        web_url=data["web_url"],
        changed_files_summary=data.get("changed_files_summary"),
    )


def _branch_from_dict(data: dict[str, Any]) -> BranchInfo:
    """dict로부터 BranchInfo 복원."""
    last_pushed = data["last_pushed_at"]
    return BranchInfo(
        name=data["name"],
        last_commit_sha=data["last_commit_sha"],
        last_pushed_at=datetime.fromisoformat(last_pushed) if last_pushed else None,
        web_url=data["web_url"],
    )


def _review_from_dict(data: dict[str, Any]) -> ReviewEvent:
    """dict로부터 ReviewEvent 복원."""
    return ReviewEvent(
        kind=data["kind"],
        actor_name=data["actor_name"],
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
    )


def _merge_request_from_dict(data: dict[str, Any]) -> MergeRequestInfo:
    """dict로부터 MergeRequestInfo 복원."""
    merged = data["merged_at"]
    reviews_data = data.get("reviews", [])
    return MergeRequestInfo(
        iid=data["iid"],
        title=data["title"],
        state=data["state"],
        is_draft=data["is_draft"],
        labels=tuple(data.get("labels", [])),
        source_branch=data["source_branch"],
        target_branch=data["target_branch"],
        author_name=data["author_name"],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        merged_at=datetime.fromisoformat(merged) if merged else None,
        reviews=tuple(_review_from_dict(r) for r in reviews_data),
        is_external=data["is_external"],
        web_url=data["web_url"],
        description=data.get("description"),
    )


def activity_from_dict(data: dict[str, Any]) -> RepoActivity:
    """dict로부터 RepoActivity 복원."""
    repo = _repo_ref_from_dict(data["repo"])
    commits = tuple(_commit_from_dict(c) for c in data.get("commits", []))
    active_branches = tuple(_branch_from_dict(b) for b in data.get("active_branches", []))
    created_branches = tuple(data.get("created_branches", []))
    deleted_branches = tuple(data.get("deleted_branches", []))
    merge_requests = tuple(_merge_request_from_dict(mr) for mr in data.get("merge_requests", []))
    stale_branches = tuple(_branch_from_dict(b) for b in data.get("stale_branches", []))
    recent_merge_requests = tuple(
        _merge_request_from_dict(mr) for mr in data.get("recent_merge_requests", [])
    )
    return RepoActivity(
        repo=repo,
        status=data["status"],
        failure_reason=data.get("failure_reason"),
        commits=commits,
        active_branches=active_branches,
        created_branches=created_branches,
        deleted_branches=deleted_branches,
        merge_requests=merge_requests,
        collected_at=datetime.fromisoformat(data["collected_at"]),
        stale_branches=stale_branches,
        recent_merge_requests=recent_merge_requests,
    )
