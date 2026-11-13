"""Config 라운드 5 테스트: release_line_patterns, issue_tracking."""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from pulse.config.loader import (
    DEFAULT_RELEASE_LINE_PATTERNS,
    GroupingHints,
    load_config,
)


class TestGroupingHintsReleasePatterns:
    """release_line_patterns 테스트."""

    def test_grouping_hints_default_release_patterns(self) -> None:
        """기본 패턴."""
        hints = GroupingHints()
        assert hints.release_line_patterns == DEFAULT_RELEASE_LINE_PATTERNS
        assert "main" in hints.release_line_patterns
        assert "develop" in hints.release_line_patterns

    def test_grouping_hints_release_patterns_override(self) -> None:
        """오버라이드."""
        custom_patterns = ("custom-main", "custom-release")
        hints = GroupingHints(release_line_patterns=custom_patterns)
        assert hints.release_line_patterns == custom_patterns


class TestIssueTracking:
    """issue_tracking 섹션 테스트."""

    def test_config_issue_tracking_optional(self) -> None:
        """선택 섹션."""
        with TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.yaml"
            config_data = {
                "team_name": "Test Team",
                "repos": [{"url": "https://github.com/test/repo"}],
            }
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)
            config = load_config(config_file)
            assert config.issue_tracking.url_template is None

    def test_config_issue_tracking_url_template_loaded(self) -> None:
        """url_template 로드."""
        with TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.yaml"
            config_data = {
                "team_name": "Test Team",
                "repos": [{"url": "https://github.com/test/repo"}],
                "issue_tracking": {
                    "url_template": "https://jira.example.com/browse/{key}",
                },
            }
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)
            config = load_config(config_file)
            assert config.issue_tracking.url_template == "https://jira.example.com/browse/{key}"
