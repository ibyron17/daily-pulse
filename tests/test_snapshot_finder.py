"""스냅샷 탐색 함수 테스트 (F3)."""

from pathlib import Path

from pulse.collector.snapshot import (
    BranchSnapshot,
    find_snapshot_near_days_ago,
    find_snapshot_on_or_after,
)


class TestFindSnapshotNearDaysAgo:
    """find_snapshot_near_days_ago 함수 테스트."""

    def test_find_exact_7_days_ago(self, tmp_path: Path) -> None:
        """정확히 7일 전 스냅샷이 있을 때 그것을 반환."""
        # Arrange
        snapshot_dir = tmp_path / "snapshots"
        current_date = "2026-07-20"
        target_date = "2026-07-13"  # 7일 전
        repo_slug = "test__repo"

        # 7일 전 스냅샷 생성
        date_dir = snapshot_dir / target_date
        date_dir.mkdir(parents=True)
        snapshot = BranchSnapshot(repo_slug, {"main", "develop"}, target_date)
        snapshot.save(snapshot_dir)

        # Act
        result = find_snapshot_near_days_ago(snapshot_dir, repo_slug, current_date, days_ago=7)

        # Assert
        assert result is not None
        snapshot_date_str, snapshot_path = result
        assert snapshot_date_str == target_date
        assert snapshot_path.exists()

    def test_find_closest_before_7_days_ago(self, tmp_path: Path) -> None:
        """7일 전이 없으면 그 이전 가장 최근 스냅샷을 반환."""
        # Arrange
        snapshot_dir = tmp_path / "snapshots"
        current_date = "2026-07-20"
        fallback_date = "2026-07-12"  # 8일 전
        repo_slug = "test__repo"

        # 8일 전 스냅샷만 생성 (7일 전은 없음)
        date_dir = snapshot_dir / fallback_date
        date_dir.mkdir(parents=True)
        snapshot = BranchSnapshot(repo_slug, {"main"}, fallback_date)
        snapshot.save(snapshot_dir)

        # Act
        result = find_snapshot_near_days_ago(snapshot_dir, repo_slug, current_date, days_ago=7)

        # Assert
        assert result is not None
        snapshot_date_str, _ = result
        assert snapshot_date_str == fallback_date

    def test_find_returns_none_when_no_snapshots(self, tmp_path: Path) -> None:
        """스냅샷이 없을 때 None을 반환."""
        # Arrange
        snapshot_dir = tmp_path / "snapshots"
        current_date = "2026-07-20"
        repo_slug = "test__repo"

        # Act
        result = find_snapshot_near_days_ago(snapshot_dir, repo_slug, current_date, days_ago=7)

        # Assert
        assert result is None

    def test_find_returns_none_when_snapshot_dir_missing(self, tmp_path: Path) -> None:
        """스냅샷 디렉토리가 없을 때 None을 반환."""
        # Arrange
        snapshot_dir = tmp_path / "nonexistent"
        current_date = "2026-07-20"
        repo_slug = "test__repo"

        # Act
        result = find_snapshot_near_days_ago(snapshot_dir, repo_slug, current_date, days_ago=7)

        # Assert
        assert result is None

    def test_find_returns_most_recent_before_target(self, tmp_path: Path) -> None:
        """7일 전 이전의 여러 스냅샷 중 가장 최신을 반환."""
        # Arrange
        snapshot_dir = tmp_path / "snapshots"
        current_date = "2026-07-20"
        repo_slug = "test__repo"

        # 여러 과거 스냅샷 생성
        for snapshot_date in ["2026-07-11", "2026-07-12", "2026-07-10"]:
            date_dir = snapshot_dir / snapshot_date
            date_dir.mkdir(parents=True)
            snapshot = BranchSnapshot(repo_slug, {"main"}, snapshot_date)
            snapshot.save(snapshot_dir)

        # Act
        result = find_snapshot_near_days_ago(snapshot_dir, repo_slug, current_date, days_ago=7)

        # Assert
        assert result is not None
        snapshot_date_str, _ = result
        # 7일 전(2026-07-13) 이전에서 가장 최신은 2026-07-12
        assert snapshot_date_str == "2026-07-12"


def _save_snapshots(snapshot_dir: Path, repo_slug: str, snapshot_dates: list[str]) -> None:
    """날짜별 스냅샷 파일을 만든다."""
    for snapshot_date in snapshot_dates:
        BranchSnapshot(repo_slug, {"main"}, snapshot_date).save(snapshot_dir)


class TestFindSnapshotOnOrAfter:
    """find_snapshot_on_or_after: target 날짜 이후(포함) 가장 이른 스냅샷."""

    def test_returns_same_day_snapshot_when_present(self, tmp_path: Path) -> None:
        """target 날짜 스냅샷이 있으면 그것을 반환 (포함 경계)."""
        snapshot_dir = tmp_path / "snapshots"
        _save_snapshots(snapshot_dir, "test__repo", ["2026-10-04", "2026-10-05", "2026-10-06"])

        result = find_snapshot_on_or_after(snapshot_dir, "test__repo", "2026-10-05")

        assert result is not None
        assert result[0] == "2026-10-05"
        assert result[1] == snapshot_dir / "2026-10-05" / "test__repo.json"

    def test_returns_earliest_later_snapshot_when_target_day_is_missing(
        self, tmp_path: Path
    ) -> None:
        """target 날짜 스냅샷이 없으면 그 이후 가장 이른 것을 반환한다."""
        snapshot_dir = tmp_path / "snapshots"
        _save_snapshots(snapshot_dir, "test__repo", ["2026-10-03", "2026-10-07", "2026-10-06"])

        result = find_snapshot_on_or_after(snapshot_dir, "test__repo", "2026-10-05")

        assert result is not None
        assert result[0] == "2026-10-06"

    def test_ignores_earlier_snapshots(self, tmp_path: Path) -> None:
        """이전 날짜 스냅샷만 있으면 None (이전 것은 「끝 스냅샷」이 될 수 없다)."""
        snapshot_dir = tmp_path / "snapshots"
        _save_snapshots(snapshot_dir, "test__repo", ["2026-10-03", "2026-10-04"])

        assert find_snapshot_on_or_after(snapshot_dir, "test__repo", "2026-10-05") is None

    def test_skips_dates_without_this_repo(self, tmp_path: Path) -> None:
        """다른 레포 스냅샷만 있는 날짜는 건너뛴다."""
        snapshot_dir = tmp_path / "snapshots"
        _save_snapshots(snapshot_dir, "other__repo", ["2026-10-05"])
        _save_snapshots(snapshot_dir, "test__repo", ["2026-10-06"])

        result = find_snapshot_on_or_after(snapshot_dir, "test__repo", "2026-10-05")

        assert result is not None
        assert result[0] == "2026-10-06"

    def test_ignores_non_date_directories(self, tmp_path: Path) -> None:
        """날짜 형식이 아닌 디렉토리는 무시한다."""
        snapshot_dir = tmp_path / "snapshots"
        (snapshot_dir / "backup").mkdir(parents=True)
        (snapshot_dir / "backup" / "test__repo.json").write_text("{}")
        _save_snapshots(snapshot_dir, "test__repo", ["2026-10-06"])

        result = find_snapshot_on_or_after(snapshot_dir, "test__repo", "2026-10-05")

        assert result is not None
        assert result[0] == "2026-10-06"

    def test_returns_none_when_snapshot_dir_missing(self, tmp_path: Path) -> None:
        assert find_snapshot_on_or_after(tmp_path / "none", "test__repo", "2026-10-05") is None
