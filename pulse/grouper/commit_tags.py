"""커밋 제목의 작업 유형 태그 파싱과 집계 — provider 비종속 순수 로직.

레포마다 커밋 관례가 다르다. 실측(2026-07-27)에서 같은 조직 안에 두 형식이 공존했다:
`[feat] ...`(sample-repo, sample-editor)와 `feat: ...`(sample-docs).
따라서 세 형식을 모두 인식하고, 인식률(coverage)을 함께 반환해 자유 서술 관례의 레포에서는
호출자가 렌더를 건너뛸 수 있게 한다.
"""

import re
from collections import Counter
from datetime import date, timedelta

from pulse.models import BranchTagDistribution

_BRACKET_TAG = re.compile(r"^\[([A-Za-z]+)\]")
_SCOPED_TAG = re.compile(r"^([A-Za-z]+)\([^)]*\)!?:")
# (?!//)는 URL을 배제한다 — "https://example.com 수정"의 https가 태그로 잡히면 안 된다.
# 알려진 태그 화이트리스트(feat/fix/...)를 쓰지 않는 이유: 조직마다 어휘가 달라
# 범용성을 해친다. 인식률(coverage)로 관례 없는 레포를 걸러내는 쪽을 택했다.
_PLAIN_TAG = re.compile(r"^([A-Za-z]+)!?:(?!//)")

_MERGE_PREFIXES = ("merge ", "merged ", "revert merge")

FIX_TAG = "fix"

# fix 급증 판정 기준 — 표본이 적을 때 요란한 신호를 내지 않도록 하한을 둔다
FIX_SURGE_MIN_PRIOR_WEEKS = 2
FIX_SURGE_MIN_LATEST_COMMITS = 5
FIX_SURGE_RATIO_DELTA = 0.2


def is_merge_title(title: str) -> bool:
    """merge 커밋 제목인지 판별한다 (태그 집계 모집단에서 제외).

    Args:
        title: 커밋 제목 (첫 줄)

    Returns:
        merge 커밋이면 True
    """
    lowered = title.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _MERGE_PREFIXES)


def parse_tag(title: str) -> str | None:
    """커밋 제목에서 작업 유형 태그를 뽑는다.

    인식 형식: `[feat] ...` · `feat: ...` · `feat(scope): ...` (대소문자 무시).
    merge 커밋과 형식 없는 자유 서술은 None.

    Args:
        title: 커밋 제목 (첫 줄)

    Returns:
        소문자 태그 문자열, 인식 실패 시 None
    """
    stripped = title.strip()
    if is_merge_title(stripped):
        return None
    for pattern in (_BRACKET_TAG, _SCOPED_TAG, _PLAIN_TAG):
        match = pattern.match(stripped)
        if match:
            return match.group(1).lower()
    return None


def build_tag_distribution(titles: tuple[str, ...]) -> BranchTagDistribution:
    """태그 구성과 인식률을 집계한다.

    merge 커밋은 모집단(total)에서 제외한다 — 자동 생성 커밋이 인식률을 왜곡한다.

    Args:
        titles: 커밋 제목들

    Returns:
        태그 분포 (counts는 건수 내림차순, 동수면 태그명 오름차순)
    """
    counter: Counter[str] = Counter()
    total = 0
    for title in titles:
        if is_merge_title(title):
            continue
        total += 1
        tag = parse_tag(title)
        if tag:
            counter[tag] += 1
    counts = tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
    return BranchTagDistribution(counts=counts, recognized=sum(counter.values()), total=total)


def week_start_of(day: date) -> date:
    """해당 날짜가 속한 주의 월요일을 반환한다."""
    return day - timedelta(days=day.weekday())


def build_week_fix_ratios(
    dated_titles: tuple[tuple[date, str], ...],
) -> tuple[tuple[str, int, int], ...]:
    """(날짜, 제목) 쌍을 주 단위로 묶어 fix 비중 계산 재료를 만든다.

    Args:
        dated_titles: (커밋 날짜, 커밋 제목) 쌍들

    Returns:
        주 시작일 오름차순의 (주 시작 ISO date, fix 커밋 수, 태그 인식 커밋 수) 튜플
    """
    fix_counts: Counter[date] = Counter()
    recognized_counts: Counter[date] = Counter()
    for day, title in dated_titles:
        tag = parse_tag(title)
        if not tag:
            continue
        week = week_start_of(day)
        recognized_counts[week] += 1
        if tag == FIX_TAG:
            fix_counts[week] += 1
    return tuple(
        (week.isoformat(), fix_counts.get(week, 0), recognized_counts[week])
        for week in sorted(recognized_counts)
    )


def detect_fix_surge(week_fix_ratios: tuple[tuple[str, int, int], ...]) -> bool:
    """최근 주의 fix 비중이 이전 주 평균보다 유의미하게 높으면 True.

    단계 자동 판정(구축기→안정화기)은 하지 않는다 — 실측 10주 중 9주가 일관되게
    "혼재"(구축 51~59%)였고 구성비로는 단계 전이가 읽히지 않았다. 대신 검증·버그 대응
    국면으로의 쏠림만 신호로 쓴다.

    Args:
        week_fix_ratios: build_week_fix_ratios 결과 (주 시작일 오름차순)

    Returns:
        최근 주 fix 비중이 이전 평균 대비 기준치 이상 높으면 True
    """
    if len(week_fix_ratios) < FIX_SURGE_MIN_PRIOR_WEEKS + 1:
        return False

    *prior_weeks, latest_week = week_fix_ratios
    _, latest_fix, latest_total = latest_week
    if latest_total < FIX_SURGE_MIN_LATEST_COMMITS:
        return False

    prior_total = sum(total for _, _, total in prior_weeks)
    if not prior_total:
        return False

    prior_ratio = sum(fix for _, fix, _ in prior_weeks) / prior_total
    latest_ratio = latest_fix / latest_total
    return latest_ratio - prior_ratio >= FIX_SURGE_RATIO_DELTA
