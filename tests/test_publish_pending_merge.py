"""pending.json 지문 저장 테스트 — period 섹션 병합 보존과 period별 report_dates."""

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pulse.analysis_cache import load_pending, save_pending
from pulse.models import DashboardModel, FeatureGroup
from pulse.publish import _save_pending_fingerprints
from tests.conftest import make_feature_group

REPO = "sample-group/sample-repo"


def _key(group_name: str) -> str:
    """pending.json의 그룹 키 형식 (`repo::name`)."""
    return f"{REPO}::{group_name}"


def _make_model(
    period: Literal["daily", "weekly"],
    report_date: date,
    groups: tuple[FeatureGroup, ...],
) -> DashboardModel:
    """지문 저장에 필요한 최소 DashboardModel."""
    return DashboardModel(
        team_name="Test",
        report_date=report_date,
        lookback_hours=24 if period == "daily" else 168,
        summary_line="",
        groups=groups,
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=(REPO,),
        period=period,
    )


def _daily_model(*group_names: str, report_date: date = date(2026, 7, 29)) -> DashboardModel:
    """일간 모델 (그룹 이름만 지정)."""
    return _make_model("daily", report_date, tuple(make_feature_group(name=n) for n in group_names))


def _weekly_model(*group_names: str, report_date: date = date(2026, 7, 27)) -> DashboardModel:
    """주간 모델 (그룹 이름만 지정)."""
    return _make_model(
        "weekly", report_date, tuple(make_feature_group(name=n) for n in group_names)
    )


def _load(data_dir: Path) -> dict[str, Any]:
    """저장된 pending.json을 읽는다."""
    return load_pending(data_dir / "analysis" / "pending.json")


def test_weekly_collect_keeps_daily_fingerprints(tmp_path: Path) -> None:
    """주간 수집이 앞선 일간 수집의 지문을 지우지 않는다.

    일간과 주간을 서로 다른 --now로 따로 수집하는 흐름(일간 오늘·주간 지난 월요일)에서
    뒤 실행이 앞 지문을 덮어쓰면, inject가 그 period의 캐시된 분석을 주입하지 못해
    그룹 슬롯이 빈 채 남는다. 2026-07-29 발행에서 실제로 발생했다.
    """
    daily = _daily_model("ai_assistant")
    weekly = _weekly_model("tiptap")

    _save_pending_fingerprints(daily, weekly, "daily", tmp_path)
    _save_pending_fingerprints(daily, weekly, "weekly", tmp_path)

    pending = _load(tmp_path)
    assert _key("ai_assistant") in pending["daily"]
    assert _key("tiptap") in pending["weekly"]


def test_daily_collect_keeps_weekly_fingerprints(tmp_path: Path) -> None:
    """반대 순서(주간 먼저)에서도 앞 지문이 보존된다."""
    daily = _daily_model("ai_assistant")
    weekly = _weekly_model("tiptap")

    _save_pending_fingerprints(daily, weekly, "weekly", tmp_path)
    _save_pending_fingerprints(daily, weekly, "daily", tmp_path)

    pending = _load(tmp_path)
    assert _key("tiptap") in pending["weekly"]
    assert _key("ai_assistant") in pending["daily"]


def test_same_period_recollect_replaces_section(tmp_path: Path) -> None:
    """같은 period를 다시 수집하면 그 섹션은 통째로 교체된다 (누적 금지).

    섹션 안에서 병합하면 이제 없는 그룹의 낡은 지문이 남아, 나중에 우연히 지문이
    맞는 캐시가 되살아난다. 보존은 period 사이에서만 일어나야 한다.
    """
    weekly = _weekly_model("tiptap")

    _save_pending_fingerprints(_daily_model("사라진_그룹"), weekly, "daily", tmp_path)
    _save_pending_fingerprints(_daily_model("남는_그룹"), weekly, "daily", tmp_path)

    daily_section = _load(tmp_path)["daily"]
    assert _key("사라진_그룹") not in daily_section
    assert _key("남는_그룹") in daily_section


def test_report_dates_recorded_per_period(tmp_path: Path) -> None:
    """report_dates가 period별로 기록된다 — 두 period의 기준일이 다를 수 있다."""
    daily = _daily_model("ai_assistant", report_date=date(2026, 7, 29))
    weekly = _weekly_model("tiptap", report_date=date(2026, 7, 27))

    _save_pending_fingerprints(daily, weekly, "daily", tmp_path)
    _save_pending_fingerprints(daily, weekly, "weekly", tmp_path)

    assert _load(tmp_path)["report_dates"] == {
        "daily": "2026-07-29",
        "weekly": "2026-07-27",
    }


def test_period_both_records_both_sections(tmp_path: Path) -> None:
    """period=both는 두 섹션과 두 날짜를 한 번에 기록한다 (정기 발행 경로)."""
    _save_pending_fingerprints(
        _daily_model("ai_assistant"), _weekly_model("tiptap"), "both", tmp_path
    )

    pending = _load(tmp_path)
    assert _key("ai_assistant") in pending["daily"]
    assert _key("tiptap") in pending["weekly"]
    assert pending["report_dates"] == {"daily": "2026-07-29", "weekly": "2026-07-27"}


def test_legacy_single_report_date_key_is_dropped(tmp_path: Path) -> None:
    """구 형식의 단일 report_date 키는 정리된다 (report_dates가 대체).

    남겨두면 "report_date는 07-29인데 weekly 지문은 07-27 것"인 파일이 되어
    진단할 때 오해를 부른다.
    """
    path = tmp_path / "analysis" / "pending.json"
    save_pending({"report_date": "2026-07-20", "daily": {_key("낡은_그룹"): "deadbeef"}}, path)

    _save_pending_fingerprints(
        _daily_model("ai_assistant"), _weekly_model("tiptap"), "daily", tmp_path
    )

    pending = _load(tmp_path)
    assert "report_date" not in pending
    assert pending["report_dates"] == {"daily": "2026-07-29"}


def test_fingerprints_match_cache_lookup_format(tmp_path: Path) -> None:
    """저장된 지문은 캐시 조회에 쓰이는 값과 같다 (같은 seed면 같은 지문)."""
    from pulse.analysis_cache import compute_group_seed_fingerprint

    group = make_feature_group(name="ai_assistant")
    _save_pending_fingerprints(
        _make_model("daily", date(2026, 7, 29), (group,)),
        _weekly_model("tiptap"),
        "daily",
        tmp_path,
    )

    stored = _load(tmp_path)["daily"]
    assert stored[_key("ai_assistant")] == compute_group_seed_fingerprint(group)
