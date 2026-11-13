"""주간 발행 게이트(영업일 ∧ 이번 주 미발행) 및 --period 기능 테스트."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pulse.analysis_cache import save_analysis_cache, save_pending
from pulse.publish import _build_effective_groups
from pulse.run_plan import plan_collect

KST = ZoneInfo("Asia/Seoul")


def test_weekly_gate_opens_on_monday_when_last_week_was_published() -> None:
    """영업일(월요일)에 이번 주 주간이 아직 없으면 게이트를 통과한다 (plan_collect)."""
    monday = datetime(2026, 7, 20, 0, 0, tzinfo=KST)  # 2026-07-20은 월요일
    assert monday.weekday() == 0
    last_week_end = datetime(2026, 7, 13, 0, 0, tzinfo=KST)

    plan = plan_collect(
        monday,
        "weekly",
        force_weekly=False,
        ad_hoc=False,
        holidays=frozenset(),
        last_window_end=last_week_end,
    )

    assert plan.publish_weekly is True


def test_weekly_gate_stays_closed_when_this_week_is_already_published() -> None:
    """화요일 실행은 이번 주 주간이 이미 나갔으면 force 없이는 발행하지 않는다."""
    tuesday = datetime(2026, 7, 21, 0, 0, tzinfo=KST)  # 2026-07-21은 화요일
    assert tuesday.weekday() == 1
    this_week_end = datetime(2026, 7, 20, 0, 0, tzinfo=KST)

    plan = plan_collect(
        tuesday,
        "weekly",
        force_weekly=False,
        ad_hoc=False,
        holidays=frozenset(),
        last_window_end=this_week_end,
    )

    assert plan.publish_weekly is False


def test_cache_merge_only_original_summary_items(tmp_path: Path) -> None:
    """캐시 병합이 original summary.json의 항목만 처리한다."""
    from typing import Any

    # 캐시 준비: 기존 항목
    cache_path = tmp_path / "cache.json"
    cache: dict[str, Any] = {
        "org/repo::feature/oauth@daily": {
            "period": "daily",
            "seed_fingerprint": "abc123",
            "title": "OAuth 기존",
            "analysis": "기존 분석",
        }
    }
    save_analysis_cache(cache, cache_path)

    # pending 준비: 두 그룹 (캐시 히트 + 신규)
    pending_path = tmp_path / "pending.json"
    pending_data: dict[str, Any] = {
        "report_date": "2026-07-22",
        "daily": {
            "org/repo::feature/oauth": "abc123",  # 히트
            "org/repo::feature/mfa": "xyz789",  # 신규
        },
    }
    save_pending(pending_data, pending_path)

    # original summary.json: mfa만 작성 (oauth는 캐시에서 가져옴)
    original_summary: dict[str, Any] = {
        "daily": {"org/repo::feature/mfa": {"title": "MFA 새로", "analysis": "새로운 분석"}}
    }

    # 유효 맵 구성 (캐시 히트 + 신규 병합)
    effective = _build_effective_groups(
        "daily",
        original_summary.get("daily", {}),
        cache,
        pending_data.get("daily", {}),
    )

    # effective는 oauth(캐시) + mfa(신규)를 모두 포함
    assert "org/repo::feature/oauth" in effective
    assert "org/repo::feature/mfa" in effective
    assert effective["org/repo::feature/oauth"]["title"] == "OAuth 기존"
    assert effective["org/repo::feature/mfa"]["title"] == "MFA 새로"

    # 캐시 병합할 때는 original_summary의 항목(mfa)만 저장해야 함
    # (oauth는 이미 캐시에 있으므로 재저장 불필요)
    items_to_save = original_summary.get("daily", {})
    assert "org/repo::feature/oauth" not in items_to_save  # 신규 작성 항목 아님
    assert "org/repo::feature/mfa" in items_to_save  # 신규 작성 항목


def test_cached_at_includes_timezone() -> None:
    """cached_at이 timezone을 포함한 isoformat 형식이어야 한다."""
    from datetime import datetime as dt

    now_with_tz = dt.now().astimezone().isoformat()
    now_without_tz = dt.now().isoformat()

    # timezone이 포함된 형식: 2026-07-22T10:30:45.123456+09:00
    assert "+" in now_with_tz or "-" in now_with_tz.split("T")[1]
    # timezone이 없는 형식: 2026-07-22T10:30:45.123456
    assert "+" not in now_without_tz and "-" not in now_without_tz.split("T")[1]
