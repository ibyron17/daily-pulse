"""보존 정책 테스트 (today 주입으로 결정적 실행)."""

from datetime import date
from pathlib import Path

import pytest

from pulse.retention import cleanup_retention, get_files_to_delete

TODAY = date(2026, 7, 16)
OLD_DATE = date(2026, 4, 1)  # 106일 전 — retention 90일 초과
RECENT_DATE = date(2026, 6, 16)  # 30일 전 — 보존 범위 내


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """raw/snapshots 하위 디렉토리를 갖춘 임시 data 디렉토리."""
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "snapshots").mkdir(parents=True)
    return data_dir


def _make_dated_file(base_dir: Path, day: date, filename: str) -> Path:
    """날짜 디렉토리 아래에 더미 파일을 만든다."""
    dated_dir = base_dir / day.isoformat()
    dated_dir.mkdir(exist_ok=True)
    file_path = dated_dir / filename
    file_path.write_text("{}", encoding="utf-8")
    return file_path


def test_get_files_to_delete_raw_directory(temp_data_dir: Path) -> None:
    """raw에서 retention 초과 파일만 삭제 대상이 된다."""
    # Arrange
    old_file = _make_dated_file(temp_data_dir / "raw", OLD_DATE, "repo.json")
    recent_file = _make_dated_file(temp_data_dir / "raw", RECENT_DATE, "repo.json")

    # Act
    to_delete = get_files_to_delete(temp_data_dir, retention_days=90, today=TODAY)

    # Assert
    assert old_file in to_delete
    assert recent_file not in to_delete


def test_get_files_to_delete_snapshots_directory(temp_data_dir: Path) -> None:
    """snapshots에서도 retention 초과 파일을 감지한다."""
    # Arrange
    old_snapshot = _make_dated_file(temp_data_dir / "snapshots", OLD_DATE, "snap.json")

    # Act
    to_delete = get_files_to_delete(temp_data_dir, retention_days=90, today=TODAY)

    # Assert
    assert old_snapshot in to_delete


def test_get_files_to_delete_ignores_non_date_directories(temp_data_dir: Path) -> None:
    """날짜 형식이 아닌 디렉토리는 절대 삭제 대상이 아니다."""
    # Arrange
    keep_dir = temp_data_dir / "raw" / "important-backup"
    keep_dir.mkdir()
    keep_file = keep_dir / "data.json"
    keep_file.write_text("{}", encoding="utf-8")

    # Act
    to_delete = get_files_to_delete(temp_data_dir, retention_days=90, today=TODAY)

    # Assert
    assert keep_file not in to_delete


def test_get_files_to_delete_boundary_exact_retention(temp_data_dir: Path) -> None:
    """정확히 retention_days 경과한 날짜는 삭제 대상 (cutoff 포함)."""
    # Arrange
    boundary_date = date(2026, 4, 17)  # TODAY - 90일
    boundary_file = _make_dated_file(temp_data_dir / "raw", boundary_date, "repo.json")

    # Act
    to_delete = get_files_to_delete(temp_data_dir, retention_days=90, today=TODAY)

    # Assert
    assert boundary_file in to_delete


def test_cleanup_retention_deletes_files(temp_data_dir: Path) -> None:
    """cleanup_retention이 파일과 빈 날짜 디렉토리를 실제로 삭제한다."""
    # Arrange
    old_file = _make_dated_file(temp_data_dir / "raw", OLD_DATE, "repo.json")
    old_dir = old_file.parent
    recent_file = _make_dated_file(temp_data_dir / "raw", RECENT_DATE, "repo.json")

    # Act
    cleanup_retention(temp_data_dir, retention_days=90, today=TODAY)

    # Assert
    assert not old_file.exists()
    assert not old_dir.exists()
    assert recent_file.exists()


def test_get_files_to_delete_includes_old_reports(temp_data_dir: Path, tmp_path: Path) -> None:
    """reports의 오래된 pulse-*.html은 삭제 대상, latest.html은 절대 제외."""
    # Arrange
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    old_report = reports_dir / f"pulse-{OLD_DATE.isoformat()}.html"
    old_report.write_text("<html></html>", encoding="utf-8")
    recent_report = reports_dir / f"pulse-{RECENT_DATE.isoformat()}.html"
    recent_report.write_text("<html></html>", encoding="utf-8")
    latest = reports_dir / "latest.html"
    latest.write_text("<html></html>", encoding="utf-8")

    # Act
    to_delete = get_files_to_delete(
        temp_data_dir, retention_days=90, today=TODAY, reports_dir=reports_dir
    )

    # Assert
    assert old_report in to_delete
    assert recent_report not in to_delete
    assert latest not in to_delete


def test_get_files_to_delete_ignores_non_report_html(temp_data_dir: Path, tmp_path: Path) -> None:
    """pulse-날짜 형식이 아닌 파일(잘못된 날짜 포함)은 reports에서 삭제 대상이 아니다."""
    # Arrange
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    odd_file = reports_dir / "pulse-not-a-date.html"
    odd_file.write_text("<html></html>", encoding="utf-8")
    other_file = reports_dir / "notes.html"
    other_file.write_text("<html></html>", encoding="utf-8")

    # Act
    to_delete = get_files_to_delete(
        temp_data_dir, retention_days=90, today=TODAY, reports_dir=reports_dir
    )

    # Assert
    assert odd_file not in to_delete
    assert other_file not in to_delete
