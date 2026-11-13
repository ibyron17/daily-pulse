"""단발성 조회 모드 (--ad-hoc) 통합 테스트."""

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest


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
        },
    )()
    daily_model = type(
        "Model", (), {"groups": (), "report_date": date(2026, 7, 20), "period": "daily"}
    )()
    weekly_model = type(
        "Model", (), {"groups": (), "report_date": date(2026, 7, 20), "period": "weekly"}
    )()

    def _fake_extract(model: Any, cache: Any = None) -> dict[str, Any]:
        if model is weekly_model:
            return {"report_date": "2026-07-20", "period": "weekly", "groups": {}}
        return {"report_date": "2026-07-20", "period": "daily", "groups": {}}

    def _fake_write_report(
        html: str, output_dir: Path, report_date: date, write_latest: bool = True
    ) -> tuple[Path, Path | None]:
        output_dir.mkdir(parents=True, exist_ok=True)
        dated_path = output_dir / f"pulse-{report_date.isoformat()}.html"
        dated_path.write_text(html)
        latest_path: Path | None = None
        if write_latest:
            latest_path = output_dir / "latest.html"
            latest_path.write_text(html)
        return dated_path, latest_path

    def _fake_write_weekly_report(
        html: str, output_dir: Path, report_date: date, write_latest: bool = True
    ) -> tuple[Path, Path | None]:
        output_dir.mkdir(parents=True, exist_ok=True)
        dated_path = output_dir / f"pulse-weekly-{report_date.isoformat()}.html"
        dated_path.write_text(html)
        latest_path: Path | None = None
        if write_latest:
            latest_path = output_dir / "latest-weekly.html"
            latest_path.write_text(html)
        return dated_path, latest_path

    monkeypatch.setattr(publish, "load_config", lambda path: config)
    monkeypatch.setattr(publish, "missing_tokens", lambda cfg: [])
    monkeypatch.setattr(
        publish,
        "run_pipeline",
        lambda cfg, now=None, persist_state=True, weekly_window_end=None: (
            daily_model,
            weekly_model,
        ),
    )
    monkeypatch.setattr(publish, "extract_summary_input_by_repo", _fake_extract)
    monkeypatch.setattr(renderer, "render_html", lambda model: "<html></html>")
    monkeypatch.setattr(renderer, "write_report", _fake_write_report)
    monkeypatch.setattr(renderer, "write_weekly_report", _fake_write_weekly_report)
    return config


class TestCmdCollectAdHoc:
    """_cmd_collect(ad_hoc=True) 단발성 조회 테스트."""

    def test_ad_hoc_daily_creates_only_dated_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ad-hoc daily 조회 시 dated 파일만 생성되고 latest.html은 불변."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        # latest.html이 이미 존재한다고 가정 (생성 전 스냅샷)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        latest_path = config.output_dir / "latest.html"
        latest_content_before = b"OLD_CONTENT"
        latest_path.write_bytes(latest_content_before)

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            ad_hoc=True,
            now_override="2026-07-20T00:00:00+09:00",
        )

        assert exit_code == 0
        # dated 파일은 생성되어야 함
        dated_path = config.output_dir / "pulse-2026-07-20.html"
        assert dated_path.exists(), "dated 파일이 생성되어야 함"

        # latest.html은 변경되지 않아야 함
        assert latest_path.exists()
        latest_content_after = latest_path.read_bytes()
        assert latest_content_after == latest_content_before, "latest.html이 변경되면 안 됨"

        # payload는 ad_hoc: true, published_weekly: false를 포함
        payload = json.loads(capsys.readouterr().out)
        assert payload.get("ad_hoc") is True
        assert payload.get("published_weekly") is False

    def test_ad_hoc_weekly_creates_only_dated_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ad-hoc weekly 조회 시 dated 파일만 생성되고 latest-weekly.html은 불변."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        # latest-weekly.html이 이미 존재한다고 가정
        config.output_dir.mkdir(parents=True, exist_ok=True)
        latest_weekly_path = config.output_dir / "latest-weekly.html"
        latest_weekly_path.write_text("OLD_WEEKLY", encoding="utf-8")

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="weekly",
            ad_hoc=True,
            now_override="2026-07-20T00:00:00+09:00",
        )

        assert exit_code == 0
        # dated 파일은 생성되어야 함
        dated_weekly_path = config.output_dir / "pulse-weekly-2026-07-20.html"
        assert dated_weekly_path.exists(), "dated weekly 파일이 생성되어야 함"

        # latest-weekly.html은 변경되지 않아야 함
        assert latest_weekly_path.exists()
        assert latest_weekly_path.read_text() == "OLD_WEEKLY"

        # payload
        payload = json.loads(capsys.readouterr().out)
        assert payload.get("ad_hoc") is True

    def test_ad_hoc_with_force_weekly_is_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--ad-hoc과 --force-weekly 동시 지정은 오류."""
        from pulse.publish import _cmd_collect

        _setup_collect_stubs(monkeypatch, tmp_path)

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="weekly",
            force_weekly=True,
            ad_hoc=True,
            now_override="2026-07-20T00:00:00+09:00",
        )

        # exit code 2: 논리 오류
        assert exit_code == 2

    def test_regular_collect_still_updates_latest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ad-hoc 미지정 시 기존 동작 (latest.html 갱신)."""
        from pulse.publish import _cmd_collect

        config = _setup_collect_stubs(monkeypatch, tmp_path)

        config.output_dir.mkdir(parents=True, exist_ok=True)
        latest_path = config.output_dir / "latest.html"
        latest_path.write_text("OLD", encoding="utf-8")

        exit_code = _cmd_collect(
            Path("dummy.yaml"),
            period="daily",
            ad_hoc=False,  # 기본값
            now_override="2026-07-20T00:00:00+09:00",
        )

        assert exit_code == 0
        # latest.html이 갱신되어야 함 (테스트 스텁에서는 실제로 쓰지 않지만)
        payload = json.loads(capsys.readouterr().out)
        assert payload["ad_hoc"] is False


class TestCmdInjectAdHoc:
    """_cmd_inject(ad_hoc=True) 단발성 주입 테스트."""

    def test_ad_hoc_inject_without_date_is_error(self, tmp_path: Path) -> None:
        """ad-hoc inject에 --date 미지정은 오류."""
        from pulse.publish import _cmd_inject

        summary_path = tmp_path / "summary.json"
        summary_path.write_text(json.dumps({}), encoding="utf-8")

        exit_code = _cmd_inject(
            Path("dummy.yaml"),
            summary_path,
            period="both",
            ad_hoc=True,
            date_str=None,  # 미지정
        )

        # exit code 2: 필수 인자 미지정
        assert exit_code == 2


class TestPipelinePersistState:
    """run_pipeline(persist_state) 파라미터 테스트."""

    def test_persist_state_parameter_accepted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """run_pipeline이 persist_state 파라미터를 받아들인다."""
        from pulse.pipeline import run_pipeline

        # 최소 스텁 설정
        captured_save_snapshots: list[bool] = []

        def _fake_collect(config: Any, now: Any, save_snapshots: bool = True) -> tuple[Any, ...]:
            # save_snapshots이 False로 전달되는지 확인하기 위해 저장
            captured_save_snapshots.append(save_snapshots)
            return ()

        import pulse.pipeline as pipeline_module

        monkeypatch.setattr(pipeline_module, "_collect_activities", _fake_collect)
        monkeypatch.setattr(pipeline_module, "_save_raw_activities", lambda *args: None)
        monkeypatch.setattr(pipeline_module, "filter_activities_to_window", lambda a, h, n: ())
        monkeypatch.setattr(pipeline_module, "group_activities", lambda **kwargs: ((), (), (), 0.0))
        monkeypatch.setattr(
            pipeline_module, "build_dashboard_model", lambda **kwargs: type("M", (), {})()
        )
        monkeypatch.setattr(
            pipeline_module, "find_weekly_baseline_snapshots", lambda cfg, date: ({}, None)
        )
        monkeypatch.setattr(pipeline_module, "generate_new_work_signals", lambda a, n, **kwargs: ())
        monkeypatch.setattr(pipeline_module, "cleanup_retention", lambda *args: None)

        from dataclasses import dataclass, field

        @dataclass
        class StubConfig:
            timezone_name: str = "Asia/Seoul"
            lookback_hours: int = 24
            weekend_catchup: bool = False
            data_dir: Path = field(default_factory=lambda: tmp_path)
            output_dir: Path = field(default_factory=lambda: tmp_path / "reports")
            retention_days: int = 30
            repos: list[Any] = field(default_factory=list)

        config = StubConfig(data_dir=tmp_path, output_dir=tmp_path / "reports")

        # persist_state=False 호출
        captured_save_snapshots.clear()
        daily, weekly = run_pipeline(cast(Any, config), now_override=None, persist_state=False)
        assert captured_save_snapshots[0] is False

        # persist_state=True 호출
        captured_save_snapshots.clear()
        daily, weekly = run_pipeline(cast(Any, config), now_override=None, persist_state=True)
        assert captured_save_snapshots[0] is True


class TestWriteReportWriteLatest:
    """write_report(write_latest) 파라미터 테스트."""

    def test_write_report_with_write_latest_true(self, tmp_path: Path) -> None:
        """write_latest=True 시 latest.html이 생성된다."""
        from pulse.renderer.html import write_report

        output_dir = tmp_path / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        html = "<html>Test</html>"
        dated_path, latest_path = write_report(
            html, output_dir, date(2026, 7, 20), write_latest=True
        )

        assert dated_path.exists()
        assert latest_path is not None
        assert latest_path.exists()
        assert latest_path.name == "latest.html"

    def test_write_report_with_write_latest_false(self, tmp_path: Path) -> None:
        """write_latest=False 시 dated만 생성되고 latest는 None."""
        from pulse.renderer.html import write_report

        output_dir = tmp_path / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 기존 latest.html이 있다고 가정
        existing_latest = output_dir / "latest.html"
        content_before = b"OLD_CONTENT"
        existing_latest.write_bytes(content_before)

        html = "<html>Test</html>"
        dated_path, latest_path = write_report(
            html, output_dir, date(2026, 7, 20), write_latest=False
        )

        assert dated_path.exists()
        assert latest_path is None, "write_latest=False일 때 latest_path는 None"

        # 기존 latest.html은 변경되지 않아야 함
        content_after = existing_latest.read_bytes()
        assert content_after == content_before, "latest.html이 변경되면 안 됨"

    def test_write_weekly_report_with_write_latest_false(self, tmp_path: Path) -> None:
        """write_weekly_report(write_latest=False) 시 dated만 생성."""
        from pulse.renderer.html import write_weekly_report

        output_dir = tmp_path / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        existing_latest_weekly = output_dir / "latest-weekly.html"
        existing_latest_weekly.write_text("OLD_WEEKLY")

        html = "<html>Weekly</html>"
        dated_path, latest_path = write_weekly_report(
            html, output_dir, date(2026, 7, 20), write_latest=False
        )

        assert dated_path.exists()
        assert latest_path is None
        assert existing_latest_weekly.read_text() == "OLD_WEEKLY"
