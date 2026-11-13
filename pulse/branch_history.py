"""브랜치 생애 히스토리 저장소 — 집계 로드/저장/병합과 렌더용 뷰 구축.

lifecycle.py와 같은 구조(로드/저장/갱신/뷰 구축, 손상 시 빈 저장소 + 경고)를 따른다.

저장하는 것은 **집계뿐**이다 — 커밋 원본은 저장하지 않는다. 브랜치 수백 개 레포에서
원본을 쌓으면 캐시가 폭증하고, 렌더에 필요한 것은 일자별 카운트·태그 구성·이슈키뿐이다.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pulse.grouper.classify import extract_issue_keys
from pulse.grouper.commit_tags import (
    build_tag_distribution,
    build_week_fix_ratios,
    detect_fix_surge,
    week_start_of,
)
from pulse.models import (
    BranchHistoryFetch,
    BranchHistoryView,
    BranchTagDistribution,
)

logger = logging.getLogger(__name__)

# v2 (2026-07-30): 일자별 카운트의 시각 기준을 committed → authored로 전환.
# v1 집계는 리베이스된 날짜(왜곡)를 담고 있어 병합이 불가능하다 — 버전 불일치로
# 전체를 버리고 재수집한다 (활동 브랜치만 대상이라 1회성 비용이 작다).
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class BranchHistoryEntry:
    """저장소의 브랜치 한 건 — 집계만 담는다.

    first_commit_on은 base 대비 고유 커밋의 첫 작업일(authored 기준, 리베이스에 불변).
    last_sha는 증분 판정 기준 — 현재 head와 같으면 재조회하지 않는다.
    truncated면 total_commits가 상한으로 절단됐다는 뜻이며 "N건 이상"으로 표기한다.
    """

    base_branch: str
    merge_base_sha: str | None
    first_commit_on: str
    last_sha: str
    total_commits: int
    truncated: bool
    date_commit_counts: tuple[tuple[str, int], ...]
    tag_counts: tuple[tuple[str, int], ...]
    tag_recognized: int
    tag_total: int
    week_fix_ratios: tuple[tuple[str, int, int], ...]
    issue_keys: tuple[str, ...]
    behind_count: int | None
    updated_on: str


@dataclass(frozen=True)
class BranchHistoryStore:
    """브랜치 히스토리 저장소 전체."""

    schema_version: int
    updated_at: datetime
    entries: tuple[tuple[str, BranchHistoryEntry], ...] = ()


def history_key(repo_full_path: str, branch_name: str) -> str:
    """저장소 키를 생성한다."""
    return f"{repo_full_path}::{branch_name}"


def entries_as_dict(store: BranchHistoryStore) -> dict[str, BranchHistoryEntry]:
    """불변 튜플을 조회용 dict로 변환한다."""
    return dict(store.entries)


def needs_refresh(entry: BranchHistoryEntry | None, current_head_sha: str) -> bool:
    """캐시가 없거나 head가 바뀌었으면 재조회 대상이다.

    Args:
        entry: 저장된 집계 (없으면 None)
        current_head_sha: 브랜치의 현재 head SHA (이미 수집된 활동 브랜치 정보에서 얻는다)

    Returns:
        재조회가 필요하면 True
    """
    if entry is None:
        return True
    return entry.last_sha != current_head_sha


def _merge_date_counts(
    previous: tuple[tuple[str, int], ...],
    fetched: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    """일자별 카운트를 날짜 overwrite로 병합한다 (순수 — 절단된 조회 전용).

    상한으로 절단된 조회는 과거 날짜를 담지 못한다. 이전 집계의 과거 카운트를 보존해야
    "언제부터 활동했나"가 유지된다. 완전한 조회에는 쓰지 않는다 — 리베이스로 커밋
    날짜가 다시 쓰이면 이전 집계의 옛 날짜는 존재하지 않는 커밋의 유령 기록이 된다.
    """
    merged = dict(previous)
    merged.update(dict(fetched))
    return tuple(sorted(merged.items()))


def _date_counts_of(fetch: BranchHistoryFetch) -> tuple[tuple[str, int], ...]:
    """조회된 커밋을 일자별 카운트로 집계한다."""
    counter: Counter[str] = Counter()
    for commit in fetch.commits:
        counter[commit.worked_at.date().isoformat()] += 1
    return tuple(sorted(counter.items()))


def _collect_issue_keys(fetch: BranchHistoryFetch) -> tuple[str, ...]:
    """커밋 제목들에서 이슈 키를 등장 순서로 중복 없이 모은다."""
    seen: dict[str, None] = {}
    for commit in fetch.commits:
        for key in extract_issue_keys(commit.title):
            seen.setdefault(key, None)
    return tuple(seen)


def build_entry(
    previous: BranchHistoryEntry | None,
    fetch: BranchHistoryFetch,
    run_date: date,
) -> BranchHistoryEntry:
    """조회 결과로 저장 항목을 만든다 (순수 — 새 항목 반환).

    일자별 카운트는 조회분으로 교체하되, 절단된 조회만 이전 집계와 병합해 과거를
    보존한다. 완전한 조회는 전 구간을 담고 있으므로 교체가 맞다 — 병합하면
    리베이스 이전 fetch의 옛 날짜가 남아 같은 커밋이 이중 집계된다.
    태그·이슈키·주간 fix 비중은 항상 조회분 기준으로 교체한다 — 날짜별로 보관하지
    않으므로 병합이 불가능하고, 절단된 경우 "최근 N건 기준"임을 truncated로
    표시하는 편이 정직하다.

    Args:
        previous: 기존 항목 (없으면 None)
        fetch: provider 조회 결과
        run_date: 실행 날짜

    Returns:
        갱신된 항목
    """
    titles = tuple(commit.title for commit in fetch.commits)
    distribution = build_tag_distribution(titles)
    dated_titles = tuple((commit.worked_at.date(), commit.title) for commit in fetch.commits)
    fetched_counts = _date_counts_of(fetch)
    if fetch.truncated and previous is not None:
        date_counts = _merge_date_counts(previous.date_commit_counts, fetched_counts)
    else:
        date_counts = fetched_counts
    first_commit_on = date_counts[0][0] if date_counts else run_date.isoformat()

    return BranchHistoryEntry(
        base_branch=fetch.base_branch,
        merge_base_sha=fetch.merge_base_sha,
        first_commit_on=first_commit_on,
        last_sha=fetch.head_sha,
        total_commits=fetch.total_commits,
        truncated=fetch.truncated,
        date_commit_counts=date_counts,
        tag_counts=distribution.counts,
        tag_recognized=distribution.recognized,
        tag_total=distribution.total,
        week_fix_ratios=build_week_fix_ratios(dated_titles),
        issue_keys=_collect_issue_keys(fetch),
        behind_count=fetch.behind_count,
        updated_on=run_date.isoformat(),
    )


def update_store(
    store: BranchHistoryStore,
    repo_full_path: str,
    fetches: tuple[BranchHistoryFetch, ...],
    run_date: date,
    updated_at: datetime | None = None,
) -> BranchHistoryStore:
    """조회 결과들로 저장소를 갱신한다 (순수 — 새 저장소 반환).

    Args:
        store: 기존 저장소
        repo_full_path: 레포 전체 경로
        fetches: 이 레포의 브랜치 조회 결과들
        run_date: 실행 날짜
        updated_at: 갱신 시각 (기본 None → 현재 UTC)

    Returns:
        갱신된 저장소
    """
    entries = entries_as_dict(store)
    for fetch in fetches:
        key = history_key(repo_full_path, fetch.branch_name)
        entries[key] = build_entry(entries.get(key), fetch, run_date)
    return BranchHistoryStore(
        schema_version=SCHEMA_VERSION,
        updated_at=updated_at or datetime.now(timezone.utc),
        entries=tuple(sorted(entries.items())),
    )


# 전사(前史) 판정: 본편과 이만큼 끊긴 소수 선행 구간은 시작일 계산에서 제외한다
PREHISTORY_GAP_DAYS = 30
PREHISTORY_MAX_SHARE = 0.25


def _trim_prehistory(
    date_counts: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    """본편과 동떨어진 선행 활동(전사)을 잘라낸다 (순수).

    체리픽·타 브랜치에서 딸려 온 커밋은 authored가 브랜치 생성 훨씬 이전이라
    시작일·경과일을 연 단위로 부풀린다(실측: 1년 전 커밋 2건이 "399일차"를 만듦).
    전체 커밋의 25% 미만인 선행 구간이 뒤 본편과 30일 넘게 끊겨 있으면 전사로 본다 —
    작업의 4분의 1 이상이 이미 이뤄진 뒤의 긴 휴지기는 본편의 일부이므로 자르지 않는다.
    """
    active = [(date.fromisoformat(day), count) for day, count in date_counts if count > 0]
    if len(active) < 2:
        return date_counts

    total = sum(count for _, count in active)
    cumulative = 0
    cut_index = 0
    for index in range(len(active) - 1):
        cumulative += active[index][1]
        if cumulative / total >= PREHISTORY_MAX_SHARE:
            break
        gap_days = (active[index + 1][0] - active[index][0]).days
        if gap_days > PREHISTORY_GAP_DAYS:
            cut_index = index + 1

    if cut_index == 0:
        return date_counts
    cutoff = active[cut_index][0].isoformat()
    return tuple((day, count) for day, count in date_counts if day >= cutoff)


def _week_commit_counts(date_counts: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
    """일자별 카운트를 주 단위로 합산한다."""
    counter: Counter[date] = Counter()
    for date_str, count in date_counts:
        counter[week_start_of(date.fromisoformat(date_str))] += count
    return tuple((week.isoformat(), counter[week]) for week in sorted(counter))


def _longest_silent_gap(date_counts: tuple[tuple[str, int], ...]) -> int:
    """활동일 사이의 최장 연속 무활동 일수를 구한다."""
    active = sorted(date.fromisoformat(d) for d, count in date_counts if count > 0)
    if len(active) < 2:
        return 0
    # 인접 쌍 순회이므로 뒤 시퀀스가 1개 짧다 — strict=False가 의도된 동작이다
    return max(
        (later - earlier).days - 1 for earlier, later in zip(active, active[1:], strict=False)
    )


def build_history_view(
    entry: BranchHistoryEntry,
    today: date,
    min_tag_coverage: float,
) -> BranchHistoryView:
    """저장 집계를 렌더용 뷰로 계산한다.

    시작일·경과일·활동일·추이는 전사를 잘라낸 타임라인 기준이다 — 저장소는 원본
    집계를 그대로 두고, 서사 지표만 본편에 맞춘다. total_commits는 브랜치 고유
    커밋 총수 그대로다(전사 커밋도 브랜치에 실재한다).
    태그 인식률이 기준 미만이면 tags=None으로 둔다 — 자유 서술 관례의 레포에서
    "미인식 100%"를 보여주는 것은 화면 낭비다(우아한 저하).

    Args:
        entry: 저장된 집계
        today: 기준 날짜
        min_tag_coverage: 태그 UI를 표시할 최소 인식률

    Returns:
        렌더용 뷰
    """
    timeline = _trim_prehistory(entry.date_commit_counts)
    started_on = timeline[0][0] if timeline else entry.first_commit_on
    started = date.fromisoformat(started_on)
    distribution = BranchTagDistribution(
        counts=entry.tag_counts,
        recognized=entry.tag_recognized,
        total=entry.tag_total,
    )
    return BranchHistoryView(
        base_branch=entry.base_branch,
        started_on=started_on,
        total_days=(today - started).days + 1,
        active_days=sum(1 for _, count in timeline if count > 0),
        total_commits=entry.total_commits,
        truncated=entry.truncated,
        week_commit_counts=_week_commit_counts(timeline),
        silent_gap_days=_longest_silent_gap(timeline),
        tags=distribution if distribution.coverage >= min_tag_coverage else None,
        fix_surge=detect_fix_surge(entry.week_fix_ratios),
        behind_count=entry.behind_count,
    )


def _empty_store() -> BranchHistoryStore:
    """빈 저장소를 만든다 (로드 실패 시 폴백)."""
    return BranchHistoryStore(
        schema_version=SCHEMA_VERSION,
        updated_at=datetime.now(timezone.utc),
        entries=(),
    )


def _entry_from_dict(data: dict[str, Any]) -> BranchHistoryEntry:
    """dict로부터 항목을 복원한다.

    JSON은 외부 입력이므로 형식을 신뢰하지 않는다. 필수 키 누락·타입 불일치는
    예외로 올려 호출자(load_store)가 그 항목만 건너뛰게 한다.
    """
    date_counts = data.get("date_commit_counts")
    counts = tuple(sorted(date_counts.items())) if isinstance(date_counts, dict) else ()
    merge_base_sha = data.get("merge_base_sha")
    behind_count = data.get("behind_count")
    return BranchHistoryEntry(
        base_branch=str(data["base_branch"]),
        merge_base_sha=str(merge_base_sha) if merge_base_sha is not None else None,
        first_commit_on=str(data["first_commit_on"]),
        last_sha=str(data["last_sha"]),
        total_commits=int(data["total_commits"]),
        truncated=bool(data.get("truncated", False)),
        date_commit_counts=counts,
        tag_counts=tuple((str(tag), int(count)) for tag, count in data.get("tag_counts", ())),
        tag_recognized=int(data.get("tag_recognized", 0)),
        tag_total=int(data.get("tag_total", 0)),
        week_fix_ratios=tuple(
            (str(week), int(fix), int(recognized))
            for week, fix, recognized in data.get("week_fix_ratios", ())
        ),
        issue_keys=tuple(str(key) for key in data.get("issue_keys", ())),
        behind_count=int(behind_count) if behind_count is not None else None,
        updated_on=str(data.get("updated_on", "")),
    )


def load_store(path: Path) -> BranchHistoryStore:
    """저장소를 로드한다 — 없음/손상/스키마 불일치 시 빈 저장소 + 경고 (우아한 저하)."""
    if not path.exists():
        return _empty_store()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("루트가 dict가 아닙니다")

        if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            logger.warning("branch history: 지원하지 않는 스키마 %s", data.get("schema_version"))
            return _empty_store()

        try:
            updated_at = datetime.fromisoformat(str(data.get("updated_at")))
        except (ValueError, TypeError):
            updated_at = datetime.now(timezone.utc)

        entries_data = data.get("entries", {})
        if not isinstance(entries_data, dict):
            logger.warning("branch history: entries가 dict가 아닙니다")
            return _empty_store()

        entries: dict[str, BranchHistoryEntry] = {}
        for key, entry_data in entries_data.items():
            if not isinstance(entry_data, dict):
                continue
            try:
                entries[key] = _entry_from_dict(entry_data)
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("branch history: 손상된 항목 건너뜀 %s: %s", key, error)

        return BranchHistoryStore(
            schema_version=SCHEMA_VERSION,
            updated_at=updated_at,
            entries=tuple(sorted(entries.items())),
        )

    except (json.JSONDecodeError, OSError, ValueError) as error:
        logger.warning("branch history 로드 실패: %s — 빈 저장소로 진행", error)
        return _empty_store()


def save_store(store: BranchHistoryStore, path: Path) -> None:
    """저장소를 저장한다 (디렉토리 자동 생성, 키 정렬 고정)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = {
        key: {
            "base_branch": entry.base_branch,
            "merge_base_sha": entry.merge_base_sha,
            "first_commit_on": entry.first_commit_on,
            "last_sha": entry.last_sha,
            "total_commits": entry.total_commits,
            "truncated": entry.truncated,
            "date_commit_counts": dict(entry.date_commit_counts),
            "tag_counts": [list(pair) for pair in entry.tag_counts],
            "tag_recognized": entry.tag_recognized,
            "tag_total": entry.tag_total,
            "week_fix_ratios": [list(triple) for triple in entry.week_fix_ratios],
            "issue_keys": list(entry.issue_keys),
            "behind_count": entry.behind_count,
            "updated_on": entry.updated_on,
        }
        for key, entry in store.entries
    }
    payload = {
        "schema_version": store.schema_version,
        "updated_at": store.updated_at.isoformat(),
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def store_path(data_dir: Path) -> Path:
    """저장소 파일 경로를 만든다."""
    return data_dir / "history" / "branches.json"
