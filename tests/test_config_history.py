"""HistoryConfig 파싱과 repos.base_branch 파싱 테스트."""

import tempfile
from pathlib import Path

import pytest

from pulse.config.loader import (
    DEFAULT_MAX_HISTORY_COMMITS,
    DEFAULT_MIN_TAG_COVERAGE,
    ConfigError,
    HistoryConfig,
    load_config,
)

BASE_YAML = """\
team_name: Test Team
gitlab_url: http://gitlab.test
repos:
  - url: org/repo
"""


def write_config(body: str) -> Path:
    """임시 config.yaml을 만들고 경로를 반환한다 (호출자가 디렉터리 수명을 관리)."""
    tmpdir = tempfile.mkdtemp()
    path = Path(tmpdir) / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestHistoryConfigDefaults:
    def test_dataclass_defaults(self) -> None:
        config = HistoryConfig()
        assert config.enabled is True
        assert config.max_history_commits == DEFAULT_MAX_HISTORY_COMMITS
        assert config.min_tag_coverage == DEFAULT_MIN_TAG_COVERAGE

    def test_section_omitted_uses_defaults(self) -> None:
        config = load_config(write_config(BASE_YAML))
        assert config.history == HistoryConfig()

    def test_non_dict_section_falls_back_to_defaults(self) -> None:
        config = load_config(write_config(BASE_YAML + "history: true\n"))
        assert config.history == HistoryConfig()


class TestHistoryConfigParsing:
    def test_all_fields_parsed(self) -> None:
        config = load_config(
            write_config(
                BASE_YAML
                + """\
history:
  enabled: false
  max_history_commits: 250
  min_tag_coverage: 0.8
"""
            )
        )
        assert config.history.enabled is False
        assert config.history.max_history_commits == 250
        assert config.history.min_tag_coverage == 0.8

    def test_partial_section_keeps_other_defaults(self) -> None:
        config = load_config(write_config(BASE_YAML + "history:\n  max_history_commits: 500\n"))
        assert config.history.max_history_commits == 500
        assert config.history.enabled is True
        assert config.history.min_tag_coverage == DEFAULT_MIN_TAG_COVERAGE

    def test_zero_coverage_is_allowed(self) -> None:
        """0.0은 '태그 UI를 항상 표시'라는 유효한 설정이다."""
        config = load_config(write_config(BASE_YAML + "history:\n  min_tag_coverage: 0\n"))
        assert config.history.min_tag_coverage == 0.0

    def test_negative_max_commits_rejected(self) -> None:
        with pytest.raises(ConfigError, match="max_history_commits"):
            load_config(write_config(BASE_YAML + "history:\n  max_history_commits: -1\n"))

    def test_coverage_above_one_rejected(self) -> None:
        with pytest.raises(ConfigError, match="min_tag_coverage"):
            load_config(write_config(BASE_YAML + "history:\n  min_tag_coverage: 1.5\n"))

    def test_coverage_wrong_type_rejected(self) -> None:
        with pytest.raises(ConfigError, match="min_tag_coverage"):
            load_config(write_config(BASE_YAML + 'history:\n  min_tag_coverage: "half"\n'))

    def test_coverage_bool_rejected(self) -> None:
        """bool은 int의 서브클래스지만 비율로 받아들이면 안 된다."""
        with pytest.raises(ConfigError, match="min_tag_coverage"):
            load_config(write_config(BASE_YAML + "history:\n  min_tag_coverage: true\n"))


class TestRepoBaseBranch:
    def test_omitted_is_none(self) -> None:
        config = load_config(write_config(BASE_YAML))
        assert config.repos[0].base_branch is None

    def test_parsed_from_repo_entry(self) -> None:
        config = load_config(
            write_config(
                """\
team_name: Test Team
gitlab_url: http://gitlab.test
repos:
  - url: org/repo
    nickname: 별칭
    base_branch: develop
"""
            )
        )
        repo = config.repos[0]
        assert repo.base_branch == "develop"
        # nickname과 함께 지정해도 서로 덮어쓰지 않는다
        assert repo.nickname == "별칭"

    def test_blank_becomes_none(self) -> None:
        config = load_config(
            write_config(
                """\
team_name: Test Team
gitlab_url: http://gitlab.test
repos:
  - url: org/repo
    base_branch: "   "
"""
            )
        )
        assert config.repos[0].base_branch is None

    def test_wrong_type_rejected(self) -> None:
        with pytest.raises(ConfigError, match="base_branch"):
            load_config(
                write_config(
                    """\
team_name: Test Team
gitlab_url: http://gitlab.test
repos:
  - url: org/repo
    base_branch: 123
"""
                )
            )

    def test_string_repo_entry_still_works(self) -> None:
        """문자열 형식 항목은 base_branch 없이 그대로 동작한다 (하위호환)."""
        config = load_config(
            write_config(
                """\
team_name: Test Team
gitlab_url: http://gitlab.test
repos:
  - org/repo
"""
            )
        )
        assert config.repos[0].base_branch is None
        assert config.repos[0].nickname is None
