"""LifecycleConfig 파싱 및 Config 통합 테스트."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from pulse.config.loader import (
    ConfigError,
    LifecycleConfig,
    load_config,
)


class TestLifecycleConfigDefaults:
    """LifecycleConfig 기본값 테스트."""

    def test_lifecycle_config_defaults(self) -> None:
        """LifecycleConfig 기본값."""
        config = LifecycleConfig()
        assert config.enabled is True
        assert config.recent_mr_limit == 50

    def test_lifecycle_config_custom_values(self) -> None:
        """LifecycleConfig 커스텀 값."""
        config = LifecycleConfig(enabled=False, recent_mr_limit=100)
        assert config.enabled is False
        assert config.recent_mr_limit == 100


class TestConfigLoaderLifecycleSection:
    """config.yaml의 lifecycle 섹션 파싱 테스트."""

    def test_config_without_lifecycle_section(self) -> None:
        """lifecycle 섹션이 없는 config → 기본값."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
"""
            )
            config = load_config(config_path)
            assert config.lifecycle.enabled is True
            assert config.lifecycle.recent_mr_limit == 50

    def test_config_with_lifecycle_enabled_true(self) -> None:
        """lifecycle.enabled = true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  enabled: true
  recent_mr_limit: 75
"""
            )
            config = load_config(config_path)
            assert config.lifecycle.enabled is True
            assert config.lifecycle.recent_mr_limit == 75

    def test_config_with_lifecycle_enabled_false(self) -> None:
        """lifecycle.enabled = false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  enabled: false
"""
            )
            config = load_config(config_path)
            assert config.lifecycle.enabled is False
            assert config.lifecycle.recent_mr_limit == 50

    def test_config_with_lifecycle_recent_mr_limit_only(self) -> None:
        """lifecycle.recent_mr_limit만 지정."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  recent_mr_limit: 100
"""
            )
            config = load_config(config_path)
            assert config.lifecycle.enabled is True
            assert config.lifecycle.recent_mr_limit == 100

    def test_config_with_lifecycle_empty_section(self) -> None:
        """lifecycle 섹션이 빈 dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle: {}
"""
            )
            config = load_config(config_path)
            assert config.lifecycle.enabled is True
            assert config.lifecycle.recent_mr_limit == 50


class TestConfigLoaderLifecycleErrors:
    """LifecycleConfig 파싱 에러 테스트."""

    def test_config_lifecycle_enabled_not_bool(self) -> None:
        """lifecycle.enabled가 불린이 아님."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  enabled: "yes"
"""
            )
            with pytest.raises(ConfigError) as exc_info:
                load_config(config_path)
            assert "불린이어야 합니다" in str(exc_info.value)

    def test_config_lifecycle_recent_mr_limit_not_positive(self) -> None:
        """lifecycle.recent_mr_limit가 음수."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  recent_mr_limit: -5
"""
            )
            with pytest.raises(ConfigError) as exc_info:
                load_config(config_path)
            assert "양수이어야 합니다" in str(exc_info.value)

    def test_config_lifecycle_recent_mr_limit_zero(self) -> None:
        """lifecycle.recent_mr_limit가 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  recent_mr_limit: 0
"""
            )
            with pytest.raises(ConfigError) as exc_info:
                load_config(config_path)
            assert "양수이어야 합니다" in str(exc_info.value)

    def test_config_lifecycle_recent_mr_limit_string(self) -> None:
        """lifecycle.recent_mr_limit가 문자열."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  recent_mr_limit: "fifty"
"""
            )
            with pytest.raises(ConfigError) as exc_info:
                load_config(config_path)
            assert "양수이어야 합니다" in str(exc_info.value)


class TestConfigLoaderUnknownKeys:
    """알 수 없는 키 처리 테스트."""

    def test_lifecycle_is_known_key(self, caplog: Any) -> None:
        """'lifecycle' 키는 known key로 처리되어 경고 없음."""
        import logging

        caplog.set_level(logging.WARNING)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lifecycle:
  enabled: true
"""
            )
            load_config(config_path)
            # "lifecycle"에 대한 unknown key 경고 없음 확인
            assert "lifecycle" not in caplog.text or "알 수 없는 설정 키" not in caplog.text

    def test_unknown_key_warning(self, caplog: Any) -> None:
        """알 수 없는 키 경고 (lifecycle과 무관)."""
        import logging

        caplog.set_level(logging.WARNING)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
unknown_setting: value
"""
            )
            load_config(config_path)
            # unknown_setting에 대한 경고
            assert "unknown_setting" in caplog.text
            assert "알 수 없는 설정 키" in caplog.text


class TestConfigIntegration:
    """LifecycleConfig와 Config의 통합 테스트."""

    def test_config_full_with_lifecycle(self) -> None:
        """모든 필드를 포함한 config 로드."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
lookback_hours: 48
weekend_catchup: false
timezone: Asia/Tokyo
retention_days: 120
lifecycle:
  enabled: true
  recent_mr_limit: 75
"""
            )
            config = load_config(config_path)
            assert isinstance(config.lifecycle, LifecycleConfig)
            assert config.lifecycle.enabled is True
            assert config.lifecycle.recent_mr_limit == 75
            assert config.team_name == "test-team"
            assert config.lookback_hours == 48

    def test_config_lifecycle_field_type(self) -> None:
        """Config.lifecycle의 타입 검증."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """\
team_name: test-team
repos:
  - https://github.com/test-org/test-repo
"""
            )
            config = load_config(config_path)
            assert isinstance(config.lifecycle, LifecycleConfig)
            assert hasattr(config.lifecycle, "enabled")
            assert hasattr(config.lifecycle, "recent_mr_limit")

    def test_config_lifecycle_frozen(self) -> None:
        """LifecycleConfig는 frozen."""
        config = LifecycleConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore
