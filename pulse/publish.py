"""Skill용 발행 진입점: collect → inject → token 서브커맨드."""

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from pulse.analysis_cache import (
    compute_group_seed_fingerprint,
    evaluate_cached_status,
    load_analysis_cache,
    load_pending,
    save_analysis_cache,
    save_pending,
)
from pulse.business_calendar import week_anchor
from pulse.collector import missing_tokens
from pulse.collector.storage import load_raw_activity, load_weekly_snapshot, save_weekly_snapshot
from pulse.config import ConfigError, load_config
from pulse.grouper import filter_activities_to_window, group_activities
from pulse.grouper.classify import extract_bracket_scope
from pulse.grouper.group import normalize_commit_titles
from pulse.lifecycle import (
    load_registry,
    registry_path,
    save_registry,
    update_registry,
)
from pulse.models import DashboardModel, ReleaseTrain
from pulse.pipeline import calendar_warnings, config_holiday_dates, get_effective_now, run_pipeline
from pulse.renderer.html import (
    ai_summary_slot,
    inject_ai_summary,
    inject_group_ai_title,
    inject_group_analysis,
)
from pulse.renderer.textmark import IMPACT_PARAGRAPH_LABEL, split_brief_paragraphs, strip_emphasis
from pulse.run_plan import (
    CollectPlan,
    Period,
    last_published_window_end,
    pending_period,
    plan_collect,
)
from pulse.secrets import (
    Provider,
    TokenError,
    clear_token,
    missing_token_hint,
    store_token,
    token_source,
)
from pulse.state_io import save_optional_state

if TYPE_CHECKING:
    from pulse.config import Config
    from pulse.models import FeatureGroup, RepoActivity

logger = logging.getLogger(__name__)

# Constants for seed derivation and changed_files_summary truncation
MAX_SEED_COMMIT_TITLES = 50
MAX_SEED_MRS = 20
MAX_SEED_MR_DESCRIPTION_CHARS = 500
MAX_SUMMARY_CHARS_PER_COMMIT = 1500
MAX_SUMMARY_CHARS_PER_GROUP = 6000


def _parse_now_override(value: str) -> datetime:
    """ISO 8601 타임스탬프 문자열을 파싱한다.

    Args:
        value: ISO 형식 타임스탬프 (예: "2026-07-22T00:00:00+09:00")

    Returns:
        datetime 객체 (tzinfo 포함)

    Raises:
        ValueError: 타임존 정보 없음 또는 파싱 실패
    """
    try:
        # Python 3.10 의 fromisoformat 은 끝의 Z(UTC)를 읽지 못해 끝자리만 +00:00 으로 바꾼다.
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            raise ValueError("--now는 타임존을 포함해야 합니다. 예: 2026-07-22T00:00:00+09:00")
        return dt
    except (ValueError, TypeError) as e:
        raise ValueError(f"--now 파싱 실패: {value} — {e}") from e


def _derive_seed_mrs(group: "FeatureGroup") -> list[dict[str, object]]:
    """그룹의 MR 전체(merged 포함)를 seed 항목으로 변환한다.

    상한: 20건, description은 500자 절단.

    Args:
        group: FeatureGroup 객체

    Returns:
        MR seed 항목 리스트. 각 항목:
        {
            "title": str,
            "state": "open" | "merged" | "closed",
            "target_branch": str,
            "is_draft": bool,
            "description": str | None (절단됨),
            "review_comment_count": int,
        }
    """
    mrs_list = []
    for mr in group.merge_requests[:MAX_SEED_MRS]:
        description = None
        if mr.description:
            description = mr.description[:MAX_SEED_MR_DESCRIPTION_CHARS]
        review_comment_count = len([r for r in mr.reviews if r.kind == "commented"])
        mrs_list.append(
            {
                "title": mr.title,
                "state": mr.state,
                "target_branch": mr.target_branch,
                "is_draft": mr.is_draft,
                "description": description,
                "review_comment_count": review_comment_count,
            }
        )
    return mrs_list


def _derive_scope_distribution(group: "FeatureGroup") -> dict[str, int]:
    """그룹 커밋들의 브래킷 영역 분포를 계산한다.

    커밋 메시지에서 '[type][scope] 제목' 형식의 scope를 추출해서 분포를 계산.

    Args:
        group: FeatureGroup 객체

    Returns:
        {scope: count} dict. 예: {"워드": 8, "뷰어": 3}
    """
    scope_counts: dict[str, int] = {}
    for commit in group.commits:
        scope = extract_bracket_scope(commit.message)
        if scope:
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
    return scope_counts


def _derive_branch_history_seed(group: "FeatureGroup") -> dict[str, object] | None:
    """브랜치 생애 뷰를 seed용으로 직렬화한다 (없으면 None).

    seed 소비자(AI 분석 작성자)가 대시보드와 같은 경과일을 쓰려면 이 값이 필요하다. 시작일·경과일은
    파이프라인 조인에서 lifecycle에도 보정되지만, active_days·태그·공백 등
    생애 지표의 원 근거는 여기다 — lifecycle의 active_days는 관측 이후만 센다.

    week_commit_counts는 넣지 않는다 — seed의 추이는 일별(daily_commit_counts) 하나로 둔다.

    Args:
        group: FeatureGroup 객체

    Returns:
        생애 seed dict 또는 None
    """
    history = group.branch_history
    if history is None:
        return None

    tags_seed: dict[str, object] | None = None
    if history.tags is not None:
        tags_seed = {
            "counts": [list(pair) for pair in history.tags.counts],
            "recognized": history.tags.recognized,
            "total": history.tags.total,
        }

    return {
        "base_branch": history.base_branch,
        "started_on": history.started_on,
        "total_days": history.total_days,
        "active_days": history.active_days,
        "total_commits": history.total_commits,
        "truncated": history.truncated,
        "silent_gap_days": history.silent_gap_days,
        "behind_count": history.behind_count,
        "fix_surge": history.fix_surge,
        "tags": tags_seed,
    }


def _derive_release_train_seed(train: "ReleaseTrain") -> list[dict[str, object]]:
    """사다리를 seed용으로 직렬화한다 (개인 정보 미포함).

    Args:
        train: ReleaseTrain 객체

    Returns:
        칸(PromotionRung) 리스트. 각 항목:
        {
            "source": str,
            "target": str,
            "last_merged_at": str | None (ISO date),
            "merged_count": int,
            "open_count": int,
        }
    """

    if not train.rungs:
        return []

    result: list[dict[str, object]] = []
    for rung in train.rungs:
        last_merged_at_str: str | None = None
        if rung.last_merged_at is not None:
            last_merged_at_str = rung.last_merged_at.date().isoformat()

        result.append(
            {
                "source": rung.source,
                "target": rung.target,
                "last_merged_at": last_merged_at_str,
                "merged_count": rung.merged_count,
                "open_count": rung.open_count,
            }
        )
    return result


def extract_summary_input(model: DashboardModel) -> dict[str, object]:
    """요약에 필요한 최소 데이터를 추출한다 (개인 이름 제외).

    Args:
        model: 대시보드 모델

    Returns:
        요약용 데이터 dict: 키는 문자열, 값은 문자열/정수/리스트/등
    """
    result: dict[str, object] = {
        "team_name": model.team_name,
        "report_date": model.report_date.isoformat(),
        "lookback_hours": model.lookback_hours,
        "period": model.period,
        "group_names": [g.name for g in model.groups],
        "group_count": len(model.groups),
        "new_work_count": len(model.new_work),
        "warning_count": len(model.warnings),
        "warning_titles": [w.title for w in model.warnings],
        "repos": list(model.repos),
    }
    return result


def extract_summary_input_by_repo(
    model: DashboardModel,
    cache: dict[str, Any] | None = None,
) -> dict[str, object]:
    """요약에 필요한 데이터를 레포별로 추출한다 (개인 이름 제외, groups 포함).

    각 레포별로 groups, warnings, new_work를 필터링하여 추출한다.
    groups 섹션은 자신의 period 그룹만 평면 dict로 반환하며,
    캐시 메타 (cached, cached_title, cached_analysis)를 추가한다.

    Args:
        model: 대시보드 모델
        cache: 그룹 분석 캐시 dict (선택, None이면 빈 dict 사용)

    Returns:
        요약용 데이터 dict: {
            "team_name": str,
            "report_date": str (ISO 형식),
            "period": str ("daily" or "weekly"),
            "repos": {
                "org/repo": {
                    "group_names": [str],
                    "group_count": int,
                    "new_work_count": int,
                    "warning_count": int,
                    "warning_titles": [str],
                    "commit_count": int,
                    "mr_count": int,
                },
                ...
            },
            "groups": {
                "org/repo::group_name": {
                    "name": str,
                    "stage": str,
                    "commit_titles": [str],
                    "branch_names": [str],
                    "mr_titles": [str],
                    "cached": bool,
                    "cached_title": str | None,
                    "cached_analysis": str | None,
                },
                ...
            }
        }
    """
    if cache is None:
        cache = {}

    repos_data: dict[str, dict[str, object]] = {}

    # 레포별 release_train 맵 생성
    repo_train_map: dict[str, ReleaseTrain] = {}
    for repo_full_path, train in model.repo_release_trains:
        repo_train_map[repo_full_path] = train

    for repo in model.repos:
        # 해당 레포의 그룹/경고/신규 작업만 필터링
        repo_groups = [g for g in model.groups if g.repo_full_path == repo]
        repo_warnings = [w for w in model.warnings if w.repo_full_path == repo]
        repo_new_work = [w for w in model.new_work if w.repo_full_path == repo]

        # 레포별 커밋/MR 개수 계산
        commit_count = sum(len(g.commits) for g in repo_groups)
        mr_count = sum(len(g.merge_requests) for g in repo_groups)

        # release_train 직렬화 (있으면 추가)
        release_train_seed = []
        if repo in repo_train_map:
            release_train_seed = _derive_release_train_seed(repo_train_map[repo])

        repos_data[repo] = {
            "group_names": [g.name for g in repo_groups],
            "group_count": len(repo_groups),
            "new_work_count": len(repo_new_work),
            "warning_count": len(repo_warnings),
            "warning_titles": [w.title for w in repo_warnings],
            "commit_count": commit_count,
            "mr_count": mr_count,
            **({"release_train": release_train_seed} if release_train_seed else {}),
        }

    # groups 섹션: 자신의 period 그룹만 평면 dict로 생성 + 캐시 메타 + changed_files
    groups_seed: dict[str, dict[str, object]] = {}
    for group in model.groups:
        key = f"{group.repo_full_path}::{group.name}"
        fingerprint = compute_group_seed_fingerprint(group)
        cache_key = f"{key}@{model.period}"
        entry = cache.get(cache_key)
        hit = entry is not None and entry.get("seed_fingerprint") == fingerprint

        cached_title = None
        cached_analysis = None
        if hit and entry is not None:
            cached_title = entry.get("title")
            cached_analysis = entry.get("analysis")

        # changed_files 집계: 그룹의 모든 커밋의 파일 합집합
        all_changed_files: set[str] = set()
        for commit in group.commits:
            all_changed_files.update(commit.changed_files)
        changed_files_count = len(all_changed_files)

        # changed_files_summary 병합: 그룹 커밋들의 발췌를 줄바꿈으로 연결, 6000자 절단
        summaries_list = [c.changed_files_summary for c in group.commits if c.changed_files_summary]
        if summaries_list:
            changed_files_summary = "\n".join(summaries_list)[:MAX_SUMMARY_CHARS_PER_GROUP]
        else:
            changed_files_summary = None

        # Seed 확대: commit_titles 50건, mrs, issue_keys, scope_distribution, group_kind
        all_commit_titles = normalize_commit_titles(group.commits)
        seed_mrs = _derive_seed_mrs(group)
        scope_distribution = _derive_scope_distribution(group)

        # 그룹 활동 지표: commit_count, last_activity_at, daily_commit_counts
        commit_count = len(group.commits)
        last_activity_at_iso = (
            group.last_activity_at.isoformat() if group.last_activity_at else None
        )
        daily_commit_counts_list = (
            [list(entry) for entry in group.daily_commit_counts]
            if group.daily_commit_counts
            else []
        )

        # lifecycle 뷰 직렬화 (있으면 추가)
        lifecycle_seed: dict[str, object] | None = None
        if group.lifecycle is not None:
            lifecycle_seed = {
                "first_seen": group.lifecycle.first_seen,
                "total_days": group.lifecycle.total_days,
                "current_stage": group.lifecycle.current_stage,
                "current_stage_days": group.lifecycle.current_stage_days,
                "active_days": group.lifecycle.active_days,
                "cumulative_commits": group.lifecycle.cumulative_commits,
            }

        branch_history_seed = _derive_branch_history_seed(group)

        groups_seed[key] = {
            "name": group.name,
            "stage": group.stage,
            "commit_titles": list(all_commit_titles[:MAX_SEED_COMMIT_TITLES]),
            "branch_names": list(group.task_summary.active_branch_names),
            "mr_titles": list(group.task_summary.open_mr_titles),
            "mrs": seed_mrs,
            "issue_keys": list(group.issue_keys),
            "scope_distribution": scope_distribution,
            "group_kind": group.group_kind,
            "commit_count": commit_count,
            "last_activity_at": last_activity_at_iso,
            "daily_commit_counts": daily_commit_counts_list,
            "changed_files_count": changed_files_count,
            "changed_files_summary": changed_files_summary,
            "cached": hit,
            "cached_title": cached_title,
            "cached_analysis": cached_analysis,
            **({"lifecycle": lifecycle_seed} if lifecycle_seed else {}),
            **({"branch_history": branch_history_seed} if branch_history_seed else {}),
        }

    result: dict[str, object] = {
        "team_name": model.team_name,
        "report_date": model.report_date.isoformat(),
        "period": model.period,
        "repos": repos_data,
        "groups": groups_seed,
        "window_start": model.window_start.isoformat() if model.window_start else None,
        "window_end": model.window_end.isoformat() if model.window_end else None,
    }
    return result


def _format_snippet_body(text: str) -> str:
    """레포 요약 한 건을 스니펫 본문으로 만든다 (마커 제거, 개선점 문단이 있으면 소제목 줄 삽입).

    Args:
        text: 레포 요약 원문 (마커·빈 줄 문단 경계를 포함할 수 있음)

    Returns:
        평문 본문 (개선점 문단이 없으면 종전과 같은 strip 결과)
    """
    plain_text = strip_emphasis(text)
    paragraphs = split_brief_paragraphs(plain_text)
    if not paragraphs.impact:
        return plain_text.strip()
    return f"{paragraphs.flow}\n\n[{IMPACT_PARAGRAPH_LABEL}]\n{paragraphs.impact}"


def build_share_snippet(summaries: dict[str, dict[str, str]]) -> str:
    """공유용 텍스트 스니펫을 생성한다 (일간 기준 레포별).

    Args:
        summaries: {"daily": {repo: "...", ...}, "weekly": {repo: "...", ...}} dict

    Returns:
        마크다운 포맷의 공유 스니펫
    """
    snippet = "## Daily Pulse 요약\n\n"

    daily_summaries = summaries.get("daily", {})
    if daily_summaries:
        for repo, text in sorted(daily_summaries.items()):
            # 평문 소비처(메신저 붙여넣기)이므로 강조 마커는 제거하고 내용만 남긴다
            stripped_text = _format_snippet_body(text)
            if stripped_text:
                snippet += f"### {repo}\n{stripped_text}\n\n"

    return snippet.rstrip() + "\n" if snippet != "## Daily Pulse 요약\n\n" else snippet


def _merge_snapshot_if_not_publishing(
    payload: dict[str, Any],
    config: "Config",
    cache: dict[str, Any] | None = None,
) -> None:
    """비발행 실행 시 주간 스냅샷을 로드하여 payload에 병합한다 (in-place).

    스냅샷이 없으면 weekly 섹션을 제거한다 (우아한 저하).

    Args:
        payload: collect JSON payload (수정됨)
        config: 설정 객체
        cache: 분석 캐시 dict (선택, None이면 사용하지 않음)
    """
    if "weekly" not in payload:
        return

    # 스냅샷 로드
    snapshot = load_weekly_snapshot(config.data_dir)
    if snapshot:
        payload["weekly"] = snapshot
        # cached 플래그 재평가
        if cache is not None:
            evaluate_cached_status(payload["weekly"], cache)
    else:
        # 스냅샷 부재 → 주간 섹션 제거 (우아한 저하)
        payload.pop("weekly", None)


def _render_and_write_reports(
    daily: Any, weekly: Any, config: Any, period: str, publish_weekly: bool, ad_hoc: bool
) -> None:
    """daily/weekly HTML을 렌더링하고 파일에 저장한다 (헬퍼).

    Args:
        daily: daily 모델
        weekly: weekly 모델
        config: 설정 객체
        period: "daily"|"weekly"|"both"
        publish_weekly: weekly를 발행하는지 여부
        ad_hoc: ad-hoc 모드 여부 (write_latest 제어)
    """
    from pulse.renderer import render_html, write_report, write_weekly_report

    if period in ("daily", "both"):
        daily_html = render_html(daily)
        write_report(
            daily_html,
            config.output_dir,
            daily.report_date,
            write_latest=(not ad_hoc),
        )

    if period in ("weekly", "both") and (publish_weekly or ad_hoc):
        weekly_html = render_html(weekly)
        write_weekly_report(
            weekly_html,
            config.output_dir,
            weekly.report_date,
            write_latest=(not ad_hoc),
        )


def _handle_weekly_snapshot(
    payload: dict[str, Any],
    config: Any,
    cache: dict[str, Any],
    publish_weekly: bool,
    ad_hoc: bool,
    effective_now: datetime,
) -> None:
    """주간 스냅샷을 저장하거나 캐시 병합 준비한다 (헬퍼, ad-hoc 제외).

    Args:
        payload: 수집 결과 payload
        config: 설정 객체
        cache: 분석 캐시
        publish_weekly: 주간 발행 여부
        ad_hoc: ad-hoc 모드 여부 (True면 함수 호출 안 함)
        effective_now: 현재 시각 (utc+tz)
    """
    if ad_hoc:
        return

    if publish_weekly and "weekly" in payload:
        snapshot_with_metadata = {
            **payload["weekly"],
            "published_at": effective_now.isoformat(),
        }
        save_optional_state(
            "주간 발행 스냅샷",
            lambda: save_weekly_snapshot(config.data_dir, snapshot_with_metadata),
        )
    else:
        _merge_snapshot_if_not_publishing(payload, config, cache)


def _group_fingerprints(model: Any) -> dict[str, str]:
    """모델의 그룹별 seed 지문을 {repo::name: 지문} 으로 만든다.

    Args:
        model: daily 또는 weekly 모델

    Returns:
        그룹 키별 지문 dict
    """
    return {
        f"{g.repo_full_path}::{g.name}": compute_group_seed_fingerprint(g) for g in model.groups
    }


def _save_pending_fingerprints(daily: Any, weekly: Any, period: str, data_dir: Path) -> None:
    """그룹 seed 지문을 pending.json에 저장한다 (헬퍼, ad-hoc 제외).

    이번 실행이 다루는 period 섹션만 교체하고 나머지 period는 그대로 남긴다.
    일간과 주간을 서로 다른 --now로 따로 수집하면(일간 오늘·주간 지난 월요일)
    뒤 실행이 앞 지문을 지워, inject가 그 period의 캐시된 분석을 주입하지 못하고
    그룹 슬롯을 빈 채 남긴다 — 2026-07-29 발행에서 실제로 발생했다.

    섹션 안에서는 병합하지 않고 통째로 바꾼다. 이제 없는 그룹의 낡은 지문이 남으면
    나중에 우연히 지문이 맞는 캐시가 되살아난다.

    Args:
        daily: daily 모델
        weekly: weekly 모델
        period: "daily"|"weekly"|"both"
        data_dir: 데이터 디렉토리
    """
    pending_path = data_dir / "analysis" / "pending.json"
    pending = load_pending(pending_path)
    pending.pop("report_date", None)  # 구 형식(단일 날짜) — report_dates가 대체

    report_dates = pending.get("report_dates")
    if not isinstance(report_dates, dict):
        report_dates = {}

    for period_key, model in (("daily", daily), ("weekly", weekly)):
        if period not in (period_key, "both"):
            continue
        pending[period_key] = _group_fingerprints(model)
        report_dates[period_key] = model.report_date.isoformat()

    pending["report_dates"] = report_dates
    save_optional_state("분석 pending 지문", lambda: save_pending(pending, pending_path))


def _plan_from_request(
    config: "Config", now_override: str | None, period: Period, force_weekly: bool, ad_hoc: bool
) -> tuple[datetime, CollectPlan]:
    """--now(없으면 현재 시각)를 config 시간대로 맞추고, 마지막 발행 기록·휴무일로 계획을 세운다.

    Raises:
        ValueError: --now 형식 오류, 또는 옵션 조합 오류(CollectPlanError)
    """
    now_override_dt = _parse_now_override(now_override) if now_override else None
    requested_now = (now_override_dt or get_effective_now(config)).astimezone(
        ZoneInfo(config.timezone_name)
    )
    last_window_end = last_published_window_end(load_weekly_snapshot(config.data_dir))
    plan = plan_collect(
        requested_now,
        period,
        force_weekly,
        ad_hoc,
        config_holiday_dates(config),
        last_window_end,
    )
    if period != "daily":
        logger.info(
            "주간 발행 판단: %s (기준일 %s, 이번 주 월요일 %s, 마지막 발행 창 끝 %s)",
            "발행" if plan.publish_weekly else "발행 안 함",
            requested_now.date().isoformat(),
            week_anchor(requested_now).date().isoformat(),
            last_window_end.isoformat() if last_window_end else None,
        )
    return requested_now, plan


def _build_summary_payload(
    daily: Any, weekly: Any, cache: dict[str, Any], period: Period
) -> dict[str, Any]:
    """period에 해당하는 일간·주간 섹션으로 요약용 payload를 만든다."""
    payload: dict[str, Any] = {}
    if period in ("daily", "both"):
        payload["daily"] = extract_summary_input_by_repo(daily, cache)
    if period in ("weekly", "both"):
        payload["weekly"] = extract_summary_input_by_repo(weekly, cache)
    return payload


def _run_collect(
    config: "Config", requested_now: datetime, plan: CollectPlan, period: Period, ad_hoc: bool
) -> int:
    """계획대로 파이프라인을 돌리고 HTML·스냅샷·pending·payload를 기록한다.

    Args:
        config: 설정 객체
        requested_now: 요청 시각 — 이름표(report_date·published_at)가 되는 발행일
        plan: plan_collect 의 결과 (주간 발행·주간 창 끝·상태 기록 여부)
        period: "daily"|"weekly"|"both"
        ad_hoc: True면 dated 파일만 쓰고 운영 상태는 바꾸지 않는다

    Returns:
        exit code (0=성공, 1=파이프라인 오류)
    """
    try:
        daily, weekly = run_pipeline(
            config,
            requested_now,
            persist_state=plan.persist_state,
            weekly_window_end=plan.weekly_window_end,
        )
        cache = load_analysis_cache(config.data_dir / "analysis" / "cache.json")
        _render_and_write_reports(daily, weekly, config, period, plan.publish_weekly, ad_hoc)

        payload = _build_summary_payload(daily, weekly, cache, period)
        payload["published_weekly"] = False if ad_hoc else plan.publish_weekly
        payload["ad_hoc"] = ad_hoc
        payload["calendar_warnings"] = list(calendar_warnings(config, requested_now.date()))

        # 주간 스냅샷 처리 (ad-hoc은 제외) — published_at 은 발행일(요청 시각)
        if period in ("weekly", "both"):
            _handle_weekly_snapshot(
                payload, config, cache, plan.publish_weekly, ad_hoc, requested_now
            )

        # pending 지문 저장 (ad-hoc은 제외) — 발행되지 않은 주간 지문으로 weekly 섹션을 덮지 않는다
        pending_scope = pending_period(period, plan.publish_weekly)
        if not ad_hoc and pending_scope is not None:
            _save_pending_fingerprints(daily, weekly, pending_scope, config.data_dir)

        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as e:
        logger.exception("파이프라인 오류: %s", e)
        return 1


def _cmd_collect(
    config_path: Path,
    period: Period = "both",
    force_weekly: bool = False,
    now_override: str | None = None,
    ad_hoc: bool = False,
) -> int:
    """파이프라인 1회 실행 → HTML 저장 → 요약용 JSON을 stdout.

    Args:
        config_path: config.yaml 경로
        period: "daily"|"weekly"|"both" (기본값: both)
        force_weekly: 주간 게이트(영업일·이번 주 미발행) 우회 재발행 플래그 — period=weekly 전용,
            운영 기록(raw·스냅샷·등록부·이력)은 쓰지 않는다
        now_override: ISO 타임스탬프 문자열 (선택, None이면 현재 시각 사용)
        ad_hoc: True면 ad-hoc 조회 모드 (dated 파일만, 운영 상태 변경 없음)

    Returns:
        exit code (0=성공)
    """
    # --ad-hoc과 --force-weekly 동시 지정 검증
    if ad_hoc and force_weekly:
        logger.error("--ad-hoc과 --force-weekly는 동시 지정할 수 없습니다")
        return 2

    try:
        config = load_config(config_path)
    except ConfigError as e:
        logger.error("설정 오류: %s", e)
        return 2

    try:
        requested_now, plan = _plan_from_request(config, now_override, period, force_weekly, ad_hoc)
    except ValueError as e:  # --now 형식 오류와 CollectPlanError(ValueError 하위)
        logger.error("%s", e)
        return 2

    missing = missing_tokens(config)
    if missing:
        logger.error("%s", missing_token_hint(missing))
        return 1

    return _run_collect(config, requested_now, plan, period, ad_hoc)


def _inject_file(
    file_path: Path, html: str, summaries_by_repo: dict[str, str], period: str = "daily"
) -> str:
    """파일의 모든 레포 슬롯을 순회하여 치환한다 (헬퍼 함수).

    Args:
        file_path: 파일 경로 (로깅용)
        html: HTML 문자열
        summaries_by_repo: {repo_full_path: summary_text} dict
        period: "daily" (기본) 또는 "weekly" — 요약 제목 동적화

    Returns:
        치환된 HTML 문자열
    """
    for repo, summary_text in summaries_by_repo.items():
        html = inject_ai_summary(html, repo, summary_text, period=period)
    return html


def _inject_group_slots(html: str, groups_by_key: dict[str, Any]) -> str:
    """카드의 그룹별 AI 제목·분석 슬롯을 치환한다 (헬퍼 함수).

    Args:
        html: HTML 문자열
        groups_by_key: {"repo::group_name": {"title": str, "analysis": str}} dict

    Returns:
        치환된 HTML 문자열
    """
    for key, data in groups_by_key.items():
        if "::" not in key or not isinstance(data, dict):
            continue
        repo, group_name = key.split("::", 1)
        title = str(data.get("title", ""))
        analysis = str(data.get("analysis", ""))
        html = inject_group_ai_title(html, repo, group_name, title)
        html = inject_group_analysis(html, repo, group_name, analysis)
    return html


def _inject_targets(targets: list[tuple[Path, dict[str, str], dict[str, Any], str]]) -> None:
    """주입 대상 파일들을 순회하여 슬롯 치환 및 저장 (헬퍼)."""
    for path, summaries_by_repo, groups_by_key, file_period in targets:
        if not path.exists():
            logger.warning("파일 없음: %s", path.name)
            continue
        html = path.read_text(encoding="utf-8")
        # 레포 슬롯도 그룹 데이터도 없으면 스킵
        has_repo_slot = any(ai_summary_slot(repo) in html for repo in summaries_by_repo)
        if not has_repo_slot and not groups_by_key:
            logger.warning("슬롯 없음 (이미 주입됨?): %s", path.name)
            continue
        # 레포 요약 슬롯 + 그룹별 제목·분석 슬롯 치환
        html = _inject_file(path, html, summaries_by_repo, period=file_period)
        html = _inject_group_slots(html, groups_by_key)
        path.write_text(html, encoding="utf-8")


def _inject_into_saved_reports_filtered(
    output_dir: Path,
    summaries: dict[str, Any],
    period: str,
) -> None:
    """저장된 HTML 슬롯을 레포·그룹별로 치환·재저장 (기간별로 필터링).

    Args:
        output_dir: reports 디렉토리
        summaries: {"daily": {...}, "weekly": {...}, "groups": {...}} dict
        period: "daily"|"weekly"|"both"
    """
    daily_summaries = summaries.get("daily", {})
    weekly_summaries = summaries.get("weekly", {})

    groups = summaries.get("groups", {})
    if not isinstance(groups, dict):
        groups = {}
    daily_groups = groups.get("daily", {}) if isinstance(groups.get("daily"), dict) else {}
    weekly_groups = groups.get("weekly", {}) if isinstance(groups.get("weekly"), dict) else {}

    # 기간별 대상 파일 선택
    targets: list[tuple[Path, dict[str, str], dict[str, Any], str]] = []

    if period in ("daily", "both"):
        targets.append((output_dir / "latest.html", daily_summaries, daily_groups, "daily"))
        for path in output_dir.glob("pulse-*.html"):
            if path.name.startswith("pulse-weekly-"):
                continue
            targets.append((path, daily_summaries, daily_groups, "daily"))

    if period in ("weekly", "both"):
        targets.append(
            (output_dir / "latest-weekly.html", weekly_summaries, weekly_groups, "weekly")
        )
        for path in output_dir.glob("pulse-weekly-*.html"):
            targets.append((path, weekly_summaries, weekly_groups, "weekly"))

    _inject_targets(targets)


def _inject_into_saved_reports_ad_hoc(
    output_dir: Path,
    summaries: dict[str, Any],
    period: str,
    target_date: date,
) -> None:
    """ad-hoc 모드: 특정 날짜의 dated 파일만 주입한다 (latest 미접촉).

    Args:
        output_dir: reports 디렉토리
        summaries: {"daily": {...}, "weekly": {...}, "groups": {...}} dict
        period: "daily"|"weekly"|"both"
        target_date: 대상 날짜 (date 객체)
    """
    daily_summaries = summaries.get("daily", {})
    weekly_summaries = summaries.get("weekly", {})
    groups = summaries.get("groups", {})
    if not isinstance(groups, dict):
        groups = {}
    daily_groups = groups.get("daily", {}) if isinstance(groups.get("daily"), dict) else {}
    weekly_groups = groups.get("weekly", {}) if isinstance(groups.get("weekly"), dict) else {}

    # dated 파일만 대상 (latest 제외)
    targets: list[tuple[Path, dict[str, str], dict[str, Any], str]] = []

    if period in ("daily", "both"):
        dated_path = output_dir / f"pulse-{target_date.isoformat()}.html"
        targets.append((dated_path, daily_summaries, daily_groups, "daily"))

    if period in ("weekly", "both"):
        dated_weekly_path = output_dir / f"pulse-weekly-{target_date.isoformat()}.html"
        targets.append((dated_weekly_path, weekly_summaries, weekly_groups, "weekly"))

    _inject_targets(targets)


def _inject_into_saved_reports(output_dir: Path, summaries: dict[str, Any]) -> None:
    """저장된 HTML(dated+latest, daily/weekly 4개 이상) 슬롯을 레포·그룹별로 치환·재저장한다.

    Args:
        output_dir: reports 디렉토리
        summaries: {"daily": {repo: "..."}, "weekly": {...},
                    "groups": {"daily": {"repo::name": {title, analysis}}, "weekly": {...}}} dict
    """
    _inject_into_saved_reports_filtered(output_dir, summaries, "both")


def _cmd_token_set(provider: str) -> int:
    """stdin에서 토큰 값을 읽어 keyring에 저장한다.

    Args:
        provider: "gitlab" or "github"

    Returns:
        exit code (0=성공, 1=실패)
    """
    try:
        # stdin에서 토큰 값 읽기 (argv 미노출)
        token_value = sys.stdin.read().strip()
        if not token_value:
            logger.error("토큰 값이 비어있습니다")
            return 1

        store_token(cast(Provider, provider), token_value)
        print(f"저장됨: {provider} 토큰이 시스템 비밀 저장소에 저장되었습니다.")
        return 0
    except TokenError as e:
        logger.error("토큰 저장 실패: %s", e)
        return 1


def _cmd_token_status() -> int:
    """각 provider의 토큰 출처를 표 형식으로 표시한다.

    Returns:
        exit code (항상 0)
    """
    providers: list[Provider] = ["gitlab", "github"]
    print("Provider | Source  | Available")
    print("---------|---------|----------")

    for provider in providers:
        source = token_source(provider)
        if source:
            available = "✓"
        else:
            source = "none"
            available = "✗"
        print(f"{provider:<8} | {source:<7} | {available}")

    return 0


def _cmd_token_clear(provider: str) -> int:
    """keyring에서 토큰을 제거한다.

    Args:
        provider: "gitlab" or "github"

    Returns:
        exit code (0=성공, 1=실패)
    """
    try:
        clear_token(cast(Provider, provider))
        print(f"제거됨: {provider} 토큰이 시스템 비밀 저장소에서 제거되었습니다.")
        return 0
    except TokenError as e:
        logger.error("토큰 제거 실패: %s", e)
        return 1


def _cmd_backfill_lifecycle(config_path: Path) -> int:
    """data/raw 디렉토리의 모든 날짜별 raw 데이터로부터 수명주기 등록부를 복원한다.

    Args:
        config_path: config.yaml 경로

    Returns:
        exit code (0=성공)
    """
    try:
        config = load_config(config_path)
    except ConfigError as e:
        logger.error("설정 오류: %s", e)
        return 2

    raw_dir = config.data_dir / "raw"
    if not raw_dir.exists():
        logger.info("raw 디렉토리가 없습니다: %s", raw_dir)
        return 0

    # raw 디렉토리의 모든 날짜 폴더를 오름차순으로 수집
    date_dirs: list[tuple[date, Path]] = []
    for item in raw_dir.iterdir():
        if not item.is_dir():
            continue
        try:
            item_date = date.fromisoformat(item.name)
            date_dirs.append((item_date, item))
        except ValueError:
            logger.debug("날짜 형식이 아닌 디렉토리 무시: %s", item.name)
            continue

    date_dirs.sort(key=lambda x: x[0])

    if not date_dirs:
        logger.info("날짜 폴더가 없습니다: %s", raw_dir)
        return 0

    # 등록부 로드 (새로 시작하거나 기존 복원)
    registry = load_registry(registry_path(config.data_dir))
    logger.info("백필 시작: %d개 날짜 폴더 처리", len(date_dirs))

    # 날짜별 순회
    for run_date, date_dir in date_dirs:
        logger.info("처리 중: %s", run_date.isoformat())
        activities: list[RepoActivity] = []

        # 해당 날짜 디렉토리의 모든 JSON 파일 로드
        for json_file in date_dir.glob("*.json"):
            try:
                activity = load_raw_activity(json_file)
                activities.append(activity)
            except Exception as e:
                logger.warning("파일 로드 실패 %s: %s", json_file.name, e)
                continue

        if not activities:
            logger.debug("활동 없음: %s", run_date.isoformat())
            continue

        # collected_at 최댓값을 now로 삼아 168h 필터링 + 그룹핑
        now = max(a.collected_at for a in activities)
        activities_tuple = tuple(activities)

        weekly_activities = filter_activities_to_window(activities_tuple, 168, now)
        weekly_groups, _, _, _ = group_activities(
            activities=weekly_activities, config=config, now=now
        )

        # 그룹에 히스토그램 주입 (등록부 갱신용)
        from pulse.grouper.signals import commit_histogram_by_date

        weekly_groups_enriched = []
        for group in weekly_groups:
            histogram = commit_histogram_by_date(group.commits, 7, run_date)
            enriched_group = replace(group, daily_commit_counts=histogram)
            weekly_groups_enriched.append(enriched_group)
        weekly_groups_tuple = tuple(weekly_groups_enriched)

        # 등록부 갱신
        registry = update_registry(registry, weekly_groups_tuple, run_date, updated_at=now)
        logger.info("  그룹 %d개 처리됨", len(weekly_groups_tuple))

    # 마지막에 한 번 저장
    save_registry(registry, registry_path(config.data_dir))
    logger.info(
        "백필 완료: 등록된 그룹 %d개, 기간 %s~%s",
        len(registry.groups),
        min(date_dirs, key=lambda x: x[0])[0].isoformat(),
        max(date_dirs, key=lambda x: x[0])[0].isoformat(),
    )
    return 0


def _build_effective_groups(
    period: str,
    summaries: dict[str, Any],
    cache: dict[str, Any],
    pending: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """캐시 + pending + summary.json을 합쳐 유효 주입 맵을 구성한다.

    Args:
        period: "daily" or "weekly"
        summaries: summary.json의 groups[period] 섹션
        cache: 분석 캐시
        pending: pending.json의 해당 period 부분

    Returns:
        {repo::name: {title, analysis}} dict
    """
    effective: dict[str, dict[str, str]] = {}

    # pending이 없으면 구 흐름 호환 (캐시 갱신 스킵)
    if not pending:
        return summaries if summaries else {}

    # period별 유효 주입 맵 구성
    for key, fingerprint in pending.items():
        cache_key = f"{key}@{period}"
        entry = cache.get(cache_key)
        if entry and entry.get("seed_fingerprint") == fingerprint:
            effective[key] = {
                "title": entry.get("title", ""),
                "analysis": entry.get("analysis", ""),
            }

    # summary.json이 캐시를 덮어씀
    if summaries:
        effective.update(summaries)

    return effective


def _build_filtered_summaries(
    summaries: dict[str, Any],
    cache: dict[str, Any],
    pending_dict: dict[str, Any],
    period: str,
) -> dict[str, Any]:
    """period 필터링 + 캐시 오버레이를 적용한 주입용 summaries를 구성한다.

    Args:
        summaries: summary.json 원본 dict
        cache: 분석 캐시
        pending_dict: pending.json dict
        period: "daily"|"weekly"|"both"

    Returns:
        {"daily"?: {...}, "weekly"?: {...}, "groups": {period: 유효 주입 맵}} dict
    """
    filtered: dict[str, Any] = {}
    groups_dict = summaries.get("groups", {})
    if not isinstance(groups_dict, dict):
        groups_dict = {}

    filtered_groups: dict[str, Any] = {}
    for period_key in ("daily", "weekly"):
        if period not in (period_key, "both"):
            continue
        filtered[period_key] = summaries.get(period_key, {})
        filtered_groups[period_key] = _build_effective_groups(
            period_key,
            groups_dict.get(period_key, {}),
            cache,
            pending_dict.get(period_key, {}),
        )

    filtered["groups"] = filtered_groups
    return filtered


def _merge_new_analyses_into_cache(
    summaries: dict[str, Any],
    pending_dict: dict[str, Any],
    cache: dict[str, Any],
) -> None:
    """summary.json의 신규 작성 항목만 pending 지문과 함께 캐시에 병합한다 (in-place).

    Args:
        summaries: summary.json 원본 dict (캐시 히트 항목은 여기 없음)
        pending_dict: pending.json dict (이번 collect의 그룹별 지문)
        cache: 분석 캐시 (병합 대상)
    """
    for period_key in ("daily", "weekly"):
        original_groups = summaries.get("groups", {}).get(period_key, {})
        if not isinstance(original_groups, dict):
            continue
        for key, data in original_groups.items():
            if not isinstance(data, dict):
                continue
            if not (data.get("title") or data.get("analysis")):
                continue
            fingerprint = pending_dict.get(period_key, {}).get(key)
            if not fingerprint:
                continue
            cache[f"{key}@{period_key}"] = {
                "period": period_key,
                "seed_fingerprint": fingerprint,
                "title": data.get("title", ""),
                "analysis": data.get("analysis", ""),
                "cached_at": datetime.now().astimezone().isoformat(),
            }


def _cmd_inject(
    config_path: Path,
    summary_path: Path,
    period: str = "both",
    ad_hoc: bool = False,
    date_str: str | None = None,
) -> int:
    """summary.json을 읽어 저장된 HTML 슬롯을 레포·그룹별로 치환·재저장 → 스니펫 stdout.

    Args:
        config_path: config.yaml 경로
        summary_path: summary.json 경로
        period: "daily"|"weekly"|"both" (기본값: both)
        ad_hoc: True면 ad-hoc 모드 (dated 파일만 주입, 캐시 병합 스킵)
        date_str: ad-hoc 모드일 때 필수. 형식: "YYYY-MM-DD"

    Returns:
        exit code (0=성공)
    """
    # ad-hoc 모드 검증: --date 필수 및 형식 검증
    from datetime import date as date_type

    target_date: date_type | None = None
    if ad_hoc:
        if date_str is None:
            logger.error("--ad-hoc 모드 시 --date YYYY-MM-DD가 필수입니다")
            return 2
        try:
            target_date = date_type.fromisoformat(date_str)
        except (ValueError, TypeError):
            logger.error("날짜 형식이 잘못되었습니다: %s (YYYY-MM-DD 형식 필요)", date_str)
            return 2

    try:
        config = load_config(config_path)
    except ConfigError as e:
        logger.error("설정 오류: %s", e)
        return 2

    try:
        summaries = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summaries, dict):
            logger.error("summary.json이 dict이어야 합니다")
            return 1

        cache_path = config.data_dir / "analysis" / "cache.json"
        cache = load_analysis_cache(cache_path)

        if target_date is not None:
            # ad-hoc 모드 (시작부 검증에 의해 target_date 존재 ↔ ad_hoc):
            # pending.json 무시, summary.json만 사용, 캐시 병합 스킵
            filtered_summaries = _build_filtered_summaries(summaries, cache, {}, period)
            _inject_into_saved_reports_ad_hoc(
                config.output_dir, filtered_summaries, period, target_date
            )
        else:
            # 표준 모드: pending + cache + summary 병합
            pending_dict = load_pending(config.data_dir / "analysis" / "pending.json")
            filtered_summaries = _build_filtered_summaries(summaries, cache, pending_dict, period)
            _inject_into_saved_reports_filtered(config.output_dir, filtered_summaries, period)
            _merge_new_analyses_into_cache(summaries, pending_dict, cache)
            save_optional_state("분석 캐시", lambda: save_analysis_cache(cache, cache_path))

        print(build_share_snippet(filtered_summaries))
        return 0
    except Exception as e:
        logger.exception("주입 오류: %s", e)
        return 1


def main() -> int:
    """CLI 인자를 파싱하고 collect/inject/token 서브커맨드를 실행한다."""
    parser = argparse.ArgumentParser(description="Daily Pulse 발행 (Skill용)")
    subparsers = parser.add_subparsers(dest="command", help="서브커맨드")

    collect_parser = subparsers.add_parser("collect", help="수집 → 요약용 JSON 출력")
    collect_parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    collect_parser.add_argument(
        "--period",
        choices=["daily", "weekly", "both"],
        default="both",
        help="발행 대상 (기본값: both)",
    )
    collect_parser.add_argument(
        "--force-weekly",
        action="store_true",
        help=(
            "주간 게이트(영업일·이번 주 미발행)를 우회해 이번 주 주간을 다시 발행한다. "
            "--period weekly 전용 — 그 외 period 와 쓰면 거부된다. "
            "조회 기간은 그 주 월요일 00:00 기준 지난주 월~일, 이름표는 실행일. "
            "운영 기록(raw·스냅샷·등록부·이력)은 쓰지 않는다"
        ),
    )
    collect_parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="기준 시각 (ISO 8601, 예: 2026-07-22T00:00:00+09:00 — 00:00이면 달력 정렬)",
    )
    collect_parser.add_argument(
        "--ad-hoc",
        action="store_true",
        default=False,
        help="ad-hoc 모드: dated 파일만 생성, 운영 상태 불변",
    )

    inject_parser = subparsers.add_parser("inject", help="요약 주입 → 스니펫 출력")
    inject_parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    inject_parser.add_argument("--summary-file", type=Path, required=True, help="summary.json 경로")
    inject_parser.add_argument(
        "--period",
        choices=["daily", "weekly", "both"],
        default="both",
        help="주입 대상 (기본값: both)",
    )
    inject_parser.add_argument(
        "--ad-hoc",
        action="store_true",
        default=False,
        help="ad-hoc 모드: dated 파일만 주입, 캐시 병합 스킵",
    )
    inject_parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="ad-hoc 모드의 대상 날짜 (YYYY-MM-DD). ad-hoc 시 필수",
    )

    token_parser = subparsers.add_parser("token", help="토큰 관리")
    token_subparsers = token_parser.add_subparsers(dest="token_command", help="토큰 명령")

    token_set_parser = token_subparsers.add_parser("set", help="stdin에서 토큰 읽어 저장")
    token_set_parser.add_argument("--provider", choices=["gitlab", "github"], required=True)

    token_subparsers.add_parser("status", help="토큰 출처 표시")

    token_clear_parser = token_subparsers.add_parser("clear", help="토큰 제거")
    token_clear_parser.add_argument("--provider", choices=["gitlab", "github"], required=True)

    backfill_parser = subparsers.add_parser(
        "backfill-lifecycle", help="raw 데이터로부터 수명주기 등록부 복원"
    )
    backfill_parser.add_argument("--config", type=Path, default=Path("config.yaml"))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parser.parse_args()

    if args.command == "collect":
        return _cmd_collect(args.config, args.period, args.force_weekly, args.now, args.ad_hoc)
    elif args.command == "inject":
        return _cmd_inject(args.config, args.summary_file, args.period, args.ad_hoc, args.date)
    elif args.command == "backfill-lifecycle":
        return _cmd_backfill_lifecycle(args.config)
    elif args.command == "token":
        if args.token_command == "set":
            return _cmd_token_set(args.provider)
        elif args.token_command == "status":
            return _cmd_token_status()
        elif args.token_command == "clear":
            return _cmd_token_clear(args.provider)
        else:
            token_parser.print_help()
            return 2
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
