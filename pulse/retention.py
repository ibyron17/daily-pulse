"""보존 정책: 오래된 raw/snapshot 파일 삭제."""

import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DATE_MANAGED_SUBDIRS = ("raw", "snapshots")
_REPORT_FILE_PREFIX = "pulse-"
_REPORT_FILE_SUFFIX = ".html"


def _parse_date_dir(item: Path) -> date | None:
    """날짜 형식(YYYY-MM-DD) 디렉토리면 날짜를, 아니면 None을 반환한다."""
    if not item.is_dir():
        return None
    try:
        return date.fromisoformat(item.name)
    except ValueError:
        logger.debug("날짜 형식이 아닌 디렉토리 무시: %s", item.name)
        return None


def _expired_files_in(subdir: Path, cutoff_date: date) -> list[Path]:
    """cutoff 이전 날짜 디렉토리 아래의 모든 파일을 수집한다."""
    expired: list[Path] = []
    for item in subdir.iterdir():
        item_date = _parse_date_dir(item)
        if item_date is None or item_date > cutoff_date:
            continue
        expired.extend(path for path in item.rglob("*") if path.is_file())
    return expired


def _parse_report_date(file_path: Path) -> date | None:
    """pulse-YYYY-MM-DD.html 형식 리포트 파일이면 날짜를 반환한다."""
    name = file_path.name
    if not (name.startswith(_REPORT_FILE_PREFIX) and name.endswith(_REPORT_FILE_SUFFIX)):
        return None
    date_part = name[len(_REPORT_FILE_PREFIX) : -len(_REPORT_FILE_SUFFIX)]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return None


def _expired_report_files(reports_dir: Path, cutoff_date: date) -> list[Path]:
    """cutoff 이전 날짜의 리포트 파일을 수집한다. latest.html은 절대 대상이 아니다."""
    expired: list[Path] = []
    for item in reports_dir.iterdir():
        if not item.is_file():
            continue
        item_date = _parse_report_date(item)
        if item_date is not None and item_date <= cutoff_date:
            expired.append(item)
    return expired


def get_files_to_delete(
    data_dir: Path,
    retention_days: int,
    today: date,
    reports_dir: Path | None = None,
) -> list[Path]:
    """삭제 대상 파일 목록을 반환 (순수 판정 — today 주입으로 시각 의존 제거).

    대상: retention_days를 초과한 data/raw·data/snapshots의 날짜 디렉토리 안 파일과,
    reports_dir의 pulse-YYYY-MM-DD.html 파일. latest.html은 날짜 형식이 아니므로 제외.
    """
    cutoff_date = today - timedelta(days=retention_days)
    to_delete: list[Path] = []
    for subdir_name in _DATE_MANAGED_SUBDIRS:
        subdir = data_dir / subdir_name
        if subdir.exists():
            to_delete.extend(_expired_files_in(subdir, cutoff_date))
    if reports_dir is not None and reports_dir.exists():
        to_delete.extend(_expired_report_files(reports_dir, cutoff_date))
    return to_delete


def _remove_empty_date_dirs(data_dir: Path) -> None:
    """삭제 후 비어 있는 날짜 디렉토리를 정리한다."""
    for subdir_name in _DATE_MANAGED_SUBDIRS:
        subdir = data_dir / subdir_name
        if not subdir.exists():
            continue
        for item in subdir.iterdir():
            if item.is_dir() and not any(item.iterdir()):
                try:
                    item.rmdir()
                    logger.info("빈 디렉토리 삭제: %s", item)
                except OSError as error:
                    logger.warning("디렉토리 삭제 실패 %s: %s", item, error)


def cleanup_retention(
    data_dir: Path,
    retention_days: int,
    today: date,
    reports_dir: Path | None = None,
) -> None:
    """보존 정책에 따라 파일을 삭제한다 (판정은 순수, 삭제 I/O는 여기서만)."""
    for file_path in get_files_to_delete(data_dir, retention_days, today, reports_dir):
        try:
            file_path.unlink()
            logger.info("삭제: %s", file_path)
        except OSError as error:
            logger.warning("삭제 실패 %s: %s", file_path, error)
    _remove_empty_date_dirs(data_dir)
