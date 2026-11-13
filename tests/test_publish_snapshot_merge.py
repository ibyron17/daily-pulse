"""주간 스냅샷 발행/병합 통합 테스트 (_cmd_collect 배선 + 병합 로직)."""

import json
import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pulse.analysis_cache import load_pending, save_pending
from pulse.business_calendar import builtin_holiday_years
from pulse.collector.storage import load_weekly_snapshot, save_weekly_snapshot
from tests.conftest import make_feature_group

KST = ZoneInfo("Asia/Seoul")

# pending 지문 단언용 — 일간·주간 스텁 모델의 그룹 이름을 달리해 어느 섹션이 쓰였는지 구분한다
STUB_REPO_PATH = "sample-group/sample-repo"  # make_feature_group 기본 레포
DAILY_GROUP_KEY = f"{STUB_REPO_PATH}::daily-feature"
WEEKLY_GROUP_KEY = f"{STUB_REPO_PATH}::weekly-feature"
# 시드 pending 의 날짜·지문 — 어떤 실행 날짜·그룹과도 달라서 「이번 실행이 덮어썼는가」가 구분된다
SEED_DATE = "2026-07-01"
# 내장 공휴일 표에 없는 해 — 표를 갱신해도 계속 「없는 해」가 되도록 마지막 해 다음 해로 잡는다
YEAR_MISSING_FROM_TABLE = max(builtin_holiday_years()) + 1
# 내장 공휴일 표가 담은 해 — 오래된 해를 표에서 정리해도 깨지지 않게 표의 마지막 해로 잡는다
YEAR_COVERED_BY_TABLE = max(builtin_holiday_years())
SEEDED_DAILY = {"org/repo::old-daily": "old-daily-fingerprint"}
SEEDED_WEEKLY = {"org/repo::old-weekly": "old-weekly-fingerprint"}


def _setup_collect_stubs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """_cmd_collect의 외부 의존(설정·토큰·파이프라인·렌더)을 스텁으로 대체한다."""
    import pulse.publish as publish
    import pulse.renderer as renderer

    config = type(
        "Config",
        (),
        {
            "data_dir": tmp_path / "data",
            "output_dir": tmp_path / "reports",
            "timezone_name": "Asia/Seoul",
            "weekend_catchup": True,
            "extra_holidays": (),
            "holiday_calendar": "kr",
            # run_pipeline 스텁이 받은 (now, persist_state, weekly_window_end) 기록
            "pipeline_calls": [],
            # HTML 쓰기 스텁이 받은 (report_date, write_latest) 기록 — 어느 HTML 이 쓰였는지 단언용
            "daily_writes": [],
            "weekly_writes": [],
        },
    )()

    def _fake_extract(model: Any, cache: Any = None) -> dict[str, Any]:
        # 실제 추출처럼 모델의 이름표(report_date)와 조회 창 끝(window_end)을 그대로 싣는다
        return {
            "report_date": model.report_date.isoformat(),
            "period": model.period,
            "window_end": model.window_end.isoformat(),
            "groups": {},
        }

    monkeypatch.setattr(publish, "load_config", lambda path: config)
    monkeypatch.setattr(publish, "missing_tokens", lambda cfg: [])

    def _fake_run_pipeline(
        cfg: Any,
        now: datetime | None = None,
        persist_state: bool = True,
        weekly_window_end: datetime | None = None,
    ) -> tuple[Any, Any]:
        assert now is not None
        config.pipeline_calls.append((now, persist_state, weekly_window_end))
        # 실제 파이프라인처럼 두 모델의 이름표(report_date)는 실행 날짜를 따르고,
        # 주간 모델의 창 끝은 weekly_window_end(없으면 now)다
        daily_model = type(
            "Model",
            (),
            {
                "groups": (make_feature_group(name="daily-feature"),),
                "report_date": now.date(),
                "window_end": now,
                "period": "daily",
            },
        )()
        weekly_model = type(
            "Model",
            (),
            {
                "groups": (make_feature_group(name="weekly-feature"),),
                "report_date": now.date(),
                "window_end": weekly_window_end or now,
                "period": "weekly",
            },
        )()
        return daily_model, weekly_model

    monkeypatch.setattr(publish, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(publish, "extract_summary_input_by_repo", _fake_extract)
    monkeypatch.setattr(renderer, "render_html", lambda model: "<html></html>")

    def _fake_write_report(
        html: str, output_dir: Path, report_date: date, write_latest: bool = True
    ) -> tuple[Path, Path | None]:
        config.daily_writes.append((report_date, write_latest))
        return Path("pulse-2026-07-20.html"), Path("latest.html")

    def _fake_write_weekly_report(
        html: str, output_dir: Path, report_date: date, write_latest: bool = True
    ) -> tuple[Path, Path | None]:
        config.weekly_writes.append((report_date, write_latest))
        return Path("pulse-weekly-2026-07-20.html"), Path("latest-weekly.html")

    monkeypatch.setattr(renderer, "write_report", _fake_write_report)
    monkeypatch.setattr(renderer, "write_weekly_report", _fake_write_weekly_report)
    return config


def _seed_pending(config: Any) -> Path:
    """실행 전 pending.json 시드 — 일간·주간 지문과 날짜가 모두 이번 실행 값과 다르다."""
    pending_path: Path = config.data_dir / "analysis" / "pending.json"
    save_pending(
        {
            "daily": dict(SEEDED_DAILY),
            "weekly": dict(SEEDED_WEEKLY),
            "report_dates": {"daily": SEED_DATE, "weekly": SEED_DATE},
        },
        pending_path,
    )
    return pending_path


def _seed_weekly_record(
    config: Any, window_end_iso: str, report_date: str, published_at: str
) -> Path:
    """실행 전 weekly_publish/latest.json 시드 — 마지막으로 발행된 주간 기록."""
    save_weekly_snapshot(
        config.data_dir,
        {
            "report_date": report_date,
            "period": "weekly",
            "window_start": "2026-09-28T00:00:00+09:00",
            "window_end": window_end_iso,
            "published_at": published_at,
            "groups": {},
        },
    )
    record_path: Path = config.data_dir / "weekly_publish" / "latest.json"
    return record_path


# 이번 주(2026-07-20 월 ~ 07-26 일) 주간이 이미 발행됐음을 뜻하는 기록의 창 끝
THIS_WEEK_WINDOW_END = "2026-07-20T00:00:00+09:00"
LAST_WEEK_WINDOW_END = "2026-07-13T00:00:00+09:00"


def test_cmd_collect_saves_snapshot_on_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """월요일 발행 실행 시 _cmd_collect가 published_at 포함 스냅샷을 저장한다."""
    from pulse.publish import _cmd_collect

    config = _setup_collect_stubs(monkeypatch, tmp_path)

    exit_code = _cmd_collect(
        Path("dummy.yaml"), period="weekly", now_override="2026-07-20T00:00:00+09:00"
    )

    assert exit_code == 0
    loaded = load_weekly_snapshot(config.data_dir)
    assert loaded is not None
    assert loaded["report_date"] == "2026-07-20"
    assert loaded["published_at"] == "2026-07-20T00:00:00+09:00"
    payload = json.loads(capsys.readouterr().out)
    assert payload["published_weekly"] is True


def test_cmd_collect_replaces_weekly_with_snapshot_on_non_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """비발행(화요일) 실행 시 _cmd_collect의 weekly 섹션이 스냅샷으로 교체된다."""
    from pulse.publish import _cmd_collect

    config = _setup_collect_stubs(monkeypatch, tmp_path)
    save_weekly_snapshot(
        config.data_dir,
        {
            "report_date": "2026-07-13",
            "period": "weekly",
            "window_end": THIS_WEEK_WINDOW_END,  # 이번 주 주간은 이미 나갔다
            "groups": {},
        },
    )

    exit_code = _cmd_collect(
        Path("dummy.yaml"), period="weekly", now_override="2026-07-21T00:00:00+09:00"
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["published_weekly"] is False
    assert payload["weekly"]["report_date"] == "2026-07-13"


def test_cmd_collect_omits_weekly_when_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """비발행(토요일) 실행 + 스냅샷 부재 시 payload에서 weekly 섹션이 생략된다."""
    from pulse.publish import _cmd_collect

    _setup_collect_stubs(monkeypatch, tmp_path)

    exit_code = _cmd_collect(
        Path("dummy.yaml"), period="weekly", now_override="2026-07-25T00:00:00+09:00"
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["published_weekly"] is False
    assert "weekly" not in payload


class TestCollectWiringWithCollectPlan:
    """_cmd_collect 가 plan_collect 결과로 기준 시각·발행·pending 범위를 정한다."""

    def test_forced_republish_keeps_run_date_label_with_monday_window_and_skips_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """W4: 화요일 강제 재발행 — now 는 화요일 그대로, 창 끝만 월요일, 운영 기록은 안 쓴다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="weekly",
            force_weekly=True,
            now_override="2026-07-21T00:00:00+09:00",
        )

        assert exit_code == 0
        assert config.pipeline_calls == [
            (
                datetime(2026, 7, 21, 0, 0, tzinfo=KST),
                False,
                datetime(2026, 7, 20, 0, 0, tzinfo=KST),
            )
        ]
        loaded = load_weekly_snapshot(config.data_dir)
        assert loaded is not None
        assert loaded["published_at"] == "2026-07-21T00:00:00+09:00"
        assert loaded["report_date"] == "2026-07-21"
        assert loaded["window_end"] == THIS_WEEK_WINDOW_END
        payload = json.loads(capsys.readouterr().out)
        assert payload["published_weekly"] is True

    def test_utc_now_is_converted_to_config_timezone_before_planning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """W5: UTC 로 준 --now(= KST 화 00:00)도 KST 로 바꿔 계획하고 KST 로 발행한다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="weekly",
            force_weekly=True,
            now_override="2026-07-20T15:00:00Z",  # = 2026-07-21(화) 00:00 KST
        )

        assert exit_code == 0
        assert config.pipeline_calls == [
            (
                datetime(2026, 7, 21, 0, 0, tzinfo=KST),
                False,
                datetime(2026, 7, 20, 0, 0, tzinfo=KST),
            )
        ]
        assert str(config.pipeline_calls[0][0].tzinfo) == "Asia/Seoul"
        assert str(config.pipeline_calls[0][2].tzinfo) == "Asia/Seoul"
        loaded = load_weekly_snapshot(config.data_dir)
        assert loaded is not None
        assert loaded["published_at"] == "2026-07-21T00:00:00+09:00"

    def test_daily_run_rewrites_only_the_daily_pending_section(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """period=daily: daily 지문·날짜는 이번 실행 값으로 새로 쓰이고 weekly 는 시드 그대로다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = _seed_pending(config)

        _cmd_collect(Path("dummy.yaml"), period="daily", now_override="2026-07-22T00:00:00+09:00")

        pending = load_pending(pending_path)
        assert set(pending["daily"]) == {DAILY_GROUP_KEY}  # 시드 지문은 통째로 교체
        assert pending["report_dates"]["daily"] == "2026-07-22"
        assert pending["weekly"] == SEEDED_WEEKLY
        assert pending["report_dates"]["weekly"] == SEED_DATE

    def test_monday_midnight_both_rewrites_both_pending_sections(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """월 00:00 both: 주간을 발행하므로 daily·weekly 두 섹션이 모두 새로 쓰인다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = _seed_pending(config)

        _cmd_collect(Path("dummy.yaml"), period="both", now_override="2026-07-20T00:00:00+09:00")

        pending = load_pending(pending_path)
        assert set(pending["daily"]) == {DAILY_GROUP_KEY}
        assert set(pending["weekly"]) == {WEEKLY_GROUP_KEY}
        assert pending["report_dates"] == {"daily": "2026-07-20", "weekly": "2026-07-20"}

    def test_non_publishing_both_run_rewrites_daily_and_keeps_published_weekly_fingerprints(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """화요일 both(이번 주 주간 발행됨): daily 는 갱신, weekly 섹션은 덮지 않는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = _seed_pending(config)
        _seed_weekly_record(config, THIS_WEEK_WINDOW_END, "2026-07-20", "2026-07-20T00:00:00+09:00")

        exit_code = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-21T00:00:00+09:00"
        )

        assert exit_code == 0
        assert config.pipeline_calls == [(datetime(2026, 7, 21, 0, 0, tzinfo=KST), True, None)]
        pending = load_pending(pending_path)
        assert set(pending["daily"]) == {DAILY_GROUP_KEY}
        assert pending["report_dates"]["daily"] == "2026-07-21"
        assert pending["weekly"] == SEEDED_WEEKLY
        assert pending["report_dates"]["weekly"] == SEED_DATE
        assert json.loads(capsys.readouterr().out)["published_weekly"] is False

    def test_forced_weekly_republish_rewrites_only_the_weekly_pending_section_with_run_date(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """W4: weekly 강제 재발행 — weekly 만 실행일 날짜로 새로 쓰이고 daily 는 시드 그대로다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = _seed_pending(config)

        _cmd_collect(
            Path("dummy.yaml"),
            period="weekly",
            force_weekly=True,
            now_override="2026-07-21T00:00:00+09:00",
        )

        pending = load_pending(pending_path)
        assert set(pending["weekly"]) == {WEEKLY_GROUP_KEY}
        assert pending["report_dates"]["weekly"] == "2026-07-21"  # 이름표는 실행일(화요일)
        assert pending["daily"] == SEEDED_DAILY
        assert pending["report_dates"]["daily"] == SEED_DATE

    def test_non_publishing_weekly_run_does_not_write_pending_at_all(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """화요일 weekly(force 없음, 이번 주 발행됨): pending 을 만들지도 바꾸지도 않는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = config.data_dir / "analysis" / "pending.json"
        _seed_weekly_record(config, THIS_WEEK_WINDOW_END, "2026-07-20", "2026-07-20T00:00:00+09:00")

        _cmd_collect(Path("dummy.yaml"), period="weekly", now_override="2026-07-21T00:00:00+09:00")
        assert not pending_path.exists()

        _seed_pending(config)
        seeded_bytes = pending_path.read_bytes()
        _cmd_collect(Path("dummy.yaml"), period="weekly", now_override="2026-07-21T00:00:00+09:00")
        assert pending_path.read_bytes() == seeded_bytes

    @pytest.mark.parametrize("seeded", [False, True])
    @pytest.mark.parametrize("period", ["daily", "weekly", "both"])
    def test_ad_hoc_never_writes_pending(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, period: str, seeded: bool
    ) -> None:
        """ad-hoc 은 어떤 period 에서도 pending 을 만들지도 바꾸지도 않는다 (운영 상태 불변)."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        pending_path = config.data_dir / "analysis" / "pending.json"
        if seeded:
            _seed_pending(config)
        before = pending_path.read_bytes() if seeded else None

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period=period,  # type: ignore[arg-type]
            now_override="2026-07-22T12:00:00+09:00",
            ad_hoc=True,
        )

        assert exit_code == 0
        weekly_end = None if period == "daily" else datetime(2026, 7, 20, 0, 0, tzinfo=KST)
        assert config.pipeline_calls == [
            (datetime(2026, 7, 22, 12, 0, tzinfo=KST), False, weekly_end)
        ]
        if seeded:
            assert pending_path.read_bytes() == before
        else:
            assert not pending_path.exists()

    def test_both_with_force_weekly_on_tuesday_is_rejected_before_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        with caplog.at_level(logging.ERROR, logger="pulse.publish"):
            exit_code = _cmd_collect(
                Path("dummy.yaml"),
                period="both",
                force_weekly=True,
                now_override="2026-07-21T00:00:00+09:00",
            )

        assert exit_code == 2
        assert config.pipeline_calls == []
        assert capsys.readouterr().out == ""
        assert any("--period weekly" in record.getMessage() for record in caplog.records)

    def test_now_without_timezone_is_rejected_before_pipeline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--now 형식 오류는 기존처럼 exit 2 이고 파이프라인을 돌리지 않는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        exit_code = _cmd_collect(
            Path("dummy.yaml"), period="weekly", now_override="2026-07-21T00:00:00"
        )

        assert exit_code == 2
        assert config.pipeline_calls == []

    def test_monday_midnight_both_publishes_weekly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        _cmd_collect(Path("dummy.yaml"), period="both", now_override="2026-07-20T00:00:00+09:00")

        monday = datetime(2026, 7, 20, 0, 0, tzinfo=KST)
        assert config.pipeline_calls == [(monday, True, monday)]
        assert json.loads(capsys.readouterr().out)["published_weekly"] is True

    def test_monday_daytime_both_reuses_published_weekly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """월요일 낮 both 도 이번 주 주간이 이미 나갔으면 새로 만들지 않고 발행분을 쓴다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        save_weekly_snapshot(
            config.data_dir,
            {
                "report_date": "2026-07-20",
                "period": "weekly",
                "window_end": THIS_WEEK_WINDOW_END,
                "groups": {},
                "published_at": "x",
            },
        )

        _cmd_collect(Path("dummy.yaml"), period="both", now_override="2026-07-20T09:00:00+09:00")

        payload = json.loads(capsys.readouterr().out)
        assert payload["published_weekly"] is False
        assert payload["weekly"]["published_at"] == "x"  # 스냅샷(00:00 발행분) 그대로

    @pytest.mark.parametrize(
        ("period", "now", "force", "last_window_end", "expected_weekly_dates"),
        [
            pytest.param(
                "both",
                "2026-07-21T00:00:00+09:00",
                False,
                THIS_WEEK_WINDOW_END,
                [],
                id="화 both·이번 주 발행됨: 안 씀",
            ),
            pytest.param(
                "both",
                "2026-07-21T00:00:00+09:00",
                False,
                LAST_WEEK_WINDOW_END,
                [date(2026, 7, 21)],
                id="화 both·지난주 기록: 보완 발행(이름표 화요일)",
            ),
            pytest.param(
                "both",
                "2026-07-20T00:00:00+09:00",
                False,
                LAST_WEEK_WINDOW_END,
                [date(2026, 7, 20)],
                id="월 00:00 both·지난주 기록: 주간 1회",
            ),
            pytest.param(
                "weekly",
                "2026-07-21T00:00:00+09:00",
                True,
                THIS_WEEK_WINDOW_END,
                [date(2026, 7, 21)],
                id="화 weekly --force-weekly·이번 주 발행됨: 화요일 이름표로 1회",
            ),
            pytest.param(
                "weekly",
                "2026-07-21T00:00:00+09:00",
                False,
                THIS_WEEK_WINDOW_END,
                [],
                id="화 weekly(force 없음)·이번 주 발행됨: 안 씀",
            ),
            pytest.param(
                "both",
                "2026-07-20T09:00:00+09:00",
                False,
                LAST_WEEK_WINDOW_END,
                [date(2026, 7, 20)],
                id="월 낮 both·지난주 기록: 발행",
            ),
            pytest.param(
                "both",
                "2026-07-20T09:00:00+09:00",
                False,
                THIS_WEEK_WINDOW_END,
                [],
                id="월 낮 both·이번 주 발행됨: 안 씀",
            ),
            pytest.param(
                "daily",
                "2026-07-20T00:00:00+09:00",
                False,
                LAST_WEEK_WINDOW_END,
                [],
                id="월 00:00 daily: 안 씀",
            ),
            pytest.param(
                "both",
                "2026-07-25T00:00:00+09:00",
                False,
                LAST_WEEK_WINDOW_END,
                [],
                id="토 both·지난주 기록: 주말은 안 씀",
            ),
        ],
    )
    def test_weekly_html_is_written_only_when_weekly_is_published(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        period: str,
        now: str,
        force: bool,
        last_window_end: str,
        expected_weekly_dates: list[date],
    ) -> None:
        """W9: 주간 HTML(dated·latest-weekly)은 주간을 발행하는 실행에서만 쓰인다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        _seed_weekly_record(config, last_window_end, "2026-07-13", "2026-07-13T00:00:00+09:00")

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period=period,  # type: ignore[arg-type]
            force_weekly=force,
            now_override=now,
        )

        assert exit_code == 0
        # write_latest=True: 운영 실행은 latest-weekly.html 도 함께 갱신한다
        assert config.weekly_writes == [(day, True) for day in expected_weekly_dates]
        expected_daily_writes = 0 if period == "weekly" else 1
        assert len(config.daily_writes) == expected_daily_writes

    @pytest.mark.parametrize(
        ("period", "expects_weekly", "expects_daily"),
        [
            pytest.param("weekly", True, False, id="ad-hoc weekly"),
            pytest.param("both", True, True, id="ad-hoc both"),
            pytest.param("daily", False, True, id="ad-hoc daily"),
        ],
    )
    def test_ad_hoc_writes_requested_html_as_dated_files_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        period: str,
        expects_weekly: bool,
        expects_daily: bool,
    ) -> None:
        """ad-hoc 은 주간 미발행 상태여도 요청한 HTML 을 쓰되 latest 는 건드리지 않는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period=period,  # type: ignore[arg-type]
            now_override="2026-07-22T12:00:00+09:00",
            ad_hoc=True,
        )

        assert exit_code == 0
        requested_date = date(2026, 7, 22)
        assert config.weekly_writes == ([(requested_date, False)] if expects_weekly else [])
        assert config.daily_writes == ([(requested_date, False)] if expects_daily else [])
        # W10: 주간을 쓰는 ad-hoc 도 창 끝을 지난주 월~일 기준(그 주 월요일)으로 맞춘다
        weekly_end = datetime(2026, 7, 20, 0, 0, tzinfo=KST) if period != "daily" else None
        assert config.pipeline_calls == [
            (datetime(2026, 7, 22, 12, 0, tzinfo=KST), False, weekly_end)
        ]

    def test_payload_calendar_warnings_empty_for_covered_year(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pulse.publish import _cmd_collect

        _setup_collect_stubs(monkeypatch, tmp_path)

        _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            now_override=f"{YEAR_COVERED_BY_TABLE}-07-21T00:00:00+09:00",
        )

        assert json.loads(capsys.readouterr().out)["calendar_warnings"] == []

    def test_payload_calendar_warnings_report_year_missing_from_table(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pulse.publish import _cmd_collect

        _setup_collect_stubs(monkeypatch, tmp_path)

        _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            now_override=f"{YEAR_MISSING_FROM_TABLE}-01-02T00:00:00+09:00",
        )

        warnings = json.loads(capsys.readouterr().out)["calendar_warnings"]
        assert len(warnings) == 1
        assert str(YEAR_MISSING_FROM_TABLE) in warnings[0]

    def test_payload_calendar_warnings_empty_when_catchup_is_off(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.weekend_catchup = False

        _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            now_override=f"{YEAR_MISSING_FROM_TABLE}-01-02T00:00:00+09:00",
        )

        assert json.loads(capsys.readouterr().out)["calendar_warnings"] == []

    def test_payload_calendar_warnings_empty_when_calendar_is_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """T5-3: 표를 쓰지 않는 none 이면 표에 없는 해여도 표 갱신 경고를 payload 에 싣지 않는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.holiday_calendar = "none"

        _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            now_override=f"{YEAR_MISSING_FROM_TABLE}-01-02T00:00:00+09:00",
        )

        assert json.loads(capsys.readouterr().out)["calendar_warnings"] == []


class TestWeeklyPublishGate:
    """주간 발행 게이트(영업일 ∧ 이번 주 미발행)가 _cmd_collect 배선에서 실제로 동작한다 (W1~W8)."""

    TODAYS_RECORD_END = "2026-10-05T00:00:00+09:00"  # 2026-10-06 사고 때 실제로 나간 주간의 창 끝

    @staticmethod
    def _october_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
        """개천절 대체공휴일(10/5 월)을 명시 주입한 스텁 설정 — 내장 표 내용에 기대지 않는다."""
        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.extra_holidays = (date(2026, 10, 5),)
        return config

    def _seed_todays_record(self, config: Any) -> Path:
        return _seed_weekly_record(
            config, self.TODAYS_RECORD_END, "2026-10-05", "2026-10-05T00:00:00+09:00"
        )

    def test_wednesday_run_after_todays_record_does_not_publish_again(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """W1(R5): 오늘 나간 주간(이름표 10/5) 기록이 있으면 10/7 정기 실행은 일간만 낸다."""
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        record_path = self._seed_todays_record(config)
        record_before = record_path.read_bytes()
        pending_path = _seed_pending(config)

        exit_code = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-10-07T00:00:00+09:00"
        )

        assert exit_code == 0
        assert config.pipeline_calls == [(datetime(2026, 10, 7, 0, 0, tzinfo=KST), True, None)]
        assert config.weekly_writes == []
        assert config.daily_writes == [(date(2026, 10, 7), True)]
        payload = json.loads(capsys.readouterr().out)
        assert payload["published_weekly"] is False
        assert payload["weekly"]["report_date"] == "2026-10-05"
        assert record_path.read_bytes() == record_before
        pending = load_pending(pending_path)
        assert pending["weekly"] == SEEDED_WEEKLY
        assert pending["report_dates"] == {"daily": "2026-10-07", "weekly": SEED_DATE}

    def test_make_up_publish_on_tuesday_labels_run_date_and_next_day_does_not_repeat(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """W2: 월요일 실행이 빠진 주는 화요일이 채우고(이름표 화요일) 수요일은 반복하지 않는다."""
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        record_path = _seed_weekly_record(
            config, "2026-09-28T00:00:00+09:00", "2026-09-28", "2026-09-28T00:00:00+09:00"
        )
        _seed_pending(config)

        first_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-10-06T00:00:00+09:00"
        )

        assert first_exit == 0
        assert config.pipeline_calls == [
            (
                datetime(2026, 10, 6, 0, 0, tzinfo=KST),
                True,
                datetime(2026, 10, 5, 0, 0, tzinfo=KST),
            )
        ]
        assert config.weekly_writes == [(date(2026, 10, 6), True)]
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["published_at"] == "2026-10-06T00:00:00+09:00"
        assert record["report_date"] == "2026-10-06"
        assert record["window_end"] == "2026-10-05T00:00:00+09:00"
        assert (
            load_pending(config.data_dir / "analysis" / "pending.json")["report_dates"]["weekly"]
            == "2026-10-06"
        )
        assert json.loads(capsys.readouterr().out)["published_weekly"] is True

        second_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-10-07T00:00:00+09:00"
        )

        assert second_exit == 0
        assert config.weekly_writes == [(date(2026, 10, 6), True)]  # 늘지 않는다
        assert json.loads(capsys.readouterr().out)["published_weekly"] is False

    def test_holiday_monday_publishes_no_weekly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """W3: 월요일이 공휴일이면 그날은 일간만 나간다."""
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        _seed_weekly_record(
            config, "2026-09-28T00:00:00+09:00", "2026-09-28", "2026-09-28T00:00:00+09:00"
        )

        exit_code = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-10-05T00:00:00+09:00"
        )

        assert exit_code == 0
        assert config.weekly_writes == []
        assert config.daily_writes == [(date(2026, 10, 5), True)]

    def test_company_holiday_from_config_blocks_weekly_on_that_monday(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """설정의 extra_holidays 가 주간 발행일 판단에 쓰인다 (내장 표에 없는 2026-07-20 사용)."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.extra_holidays = (date(2026, 7, 20),)  # 회사 휴무로 쉬는 월요일
        _seed_weekly_record(config, LAST_WEEK_WINDOW_END, "2026-07-13", "2026-07-13T00:00:00+09:00")

        monday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-20T00:00:00+09:00"
        )

        assert monday_exit == 0
        assert config.weekly_writes == []  # 휴무 월요일은 주간을 내지 않는다

        tuesday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-21T00:00:00+09:00"
        )

        assert tuesday_exit == 0
        assert config.weekly_writes == [(date(2026, 7, 21), True)]  # 다음 영업일이 채운다

    def test_weekly_gate_respects_holidays_even_when_weekend_catchup_is_off(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """weekend_catchup=false 여도 주간 발행일 판단은 휴무일을 반영한다 (일간 폭만 달라진다).

        휴무일을 설정의 extra_holidays 로만 주는 날(내장 표에 없는 2026-07-20)을 쓴다 —
        내장 표에 있는 날이면 설정 값을 버려도 구분되지 않는다.
        """
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.weekend_catchup = False
        config.extra_holidays = (date(2026, 7, 20),)  # 회사 휴무로 쉬는 월요일
        _seed_weekly_record(config, LAST_WEEK_WINDOW_END, "2026-07-13", "2026-07-13T00:00:00+09:00")

        monday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-20T00:00:00+09:00"
        )

        assert monday_exit == 0
        assert config.weekly_writes == []  # 휴무 월요일은 catchup 이 꺼져 있어도 주간을 내지 않는다

        tuesday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-21T00:00:00+09:00"
        )

        assert tuesday_exit == 0
        assert config.weekly_writes == [(date(2026, 7, 21), True)]  # 다음 영업일이 채운다

    @pytest.mark.parametrize(
        ("calendar", "expected_weekly_writes"),
        [
            pytest.param("kr", [], id="kr: 10/5 대체공휴일이라 주간을 내지 않는다"),
            pytest.param("none", [(date(2026, 10, 5), True)], id="none: 평일이라 주간을 낸다"),
        ],
    )
    def test_holiday_calendar_decides_whether_korean_holiday_monday_publishes_weekly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        calendar: str,
        expected_weekly_writes: list[tuple[date, bool]],
    ) -> None:
        """T5-1: 주간 발행 게이트가 설정의 holiday_calendar 를 따른다.

        10/5 가 내장 표에 있다는 사실에 일부러 기댄다(관심사는 「none 이 표를 끄는가」).
        표 자체의 무결성은 tests/test_kr_holidays.py 가 지킨다.
        """
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.holiday_calendar = calendar
        _seed_weekly_record(
            config, "2026-09-28T00:00:00+09:00", "2026-09-28", "2026-09-28T00:00:00+09:00"
        )

        exit_code = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-10-05T00:00:00+09:00"
        )

        assert exit_code == 0
        assert config.weekly_writes == expected_weekly_writes

    def test_extra_holidays_still_block_weekly_when_calendar_is_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """T5-2: none 은 내장 표만 끈다 — 설정의 extra_holidays 는 그날 주간 발행을 막는다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)
        config.holiday_calendar = "none"
        config.extra_holidays = (date(2026, 7, 20),)  # 회사 휴무로 쉬는 월요일
        _seed_weekly_record(config, LAST_WEEK_WINDOW_END, "2026-07-13", "2026-07-13T00:00:00+09:00")

        monday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-20T00:00:00+09:00"
        )

        assert monday_exit == 0
        assert config.weekly_writes == []

        tuesday_exit = _cmd_collect(
            Path("dummy.yaml"), period="both", now_override="2026-07-21T00:00:00+09:00"
        )

        assert tuesday_exit == 0
        assert config.weekly_writes == [(date(2026, 7, 21), True)]

    @pytest.mark.parametrize(
        ("period", "now"),
        [
            pytest.param("both", "2026-07-20T00:00:00+09:00", id="both 월 00:00"),
            pytest.param("both", "2026-07-21T00:00:00+09:00", id="both 화 00:00"),
            pytest.param("daily", "2026-07-21T00:00:00+09:00", id="daily"),
        ],
    )
    def test_force_weekly_is_rejected_for_other_periods_at_any_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        period: str,
        now: str,
    ) -> None:
        """W6: --force-weekly 는 --period weekly 전용 — 월 00:00 예외 없이 거부하고 안내한다."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        with caplog.at_level(logging.ERROR, logger="pulse.publish"):
            exit_code = _cmd_collect(
                Path("dummy.yaml"),
                period=period,  # type: ignore[arg-type]
                force_weekly=True,
                now_override=now,
            )

        assert exit_code == 2
        assert config.pipeline_calls == []
        assert capsys.readouterr().out == ""
        assert any("--period weekly" in record.getMessage() for record in caplog.records)

    def test_corrupt_record_counts_as_unpublished_and_logs_missing_window_end(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """W7: 창 끝을 못 읽는 기록은 미발행으로 보고, 로그에 None 으로 드러난다."""
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        _seed_weekly_record(config, "garbage", "2026-10-05", "2026-10-05T00:00:00+09:00")

        with caplog.at_level(logging.INFO, logger="pulse.publish"):
            exit_code = _cmd_collect(
                Path("dummy.yaml"), period="both", now_override="2026-10-06T00:00:00+09:00"
            )

        assert exit_code == 0
        assert config.weekly_writes == [(date(2026, 10, 6), True)]
        assert any("마지막 발행 창 끝 None" in record.getMessage() for record in caplog.records)

    def test_decision_log_states_not_publishing_with_its_evidence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """W8: 발행 안 함 판단과 근거(기준일·이번 주 월요일·마지막 발행 창 끝)가 한 줄로 남는다."""
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        self._seed_todays_record(config)

        with caplog.at_level(logging.INFO, logger="pulse.publish"):
            _cmd_collect(
                Path("dummy.yaml"), period="both", now_override="2026-10-07T00:00:00+09:00"
            )

        messages = [record.getMessage() for record in caplog.records]
        assert (
            "주간 발행 판단: 발행 안 함 (기준일 2026-10-07, 이번 주 월요일 2026-10-05, "
            "마지막 발행 창 끝 2026-10-05T00:00:00+09:00)"
        ) in messages

    def test_decision_log_states_publishing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pulse.publish import _cmd_collect

        config = self._october_config(monkeypatch, tmp_path)
        _seed_weekly_record(
            config, "2026-09-28T00:00:00+09:00", "2026-09-28", "2026-09-28T00:00:00+09:00"
        )

        with caplog.at_level(logging.INFO, logger="pulse.publish"):
            _cmd_collect(
                Path("dummy.yaml"), period="both", now_override="2026-10-06T00:00:00+09:00"
            )

        assert any(
            record.getMessage().startswith("주간 발행 판단: 발행 (기준일 2026-10-06")
            for record in caplog.records
        )

    def test_decision_log_is_skipped_for_daily(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """period=daily 는 주간과 무관하므로 주간 판단 로그를 남기지 않는다."""
        from pulse.publish import _cmd_collect

        self._october_config(monkeypatch, tmp_path)

        with caplog.at_level(logging.INFO, logger="pulse.publish"):
            _cmd_collect(
                Path("dummy.yaml"), period="daily", now_override="2026-10-07T00:00:00+09:00"
            )

        assert not any("주간 발행 판단" in record.getMessage() for record in caplog.records)


def test_weekly_snapshot_replaced_on_non_publish() -> None:
    """비발행 실행 시 주간 섹션이 스냅샷으로 교체된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # 이전 발행 스냅샷 저장
        prev_snapshot = {
            "report_date": "2026-07-21",
            "repos": {"org/repo": {"group_count": 1}},
            "groups": {
                "org/repo::feature": {
                    "name": "feature",
                    "stage": "reviewing",
                    "cached": False,
                }
            },
            "published_at": datetime(2026, 7, 21, 0, 0, 0).isoformat(),
        }
        save_weekly_snapshot(data_dir, prev_snapshot)

        # 비발행 실행의 payload (신선한 데이터)
        fresh_weekly = {
            "report_date": "2026-07-23",
            "repos": {"org/repo": {"group_count": 2}},
            "groups": {"org/repo::feature": {"name": "feature", "stage": "merged"}},
        }

        # 스냅샷 병합 (비발행 시뮬레이션)
        from pulse.publish import _merge_snapshot_if_not_publishing

        payload: dict[str, Any] = {"weekly": fresh_weekly}
        config_mock = type("Config", (), {"data_dir": data_dir})()
        _merge_snapshot_if_not_publishing(payload, config_mock)

        # 확인: payload의 weekly가 스냅샷으로 교체됨
        assert payload["weekly"]["report_date"] == "2026-07-21"
        assert payload["weekly"]["published_at"] == prev_snapshot["published_at"]
        assert payload["weekly"]["repos"]["org/repo"]["group_count"] == 1


def test_weekly_section_removed_when_snapshot_missing() -> None:
    """스냅샷이 없으면 payload에서 weekly 섹션이 제거된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # 스냅샷 없음 (처음 발행 전)
        payload: dict[str, Any] = {
            "daily": {"team_name": "test"},
            "weekly": {"report_date": "2026-07-23"},
        }

        # 스냅샷 병합 시도 (부재)
        from pulse.publish import _merge_snapshot_if_not_publishing

        config_mock = type("Config", (), {"data_dir": data_dir})()
        _merge_snapshot_if_not_publishing(payload, config_mock)

        # 확인: weekly 키가 제거됨
        assert "weekly" not in payload
        assert "daily" in payload  # daily는 유지


def test_cached_status_reevaluated_on_merge() -> None:
    """스냅샷 재생 시 cached 플래그가 캐시 기반으로 재평가된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # 이전 발행 스냅샷 (cached=False 상태)
        prev_snapshot = {
            "report_date": "2026-07-21",
            "groups": {
                "org/repo::feature1": {
                    "name": "feature1",
                    "cached": False,
                    "cached_title": None,
                    "cached_analysis": None,
                },
                "org/repo::feature2": {
                    "name": "feature2",
                    "cached": False,
                    "cached_title": None,
                    "cached_analysis": None,
                },
            },
        }
        save_weekly_snapshot(data_dir, prev_snapshot)

        # 분석 캐시 (feature1만 존재)
        cache: dict[str, Any] = {
            "org/repo::feature1@weekly": {
                "title": "Feature 1 Title",
                "analysis": "Feature 1 Analysis",
            }
        }

        # 스냅샷 병합 + cached 재평가
        from pulse.publish import _merge_snapshot_if_not_publishing

        payload: dict[str, Any] = {"weekly": {"report_date": "2026-07-23"}}
        config_mock = type("Config", (), {"data_dir": data_dir})()
        _merge_snapshot_if_not_publishing(payload, config_mock, cache)

        # 확인: feature1은 cached=true (캐시 히트), feature2는 cached=false (캐시 미스)
        groups = payload["weekly"]["groups"]
        assert groups["org/repo::feature1"]["cached"] is True
        assert groups["org/repo::feature1"]["cached_title"] == "Feature 1 Title"
        assert groups["org/repo::feature2"]["cached"] is False
        assert groups["org/repo::feature2"]["cached_title"] is None


def test_snapshot_roundtrip_with_published_at() -> None:
    """스냅샷 저장/로드 라운드트립에서 published_at이 보존된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        now = datetime(2026, 7, 21, 10, 30, 0)
        weekly_section = {
            "report_date": "2026-07-21",
            "groups": {"org/repo::feature": {"name": "feature"}},
            "published_at": now.isoformat(),
        }

        # 저장
        save_weekly_snapshot(data_dir, weekly_section)

        # 로드
        loaded = load_weekly_snapshot(data_dir)

        # 확인
        assert loaded is not None
        assert loaded["published_at"] == now.isoformat()
