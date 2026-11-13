"""주간 스냅샷 저장/로드 테스트."""

import json
import tempfile
from pathlib import Path

from pulse.collector.storage import load_weekly_snapshot, save_weekly_snapshot


def test_save_and_load_weekly_snapshot() -> None:
    """스냅샷을 저장하고 로드한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        weekly_section = {
            "report_date": "2026-07-28",
            "window_start": "2026-07-21T00:00:00+09:00",
            "window_end": "2026-07-28T00:00:00+09:00",
            "repos": {
                "org/repo1": {
                    "group_count": 2,
                    "commit_count": 10,
                }
            },
            "groups": {
                "org/repo1::feature": {
                    "name": "feature",
                    "stage": "reviewing",
                    "commit_titles": ["feat: X", "fix: Y"],
                }
            },
            "metrics": {"total_groups": 1},
        }

        # 저장
        save_weekly_snapshot(data_dir, weekly_section)

        # 로드
        loaded = load_weekly_snapshot(data_dir)

        assert loaded is not None
        assert loaded["report_date"] == "2026-07-28"
        assert loaded["repos"]["org/repo1"]["group_count"] == 2
        assert loaded["groups"]["org/repo1::feature"]["name"] == "feature"


def test_load_weekly_snapshot_not_exists() -> None:
    """스냅샷 파일이 없으면 None을 반환한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        loaded = load_weekly_snapshot(data_dir)
        assert loaded is None


def test_load_weekly_snapshot_invalid_json() -> None:
    """손상된 JSON 파일을 로드하면 None을 반환한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / "weekly_publish"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "latest.json"
        snapshot_path.write_text("invalid json {", encoding="utf-8")

        loaded = load_weekly_snapshot(data_dir)
        assert loaded is None


def test_snapshot_file_location() -> None:
    """스냅샷이 data/weekly_publish/latest.json에 저장된다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        weekly_section = {"report_date": "2026-07-28"}

        save_weekly_snapshot(data_dir, weekly_section)

        snapshot_path = data_dir / "weekly_publish" / "latest.json"
        assert snapshot_path.exists()
        with open(snapshot_path) as f:
            data = json.load(f)
        assert data["report_date"] == "2026-07-28"


def test_save_weekly_snapshot_overwrites() -> None:
    """스냅샷을 저장할 때마다 기존 파일을 덮어쓴다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # 첫 번째 저장
        snapshot1 = {"report_date": "2026-07-21"}
        save_weekly_snapshot(data_dir, snapshot1)

        # 두 번째 저장 (덮어쓰기)
        snapshot2 = {"report_date": "2026-07-28"}
        save_weekly_snapshot(data_dir, snapshot2)

        # 로드
        loaded = load_weekly_snapshot(data_dir)
        assert loaded is not None
        assert loaded["report_date"] == "2026-07-28"


def test_snapshot_preserves_complex_structure() -> None:
    """복잡한 구조의 스냅샷을 보존한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        weekly_section = {
            "report_date": "2026-07-28",
            "groups": {
                "org/repo1::feature1": {
                    "name": "feature1",
                    "stage": "reviewing",
                    "commit_titles": ["feat: X"],
                    "cached": False,
                    "cached_title": None,
                    "cached_analysis": None,
                },
                "org/repo1::feature2": {
                    "name": "feature2",
                    "stage": "merged",
                    "commit_titles": ["fix: Y"],
                    "cached": True,
                    "cached_title": "Feature 2 Title",
                    "cached_analysis": "Feature 2 Analysis",
                },
            },
        }

        save_weekly_snapshot(data_dir, weekly_section)
        loaded = load_weekly_snapshot(data_dir)

        assert loaded is not None
        assert len(loaded["groups"]) == 2
        assert loaded["groups"]["org/repo1::feature2"]["cached"] is True
        assert loaded["groups"]["org/repo1::feature2"]["cached_title"] == "Feature 2 Title"
