"""수명주기 등록부 테스트."""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from pulse.lifecycle import (
    GRADUATION_DAYS,
    GroupLifecycleEntry,
    GroupLifecycleRegistry,
    StageTransition,
    build_lifecycle_view,
    load_registry,
    registry_path,
    save_registry,
    update_registry,
)
from pulse.models import CommitInfo, FeatureGroup, TaskSummary


@pytest.fixture
def sample_group() -> FeatureGroup:
    """테스트용 샘플 그룹."""
    return FeatureGroup(
        name="feature-auth",
        source_rule="branch",
        evidence="feature/auth branch",
        stage="developing",
        repo_full_path="org/repo",
        commits=(
            CommitInfo(
                sha="abc123",
                author_name="Alice",
                authored_at=datetime(2026, 7, 21, 10, 0, 0),
                message="Add auth module",
                branch="feature/auth",
                changed_files=("auth.py",),
                web_url="http://example.com/commits/abc123",
            ),
        ),
        merge_requests=(),
        branch_names=("feature/auth",),
        participants=("Alice",),
        task_summary=TaskSummary(
            commit_titles=("Add auth module",),
            open_mr_titles=(),
            active_branch_names=("feature/auth",),
        ),
        group_kind="feature",
        daily_commit_counts=(
            ("2026-07-21", 1),
            ("2026-07-22", 2),
            ("2026-07-23", 0),
            ("2026-07-24", 3),
        ),
    )


@pytest.fixture
def empty_registry() -> GroupLifecycleRegistry:
    """빈 등록부."""
    return GroupLifecycleRegistry(
        schema_version=1,
        updated_at=datetime(2026, 7, 27, 9, 0, 0),
        groups=(),
    )


class TestUpdateRegistry:
    """update_registry 함수 테스트."""

    def test_register_new_group(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """신규 그룹을 등록한다."""
        run_date = date(2026, 7, 21)
        result = update_registry(empty_registry, (sample_group,), run_date)

        key = "org/repo::feature-auth"
        groups_dict = dict(result.groups)
        assert key in groups_dict
        entry = groups_dict[key]
        assert entry.first_seen == run_date
        assert entry.last_seen == run_date
        assert len(entry.stage_history) == 1
        assert entry.stage_history[0].stage == "developing"
        assert entry.stage_history[0].entered_at == run_date
        assert entry.group_kind == "feature"

    def test_stage_transition_appended(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """단계가 변경되면 stage_history에 추가된다."""
        run_date1 = date(2026, 7, 21)
        registry1 = update_registry(empty_registry, (sample_group,), run_date1)

        # 같은 그룹, 다른 stage
        group_reviewing = FeatureGroup(
            name="feature-auth",
            source_rule="branch",
            evidence="feature/auth branch",
            stage="reviewing",  # 변경됨
            repo_full_path="org/repo",
            commits=sample_group.commits,
            merge_requests=sample_group.merge_requests,
            branch_names=sample_group.branch_names,
            participants=sample_group.participants,
            task_summary=sample_group.task_summary,
            group_kind="feature",
            daily_commit_counts=sample_group.daily_commit_counts,
        )
        run_date2 = date(2026, 7, 24)
        registry2 = update_registry(registry1, (group_reviewing,), run_date2)

        key = "org/repo::feature-auth"
        groups_dict = dict(registry2.groups)
        entry = groups_dict[key]
        assert len(entry.stage_history) == 2
        assert entry.stage_history[0].stage == "developing"
        assert entry.stage_history[1].stage == "reviewing"
        assert entry.stage_history[1].entered_at == run_date2
        assert entry.last_seen == run_date2

    def test_same_stage_not_appended(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """같은 단계라면 history에 append하지 않는다."""
        run_date1 = date(2026, 7, 21)
        registry1 = update_registry(empty_registry, (sample_group,), run_date1)

        # 같은 그룹, 같은 stage
        run_date2 = date(2026, 7, 24)
        registry2 = update_registry(registry1, (sample_group,), run_date2)

        key = "org/repo::feature-auth"
        groups_dict = dict(registry2.groups)
        entry = groups_dict[key]
        assert len(entry.stage_history) == 1  # 추가되지 않음
        assert entry.stage_history[0].stage == "developing"
        assert entry.last_seen == run_date2

    def test_date_commit_counts_overwrite_merge(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """date_commit_counts는 날짜 key overwrite로 병합된다."""
        run_date1 = date(2026, 7, 21)
        registry1 = update_registry(empty_registry, (sample_group,), run_date1)

        # 새로운 daily_commit_counts (일부 날짜가 겹침)
        group_updated = FeatureGroup(
            name="feature-auth",
            source_rule="branch",
            evidence="feature/auth branch",
            stage="developing",
            repo_full_path="org/repo",
            commits=sample_group.commits,
            merge_requests=sample_group.merge_requests,
            branch_names=sample_group.branch_names,
            participants=sample_group.participants,
            task_summary=sample_group.task_summary,
            group_kind="feature",
            daily_commit_counts=(
                ("2026-07-22", 5),  # 기존값 2를 5로 덮어쓰기
                ("2026-07-23", 1),  # 기존값 0을 1로 덮어쓰기
                ("2026-07-24", 3),  # 동일
                ("2026-07-25", 2),  # 신규
            ),
        )
        run_date2 = date(2026, 7, 25)
        registry2 = update_registry(registry1, (group_updated,), run_date2)

        key = "org/repo::feature-auth"
        groups_dict = dict(registry2.groups)
        entry = groups_dict[key]
        date_map = dict(entry.date_commit_counts)
        assert date_map.get("2026-07-21") == 1  # 기존 (변경 없음)
        assert date_map.get("2026-07-22") == 5  # 덮어쓰기
        assert date_map.get("2026-07-23") == 1  # 덮어쓰기
        assert date_map.get("2026-07-24") == 3  # 유지
        assert date_map.get("2026-07-25") == 2  # 신규

    def test_idempotent(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """같은 입력으로 두 번 호출하면 결과가 동일하다 (멱등성)."""
        run_date = date(2026, 7, 21)
        result1 = update_registry(empty_registry, (sample_group,), run_date)
        result2 = update_registry(result1, (sample_group,), run_date)

        key = "org/repo::feature-auth"
        groups_dict1 = dict(result1.groups)
        groups_dict2 = dict(result2.groups)
        entry1 = groups_dict1[key]
        entry2 = groups_dict2[key]

        assert entry1.first_seen == entry2.first_seen
        assert entry1.last_seen == entry2.last_seen
        assert entry1.stage_history == entry2.stage_history
        assert entry1.date_commit_counts == entry2.date_commit_counts

    def test_multiple_groups(self: Any, empty_registry: GroupLifecycleRegistry) -> None:
        """여러 그룹을 동시에 등록한다."""
        group1 = FeatureGroup(
            name="feature-auth",
            source_rule="branch",
            evidence="feature/auth branch",
            stage="developing",
            repo_full_path="org/repo1",
            commits=(),
            merge_requests=(),
            branch_names=("feature/auth",),
            participants=(),
            group_kind="feature",
            daily_commit_counts=(("2026-07-21", 1),),
        )
        group2 = FeatureGroup(
            name="feature-api",
            source_rule="branch",
            evidence="feature/api branch",
            stage="reviewing",
            repo_full_path="org/repo2",
            commits=(),
            merge_requests=(),
            branch_names=("feature/api",),
            participants=(),
            group_kind="feature",
            daily_commit_counts=(("2026-07-21", 2),),
        )
        run_date = date(2026, 7, 21)
        result = update_registry(empty_registry, (group1, group2), run_date)

        assert len(result.groups) == 2
        groups_dict = dict(result.groups)
        assert "org/repo1::feature-auth" in groups_dict
        assert "org/repo2::feature-api" in groups_dict

    def test_input_immutable(
        self: Any, empty_registry: GroupLifecycleRegistry, sample_group: FeatureGroup
    ) -> None:
        """입력 등록부는 불변이고, 새 등록부를 반환한다."""
        original_groups = empty_registry.groups
        run_date = date(2026, 7, 21)
        result = update_registry(empty_registry, (sample_group,), run_date)

        # 입력은 변경되지 않음
        assert empty_registry.groups == original_groups
        assert empty_registry.groups == ()
        # 새 등록부가 반환됨
        assert result is not empty_registry
        assert len(result.groups) > 0


class TestBuildLifecycleView:
    """build_lifecycle_view 함수 테스트."""

    def test_group_not_found_returns_none(
        self: Any, empty_registry: GroupLifecycleRegistry
    ) -> None:
        """등록부에 없는 그룹은 None을 반환한다."""
        result = build_lifecycle_view(empty_registry, "org/repo::unknown", date(2026, 7, 27))
        assert result is None

    def test_calculate_total_days(self: Any, empty_registry: GroupLifecycleRegistry) -> None:
        """total_days = (today - first_seen).days + 1 (첫 관측일을 1일차로)."""
        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 21),
            last_seen=date(2026, 7, 27),
            stage_history=(StageTransition(stage="developing", entered_at=date(2026, 7, 21)),),
            date_commit_counts=(),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 27))
        assert result is not None
        # (2026-07-27 - 2026-07-21).days = 6, + 1 = 7
        assert result.total_days == 7

    def test_same_day_is_one_day(self: Any, empty_registry: GroupLifecycleRegistry) -> None:
        """같은 날이면 total_days = 1."""
        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 21),
            last_seen=date(2026, 7, 21),
            stage_history=(StageTransition(stage="developing", entered_at=date(2026, 7, 21)),),
            date_commit_counts=(),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 21))
        assert result is not None
        assert result.total_days == 1

    def test_current_stage_and_days(self: Any, empty_registry: GroupLifecycleRegistry) -> None:
        """current_stage와 current_stage_days를 계산한다."""
        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 21),
            last_seen=date(2026, 7, 27),
            stage_history=(
                StageTransition(stage="developing", entered_at=date(2026, 7, 21)),
                StageTransition(stage="reviewing", entered_at=date(2026, 7, 24)),
            ),
            date_commit_counts=(),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 27))
        assert result is not None
        assert result.current_stage == "reviewing"
        # (2026-07-27 - 2026-07-24).days = 3, + 1 = 4
        assert result.current_stage_days == 4

    def test_active_days_and_cumulative_commits(
        self: Any, empty_registry: GroupLifecycleRegistry
    ) -> None:
        """active_days와 cumulative_commits를 계산한다."""
        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 21),
            last_seen=date(2026, 7, 27),
            stage_history=(StageTransition(stage="developing", entered_at=date(2026, 7, 21)),),
            date_commit_counts=(
                ("2026-07-21", 3),
                ("2026-07-22", 0),  # count=0은 active_days에 포함 안 함
                ("2026-07-23", 5),
                ("2026-07-24", 2),
            ),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 27))
        assert result is not None
        assert result.active_days == 3  # 3개 날짜 (0인 날은 제외)
        assert result.cumulative_commits == 10  # 3 + 0 + 5 + 2

    def test_graduation_policy_merged_within_threshold(
        self: Any, empty_registry: GroupLifecycleRegistry
    ) -> None:
        """merged 단계이지만 14일 이내면 정상 반환."""
        today = date(2026, 7, 27)
        merged_date = today - timedelta(days=10)  # 10일 전

        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 17),
            last_seen=today,
            stage_history=(
                StageTransition(stage="developing", entered_at=date(2026, 7, 17)),
                StageTransition(stage="reviewing", entered_at=date(2026, 7, 24)),
                StageTransition(stage="merged", entered_at=merged_date),
            ),
            date_commit_counts=(("2026-07-27", 0),),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", today)
        assert result is not None
        assert result.current_stage == "merged"

    def test_graduation_policy_merged_exceeds_threshold(
        self: Any, empty_registry: GroupLifecycleRegistry
    ) -> None:
        """merged 후 14일 경과하면 None 반환."""
        today = date(2026, 7, 27)
        merged_date = today - timedelta(days=GRADUATION_DAYS)  # 정확히 GRADUATION_DAYS 전

        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 13),
            last_seen=today,
            stage_history=(
                StageTransition(stage="developing", entered_at=date(2026, 7, 13)),
                StageTransition(stage="merged", entered_at=merged_date),
            ),
            date_commit_counts=(("2026-07-27", 0),),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", today)
        assert result is None

    def test_graduation_policy_merged_13_days_not_graduated(
        self: Any, empty_registry: GroupLifecycleRegistry
    ) -> None:
        """merged 후 GRADUATION_DAYS-1일은 졸업하지 않음 (경계 테스트)."""
        today = date(2026, 7, 27)
        merged_date = today - timedelta(days=GRADUATION_DAYS - 1)

        entry = GroupLifecycleEntry(
            first_seen=date(2026, 7, 14),
            last_seen=today,
            stage_history=(
                StageTransition(stage="developing", entered_at=date(2026, 7, 14)),
                StageTransition(stage="merged", entered_at=merged_date),
            ),
            date_commit_counts=(("2026-07-27", 0),),
            group_kind="feature",
        )
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(("org/repo::group1", entry),),
        )

        result = build_lifecycle_view(registry, "org/repo::group1", today)
        assert result is not None


class TestLoadRegistry:
    """load_registry 함수 테스트."""

    def test_file_not_found_returns_empty_registry(self: Any, caplog: Any) -> None:
        """파일이 없으면 빈 등록부를 반환한다."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            result = load_registry(path)

            assert result.schema_version == 1
            assert len(result.groups) == 0
            # 경고가 로깅되지 않음 (정상)

    def test_malformed_json_returns_empty_registry(self: Any, caplog: Any) -> None:
        """JSON 손상 시 빈 등록부 + 경고를 반환한다."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            path.write_text("{invalid json")

            with caplog.at_level(logging.WARNING):
                result = load_registry(path)

            assert result.schema_version == 1
            assert len(result.groups) == 0
            assert "load failed" in caplog.text

    def test_unsupported_schema_version(self: Any, caplog: Any) -> None:
        """지원하지 않는 schema version이면 빈 등록부 + 경고."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            data = {
                "schema_version": 99,
                "updated_at": datetime.now().isoformat(),
                "groups": {},
            }
            path.write_text(json.dumps(data))

            with caplog.at_level(logging.WARNING):
                result = load_registry(path)

            assert result.schema_version == 1
            assert len(result.groups) == 0
            assert "unsupported schema version" in caplog.text

    def test_load_valid_registry(self: Any) -> None:
        """유효한 등록부를 로드한다."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            data = {
                "schema_version": 1,
                "updated_at": "2026-07-27T09:00:00",
                "groups": {
                    "org/repo::group1": {
                        "first_seen": "2026-07-21",
                        "last_seen": "2026-07-27",
                        "stage_history": [
                            {"stage": "developing", "entered_at": "2026-07-21"},
                            {"stage": "reviewing", "entered_at": "2026-07-24"},
                        ],
                        "date_commit_counts": {
                            "2026-07-21": 3,
                            "2026-07-22": 0,
                            "2026-07-23": 5,
                        },
                        "group_kind": "feature",
                    }
                },
            }
            path.write_text(json.dumps(data))

            result = load_registry(path)
            assert result.schema_version == 1
            assert len(result.groups) == 1

            groups_dict = dict(result.groups)
            entry = groups_dict["org/repo::group1"]
            assert entry.first_seen == date(2026, 7, 21)
            assert entry.last_seen == date(2026, 7, 27)
            assert len(entry.stage_history) == 2
            assert entry.stage_history[0].stage == "developing"
            assert entry.stage_history[1].stage == "reviewing"
            assert len(entry.date_commit_counts) == 3


class TestSaveRegistry:
    """save_registry 함수 테스트."""

    def test_save_and_load_roundtrip(self: Any) -> None:
        """저장 후 로드하면 동일한 등록부를 복원한다."""
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime(2026, 7, 27, 9, 0, 0),
            groups=(
                (
                    "org/repo::group1",
                    GroupLifecycleEntry(
                        first_seen=date(2026, 7, 21),
                        last_seen=date(2026, 7, 27),
                        stage_history=(
                            StageTransition(stage="developing", entered_at=date(2026, 7, 21)),
                            StageTransition(stage="reviewing", entered_at=date(2026, 7, 24)),
                        ),
                        date_commit_counts=(
                            ("2026-07-21", 3),
                            ("2026-07-22", 0),
                            ("2026-07-23", 5),
                        ),
                        group_kind="feature",
                    ),
                ),
            ),
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            save_registry(registry, path)

            loaded = load_registry(path)
            assert loaded.schema_version == registry.schema_version
            assert len(loaded.groups) == 1

            loaded_dict = dict(loaded.groups)
            registry_dict = dict(registry.groups)
            entry = loaded_dict["org/repo::group1"]
            original_entry = registry_dict["org/repo::group1"]
            assert entry.first_seen == original_entry.first_seen
            assert entry.last_seen == original_entry.last_seen
            assert entry.stage_history == original_entry.stage_history
            assert entry.date_commit_counts == original_entry.date_commit_counts

    def test_creates_parent_directory(self: Any) -> None:
        """부모 디렉토리가 없으면 자동 생성한다."""
        registry = GroupLifecycleRegistry(
            schema_version=1,
            updated_at=datetime.now(),
            groups=(),
        )

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "deep" / "registry.json"
            save_registry(registry, path)
            assert path.exists()


class TestRegistryPath:
    """registry_path 함수 테스트."""

    def test_registry_path_construction(self: Any) -> None:
        """registry_path는 data_dir/lifecycle/registry.json을 반환한다."""
        data_dir = Path("/data")
        expected = data_dir / "lifecycle" / "registry.json"
        result = registry_path(data_dir)
        assert result == expected


class TestFirstSeenConsistency:
    """첫 관측일과 활동일수의 정합성 (총 경과일 >= 활동일수)."""

    def test_first_seen_backs_up_to_earliest_active_date(self) -> None:
        """7일 히스토그램이 등록일 이전 활동을 담으면 첫 관측일이 그만큼 앞당겨진다."""
        group = FeatureGroup(
            name="line",
            source_rule="branch",
            evidence="develop",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=("develop",),
            participants=(),
            task_summary=TaskSummary((), (), ()),
            group_kind="line",
            daily_commit_counts=(
                ("2026-07-14", 3),
                ("2026-07-15", 0),
                ("2026-07-20", 5),
            ),
        )
        registry = GroupLifecycleRegistry(schema_version=1, updated_at=datetime.now(), groups=())
        updated = update_registry(registry, (group,), date(2026, 7, 20))

        entry = dict(updated.groups)["org/repo::line"]
        assert entry.first_seen == date(2026, 7, 14)

    def test_total_days_never_less_than_active_days(self) -> None:
        """어떤 경우에도 '진행 N일차'가 '활동 M일'보다 작아지지 않는다."""
        group = FeatureGroup(
            name="line",
            source_rule="branch",
            evidence="develop",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=("develop",),
            participants=(),
            task_summary=TaskSummary((), (), ()),
            group_kind="line",
            daily_commit_counts=tuple((f"2026-07-{day:02d}", 2) for day in range(14, 21)),
        )
        registry = GroupLifecycleRegistry(schema_version=1, updated_at=datetime.now(), groups=())
        updated = update_registry(registry, (group,), date(2026, 7, 20))

        view = build_lifecycle_view(updated, "org/repo::line", date(2026, 7, 20))
        assert view is not None
        assert view.total_days >= view.active_days

    def test_first_seen_unchanged_when_no_earlier_activity(self) -> None:
        """등록일 이후 활동만 있으면 첫 관측일은 등록일 그대로다."""
        group = FeatureGroup(
            name="line",
            source_rule="branch",
            evidence="develop",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=("develop",),
            participants=(),
            task_summary=TaskSummary((), (), ()),
            group_kind="line",
            daily_commit_counts=(("2026-07-20", 1),),
        )
        registry = GroupLifecycleRegistry(schema_version=1, updated_at=datetime.now(), groups=())
        updated = update_registry(registry, (group,), date(2026, 7, 20))

        assert dict(updated.groups)["org/repo::line"].first_seen == date(2026, 7, 20)


class TestBuildLifecycleViewWithPastToday:
    """today 가 등록부의 기록보다 이르면(월요일 기준 보완 발행) 경과일은 1일차로 막는다."""

    @staticmethod
    def _registry(
        first_seen: date, transitions: tuple[StageTransition, ...]
    ) -> GroupLifecycleRegistry:
        entry = GroupLifecycleEntry(
            first_seen=first_seen,
            last_seen=transitions[-1].entered_at,
            stage_history=transitions,
            date_commit_counts=(),
            group_kind="feature",
        )
        return GroupLifecycleRegistry(
            schema_version=1, updated_at=datetime.now(), groups=(("org/repo::group1", entry),)
        )

    def test_current_stage_days_never_drops_below_one(self) -> None:
        """마지막 전이가 today 다음 날이면 current_stage_days 는 0이 아니라 1."""
        registry = self._registry(
            date(2026, 7, 13),
            (
                StageTransition(stage="developing", entered_at=date(2026, 7, 13)),
                StageTransition(stage="reviewing", entered_at=date(2026, 7, 21)),
            ),
        )

        view = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 20))

        assert view is not None
        assert view.current_stage == "reviewing"
        assert view.current_stage_days == 1

    def test_total_days_never_drops_below_one(self) -> None:
        """first_seen 이 today 보다 늦어도 total_days 는 1."""
        registry = self._registry(
            date(2026, 7, 22),
            (StageTransition(stage="developing", entered_at=date(2026, 7, 22)),),
        )

        view = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 20))

        assert view is not None
        assert view.total_days == 1
        assert view.current_stage_days == 1

    def test_merged_entry_after_today_is_not_graduated(self) -> None:
        """미래에 merged 로 전이한 그룹이 졸업 처리돼 뷰에서 사라지지 않는다."""
        registry = self._registry(
            date(2026, 7, 13),
            (StageTransition(stage="merged", entered_at=date(2026, 7, 21)),),
        )

        view = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 20))

        assert view is not None
        assert view.current_stage_days == 1

    def test_regular_counting_is_unchanged(self) -> None:
        """today 가 기록보다 늦은 평상시 계산은 그대로다 (첫 관측일 = 1일차)."""
        registry = self._registry(
            date(2026, 7, 13),
            (StageTransition(stage="developing", entered_at=date(2026, 7, 13)),),
        )

        view = build_lifecycle_view(registry, "org/repo::group1", date(2026, 7, 20))

        assert view is not None
        assert view.total_days == 8
        assert view.current_stage_days == 8
