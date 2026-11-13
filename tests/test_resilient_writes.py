"""상태 저장 실패가 발행을 죽이지 않는지, 본질 산출물은 여전히 전파하는지 검증한다."""

import pathlib
from datetime import date, datetime, timezone

import pytest

import pulse.collector.snapshot as snapshot_module
import pulse.pipeline as pipeline_module
from pulse.models import RepoActivity, RepoRef

REPO = RepoRef(
    provider="gitlab",
    base_url="http://gitlab.test",
    namespace="org",
    name="repo",
    web_url="http://gitlab.test/org/repo",
)


def activity(status: str = "ok") -> RepoActivity:
    """저장 대상이 되는 최소 활동."""
    return RepoActivity(
        repo=REPO,
        status=status,  # type: ignore[arg-type]
        failure_reason=None,
        commits=(),
        active_branches=(),
        created_branches=(),
        deleted_branches=(),
        merge_requests=(),
        collected_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )


class TestRawActivitySaveIsIsolated:
    """레포 하나의 저장 실패가 나머지 레포와 발행을 막지 않는다."""

    def test_failure_does_not_propagate(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing(*args: object, **kwargs: object) -> None:
            raise OSError("Read-only file system")

        monkeypatch.setattr(pipeline_module, "save_raw_activity", failing)
        # 예외가 새어 나가면 _cmd_collect 가 exit 1 로 마감한다
        pipeline_module._save_raw_activities((activity(),), tmp_path)

    def test_other_repos_still_saved_after_one_failure(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempted: list[str] = []

        def flaky(saved_activity: RepoActivity, raw_dir: pathlib.Path) -> None:
            attempted.append(saved_activity.repo.full_path)
            if len(attempted) == 1:
                raise OSError("first one fails")

        monkeypatch.setattr(pipeline_module, "save_raw_activity", flaky)
        pipeline_module._save_raw_activities((activity(), activity()), tmp_path)

        assert len(attempted) == 2, "첫 레포 실패 후에도 나머지를 시도해야 한다"

    def test_late_binding_does_not_collapse_the_loop(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """람다가 루프 변수를 늦게 잡으면 모든 항목이 마지막 활동으로 저장된다."""
        seen: list[int] = []

        def record(saved_activity: RepoActivity, raw_dir: pathlib.Path) -> None:
            seen.append(id(saved_activity))

        first, second = activity(), activity()
        monkeypatch.setattr(pipeline_module, "save_raw_activity", record)
        pipeline_module._save_raw_activities((first, second), tmp_path)

        assert seen == [id(first), id(second)]

    def test_skipped_repos_are_not_saved(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempted: list[str] = []
        monkeypatch.setattr(
            pipeline_module,
            "save_raw_activity",
            lambda a, d: attempted.append(a.repo.full_path),
        )
        pipeline_module._save_raw_activities((activity(status="failed"),), tmp_path)

        assert attempted == []


class TestBranchSnapshotSaveIsIsolated:
    def test_snapshot_failure_does_not_propagate(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing(self: object, snapshot_dir: pathlib.Path) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(snapshot_module.BranchSnapshot, "save", failing)
        current, is_first, previous = snapshot_module.load_or_create(
            tmp_path, "org__repo", {"develop"}, date(2026, 7, 27).isoformat()
        )

        # 스냅샷 저장이 실패해도 이번 실행의 비교 결과는 그대로 쓸 수 있다
        assert current.branch_names == {"develop"}
        assert is_first is True
        assert previous is None


class TestEssentialWritesStayUnguarded:
    """대시보드 HTML 저장은 실패를 전파해야 한다 (회귀 방지).

    숨기면 낡은 대시보드가 남은 채 발행 성공으로 보고된다. 러너는
    PULSE_PUBLISH_OK 마커 유무로 성공을 판정하므로 더 위험하다.
    """

    def test_renderer_does_not_use_the_optional_state_helper(self) -> None:
        source = pathlib.Path("pulse/renderer/html.py").read_text(encoding="utf-8")
        assert "save_optional_state" not in source

    def test_inject_write_is_not_wrapped(self) -> None:
        source = pathlib.Path("pulse/publish.py").read_text(encoding="utf-8")
        # 슬롯 주입 결과 저장은 감싸지 않는다 — 요약 없는 대시보드를 완성본으로 보고하면 안 된다
        assert 'save_optional_state("주입' not in source
        assert 'path.write_text(html, encoding="utf-8")' in source
