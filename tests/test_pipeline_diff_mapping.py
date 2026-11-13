"""파이프라인의 데이터 기준일 사상 로직 테스트."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from pulse.pipeline import _map_raw_date_to_data_basis

UTC = ZoneInfo("UTC")


class TestMapRawDateToDataBasis:
    """_map_raw_date_to_data_basis 함수 테스트."""

    def test_midnight_collection_subtracts_one_day(self) -> None:
        """자정(00:00:00) 수집 → 1일 차감."""
        raw_date = date(2026, 7, 22)
        previous_now = datetime(2026, 7, 22, 0, 0, 0, tzinfo=UTC)

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2026, 7, 21)

    def test_non_midnight_collection_unchanged(self) -> None:
        """비자정(14:30) 수집 → 그대로."""
        raw_date = date(2026, 7, 22)
        previous_now = datetime(2026, 7, 22, 14, 30, 0, tzinfo=UTC)

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2026, 7, 22)

    def test_midnight_with_microseconds_still_subtracts(self) -> None:
        """자정 + 마이크로초(00:00:00.000001) → 1일 차감 (마이크로초 무시)."""
        raw_date = date(2026, 7, 22)
        previous_now = datetime(2026, 7, 22, 0, 0, 0, 1, tzinfo=UTC)

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2026, 7, 21)

    def test_00_00_01_not_midnight(self) -> None:
        """00:00:01 (1초) → 그대로 (아침으로 간주)."""
        raw_date = date(2026, 7, 22)
        previous_now = datetime(2026, 7, 22, 0, 0, 1, tzinfo=UTC)

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2026, 7, 22)

    def test_monday_72h_weekend_catchup(self) -> None:
        """월요일 72h 케이스: 월요일 자정 수집 → 일요일로 사상."""
        raw_date = date(2026, 7, 20)  # 월요일
        previous_now = datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)  # 월요일 자정

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2026, 7, 19)  # 일요일
        # 확인: 7/20은 월요일, 7/19는 일요일
        assert date(2026, 7, 19).weekday() == 6  # 일요일
        assert date(2026, 7, 20).weekday() == 0  # 월요일

    def test_friday_to_monday_72h(self) -> None:
        """금요일 수집 이후 월요일 72h 조회 시나리오."""
        # 금요일에 비자정 수집
        friday_date = date(2026, 7, 17)
        friday_now = datetime(2026, 7, 17, 9, 30, 0, tzinfo=UTC)

        result_friday = _map_raw_date_to_data_basis(friday_date, friday_now)
        assert result_friday == date(2026, 7, 17)  # 금요일 기준 (비자정이므로 그대로)

        # 월요일 자정 수집 (72h 이후)
        monday_date = date(2026, 7, 20)  # 월요일
        monday_now = datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)

        result_monday = _map_raw_date_to_data_basis(monday_date, monday_now)
        assert result_monday == date(2026, 7, 19)  # 일요일 기준

    def test_year_boundary_midnight(self) -> None:
        """연도 경계: 2026-01-01 00:00 → 2025-12-31."""
        raw_date = date(2026, 1, 1)
        previous_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        result = _map_raw_date_to_data_basis(raw_date, previous_now)

        assert result == date(2025, 12, 31)

    def test_various_timezones_hour_only_checked(self) -> None:
        """타임존 무시, 시간값만 비교."""
        from zoneinfo import ZoneInfo

        raw_date = date(2026, 7, 22)
        tz_kst = ZoneInfo("Asia/Seoul")

        # 서울 시간 00:00 (UTC-9이면 UTC+9, 즉 전날 15:00)
        seoul_midnight = datetime(2026, 7, 22, 0, 0, 0, tzinfo=tz_kst)

        result = _map_raw_date_to_data_basis(raw_date, seoul_midnight)

        # hour=0이므로 1일 차감
        assert result == date(2026, 7, 21)
