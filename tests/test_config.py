"""config 로딩, 검증, 파싱 테스트."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from pulse.config import ConfigError, load_config


def write_yaml(tmp_path: Path, data: dict[str, Any]) -> Path:
    """테스트용 YAML 파일을 생성하고 경로를 반환한다."""
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.safe_dump(data, f)
    return config_file


class TestConfigLoading:
    """config 로딩 테스트."""

    def test_load_config_parses_full_gitlab_url(self, tmp_path: Path) -> None:
        """전체 GitLab URL을 파싱한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "샘플 팀",
                "repos": ["https://gitlab.example.com/sample-group/sample-repo"],
            },
        )
        config = load_config(config_file)
        assert config.team_name == "샘플 팀"
        assert len(config.repos) == 1
        assert config.repos[0].provider == "gitlab"
        assert config.repos[0].namespace == "sample-group"
        assert config.repos[0].name == "sample-repo"
        assert config.repos[0].base_url == "https://gitlab.example.com"

    def test_load_config_detects_github_provider_from_host(self, tmp_path: Path) -> None:
        """GitHub 호스트에서 provider를 감지한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://github.com/org/repo"],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].provider == "github"

    def test_load_config_strips_git_suffix_from_repo_url(self, tmp_path: Path) -> None:
        """.git 접미사를 제거한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/sample-repo.git"],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].name == "sample-repo"

    def test_load_config_resolves_short_repo_path_with_gitlab_url(self, tmp_path: Path) -> None:
        """gitlab_url과 함께 축약형 repo 경로를 해석한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "gitlab_url": "https://gitlab.example.com",
                "repos": ["sample-group/sample-repo"],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].base_url == "https://gitlab.example.com"
        assert config.repos[0].namespace == "sample-group"

    def test_load_config_rejects_repo_path_without_gitlab_url(self, tmp_path: Path) -> None:
        """gitlab_url 없이 축약형 경로는 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["sample-group/sample-repo"],
            },
        )
        with pytest.raises(ConfigError, match="gitlab_url"):
            load_config(config_file)

    def test_load_config_reports_correct_index_for_second_repo(self, tmp_path: Path) -> None:
        """두 번째 repo 항목의 에러는 repos[1]로 표시된다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    "https://gitlab.example.com/sample-group/repo1",
                    "sample-group/repo2",  # 축약형, gitlab_url 없으므로 실패
                ],
            },
        )
        with pytest.raises(ConfigError, match=r"repos\[1\].*gitlab_url"):
            load_config(config_file)

    def test_load_config_rejects_missing_team_name(self, tmp_path: Path) -> None:
        """team_name 없으면 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "repos": ["https://gitlab.example.com/sample-group/repo"],
            },
        )
        with pytest.raises(ConfigError, match="team_name"):
            load_config(config_file)

    def test_load_config_rejects_empty_repos(self, tmp_path: Path) -> None:
        """빈 repos 목록은 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [],
            },
        )
        with pytest.raises(ConfigError):
            load_config(config_file)

    def test_load_config_rejects_invalid_timezone(self, tmp_path: Path) -> None:
        """알 수 없는 timezone은 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/repo"],
                "timezone": "Mars/Olympus",
            },
        )
        with pytest.raises(ConfigError, match="timezone"):
            load_config(config_file)

    def test_load_config_rejects_non_positive_lookback(self, tmp_path: Path) -> None:
        """양수가 아닌 lookback_hours는 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/repo"],
                "lookback_hours": 0,
            },
        )
        with pytest.raises(ConfigError):
            load_config(config_file)

    def test_load_config_applies_defaults(self, tmp_path: Path) -> None:
        """필수 필드만 있을 때 기본값이 적용된다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/repo"],
            },
        )
        config = load_config(config_file)
        assert config.lookback_hours == 24
        assert config.weekend_catchup is True
        assert config.timezone_name == "Asia/Seoul"
        assert config.retention_days == 90
        assert config.stagnation.review_waiting_days == 3
        assert config.stagnation.no_push_days == 7
        assert config.exclude_bot_authors == ()
        assert config.grouping_hints.branch_prefixes == ()

    def test_load_config_reports_missing_file(self) -> None:
        """존재하지 않는 파일은 에러를 보고한다."""
        with pytest.raises(ConfigError, match="설정 파일이 없습니다"):
            load_config(Path("nonexistent.yaml"))

    def test_load_config_warns_on_unknown_keys(self, tmp_path: Path, caplog: Any) -> None:
        """알 수 없는 키에 대해 경고를 로깅한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/repo"],
                "unknown_key": 1,
            },
        )
        config = load_config(config_file)
        assert config.team_name == "test"
        # caplog.records에서 메시지를 직접 검증
        messages = [record.getMessage() for record in caplog.records]
        assert any("unknown_key" in msg for msg in messages)

    def test_load_repos_with_nicknames(self, tmp_path: Path) -> None:
        """dict 형식 repos에서 nickname을 파싱한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-group/repo",
                        "nickname": "프론트엔드",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert len(config.repos) == 1
        assert config.repos[0].nickname == "프론트엔드"
        assert config.repos[0].display_name == "프론트엔드"

    def test_load_repos_backward_compat(self, tmp_path: Path) -> None:
        """문자열 형식 repos는 기존 호환성을 유지한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": ["https://gitlab.example.com/sample-group/repo"],
            },
        )
        config = load_config(config_file)
        assert len(config.repos) == 1
        assert config.repos[0].nickname is None
        assert config.repos[0].display_name == "sample-group/repo"

    def test_load_repos_subtree_path_parsed(self, tmp_path: Path) -> None:
        """subtree_path가 지정되면 그대로 파싱된다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "sample-model",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path == "sample-model"

    def test_load_repos_subtree_path_omitted_is_none(self, tmp_path: Path) -> None:
        """필드를 생략하면 None (하위 호환 핵심)."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [{"url": "https://gitlab.example.com/sample-group/repo"}],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path is None

    def test_load_repos_subtree_path_normalizes_slashes(self, tmp_path: Path) -> None:
        """앞뒤 슬래시를 제거해 정규형으로 저장한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "/sample-model/",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path == "sample-model"

    def test_load_repos_subtree_path_blank_becomes_none(self, tmp_path: Path) -> None:
        """빈 문자열/공백만 있으면 거부가 아니라 None으로 수렴한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "   ",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path is None

    def test_load_repos_subtree_path_slash_only_becomes_none(self, tmp_path: Path) -> None:
        """슬래시로만 이뤄진 값은 정규화 후 빈 문자열이 되므로 None으로 수렴한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "/",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path is None

    def test_load_repos_subtree_path_slash_only_non_gitlab_stays_none(self, tmp_path: Path) -> None:
        """GitHub 레포도 슬래시로만 된 값은 provider 검증 없이 None으로 수렴한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://github.com/org/repo",
                        "subtree_path": "/",
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path is None

    def test_load_repos_subtree_path_non_string_rejected(self, tmp_path: Path) -> None:
        """문자열이 아니면 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": 123,
                    }
                ],
            },
        )
        with pytest.raises(ConfigError, match="subtree_path"):
            load_config(config_file)

    def test_load_repos_subtree_path_rejects_dotdot_segment(self, tmp_path: Path) -> None:
        """'..' 세그먼트를 포함하면 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "../secrets",
                    }
                ],
            },
        )
        with pytest.raises(ConfigError, match=r"\.\."):
            load_config(config_file)

    def test_load_repos_subtree_path_rejects_non_gitlab_provider(self, tmp_path: Path) -> None:
        """GitHub 레포에 subtree_path를 지정하면 거부한다 (메시지에 gitlab 전용임이 드러남)."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://github.com/org/repo",
                        "subtree_path": "packages/app",
                    }
                ],
            },
        )
        with pytest.raises(ConfigError, match="GitLab"):
            load_config(config_file)

    def test_load_repos_subtree_path_rejects_gitlab_url_fragment(self, tmp_path: Path) -> None:
        """'/-/' 조각이 포함되면(웹 URL을 붙여넣은 실수) 안내와 함께 거부한다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-platform/sample-libs",
                        "subtree_path": "/-/tree/master/sample-model",
                    }
                ],
            },
        )
        with pytest.raises(ConfigError, match="디렉토리 경로"):
            load_config(config_file)

    def test_load_repos_subtree_path_short_form_entry_stays_none(self, tmp_path: Path) -> None:
        """문자열 축약형 repo 항목은 subtree_path 없이 여전히 파싱된다."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "gitlab_url": "https://gitlab.example.com",
                "repos": ["sample-platform/sample-libs"],
            },
        )
        config = load_config(config_file)
        assert config.repos[0].subtree_path is None

    def test_load_repos_nickname_whitespace_stripped(self, tmp_path: Path) -> None:
        """nickname이 공백만 있으면 None으로 처리되어 display_name이 full_path로 fallback."""
        config_file = write_yaml(
            tmp_path,
            {
                "team_name": "test",
                "repos": [
                    {
                        "url": "https://gitlab.example.com/sample-group/repo",
                        "nickname": "   ",  # 공백만
                    }
                ],
            },
        )
        config = load_config(config_file)
        assert len(config.repos) == 1
        # 공백 strip 후 빈 문자열이므로 None
        assert config.repos[0].nickname is None
        # display_name이 full_path로 fallback
        assert config.repos[0].display_name == "sample-group/repo"


class TestExtraHolidays:
    """extra_holidays(임시공휴일·회사 휴무) 파싱 테스트."""

    @staticmethod
    def _load(tmp_path: Path, extra: Any, include_key: bool = True) -> Any:
        data: dict[str, Any] = {
            "team_name": "test",
            "repos": ["https://gitlab.example.com/sample-group/repo"],
        }
        if include_key:
            data["extra_holidays"] = extra
        return load_config(write_yaml(tmp_path, data))

    def test_missing_key_defaults_to_empty_tuple(self, tmp_path: Path) -> None:
        """키가 없으면 빈 튜플이다 (기존 설정 파일 하위 호환)."""
        config = self._load(tmp_path, None, include_key=False)
        assert config.extra_holidays == ()

    def test_empty_list_is_empty_tuple(self, tmp_path: Path) -> None:
        config = self._load(tmp_path, [])
        assert config.extra_holidays == ()

    def test_yaml_date_values_are_accepted(self, tmp_path: Path) -> None:
        """따옴표 없는 ISO 날짜는 YAML이 date로 파싱한다."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "team_name: test\n"
            "repos: ['https://gitlab.example.com/sample-group/repo']\n"
            "extra_holidays:\n"
            "  - 2026-10-02\n"
            "  - 2026-12-31\n"
        )
        config = load_config(config_file)
        assert config.extra_holidays == (date(2026, 10, 2), date(2026, 12, 31))

    def test_date_strings_are_accepted(self, tmp_path: Path) -> None:
        """따옴표로 감싼 문자열도 받는다."""
        config = self._load(tmp_path, ["2026-10-02", "2026-12-31"])
        assert config.extra_holidays == (date(2026, 10, 2), date(2026, 12, 31))

    def test_mixed_date_and_string_items(self, tmp_path: Path) -> None:
        config = self._load(tmp_path, [date(2026, 10, 2), "2026-12-31"])
        assert config.extra_holidays == (date(2026, 10, 2), date(2026, 12, 31))

    @pytest.mark.parametrize(
        "bad_item",
        ["2026/10/02", "20261002", "10-02", "not a date", "2026-13-40", 20261002, True],
    )
    def test_invalid_item_reports_index_and_format(self, tmp_path: Path, bad_item: Any) -> None:
        """잘못된 항목은 몇 번째 항목인지와 기대 형식을 알려 준다."""
        with pytest.raises(ConfigError, match=r"extra_holidays\[1\]: YYYY-MM-DD 형식이어야 합니다"):
            self._load(tmp_path, ["2026-10-02", bad_item])

    def test_datetime_item_is_rejected(self, tmp_path: Path) -> None:
        """시각이 붙은 값은 날짜가 아니다 (datetime은 date의 하위 클래스라 따로 막는다)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "team_name: test\n"
            "repos: ['https://gitlab.example.com/sample-group/repo']\n"
            "extra_holidays:\n"
            "  - 2026-10-02 09:00:00\n"
        )
        with pytest.raises(ConfigError, match=r"extra_holidays\[0\]"):
            load_config(config_file)

    @pytest.mark.parametrize("not_a_list", ["2026-10-02", 20261002, {"2026-10-02": "휴무"}])
    def test_non_list_is_rejected(self, tmp_path: Path, not_a_list: Any) -> None:
        with pytest.raises(ConfigError, match=r"extra_holidays: 리스트이어야 합니다"):
            self._load(tmp_path, not_a_list)

    def test_key_is_known_so_no_unknown_key_warning(self, tmp_path: Path, caplog: Any) -> None:
        self._load(tmp_path, ["2026-10-02"])
        messages = [record.getMessage() for record in caplog.records]
        assert not any("extra_holidays" in message for message in messages)


class TestHolidayCalendar:
    """holiday_calendar(kr | none) 파싱 테스트."""

    @staticmethod
    def _load(tmp_path: Path, calendar: Any, include_key: bool = True) -> Any:
        data: dict[str, Any] = {
            "team_name": "test",
            "repos": ["https://gitlab.example.com/sample-group/repo"],
        }
        if include_key:
            data["holiday_calendar"] = calendar
        return load_config(write_yaml(tmp_path, data))

    @staticmethod
    def _load_yaml_text(tmp_path: Path, calendar_line: str) -> Any:
        """YAML 텍스트를 그대로 쓴다 — safe_dump 로는 만들 수 없는 따옴표 없는 값을 검증한다."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "team_name: test\n"
            "repos: ['https://gitlab.example.com/sample-group/repo']\n"
            f"{calendar_line}\n"
        )
        return load_config(config_file)

    def test_missing_key_defaults_to_kr(self, tmp_path: Path) -> None:
        """키가 없으면 kr 이다 (기존 설정 파일 하위 호환)."""
        config = self._load(tmp_path, None, include_key=False)

        assert config.holiday_calendar == "kr"

    @pytest.mark.parametrize("calendar", ["kr", "none"])
    def test_allowed_values_are_kept(self, tmp_path: Path, calendar: str) -> None:
        config = self._load(tmp_path, calendar)

        assert config.holiday_calendar == calendar

    @pytest.mark.parametrize("bad_value", ["KR", "jp", "", 1, ["kr"]])
    def test_other_values_are_rejected_with_allowed_list(
        self, tmp_path: Path, bad_value: Any
    ) -> None:
        """허용값(kr, none)이 아니면 허용값 목록과 받은 값을 알려 준다."""
        with pytest.raises(ConfigError, match=r"holiday_calendar: 'kr' 또는 'none' 이어야 합니다"):
            self._load(tmp_path, bad_value)

    def test_unquoted_none_in_yaml_is_the_string_none(self, tmp_path: Path) -> None:
        """따옴표 없는 none 은 YAML 에서 문자열 'none' 이다 (null 이 아니다)."""
        config = self._load_yaml_text(tmp_path, "holiday_calendar: none")

        assert config.holiday_calendar == "none"

    @pytest.mark.parametrize("calendar_line", ["holiday_calendar: null", "holiday_calendar:"])
    def test_null_and_empty_value_are_rejected(self, tmp_path: Path, calendar_line: str) -> None:
        """끄려는 뜻으로 적은 값이 조용히 kr 로 바뀌지 않게 null·빈 값은 오류다."""
        with pytest.raises(ConfigError, match=r"holiday_calendar: 'kr' 또는 'none' 이어야 합니다"):
            self._load_yaml_text(tmp_path, calendar_line)

    @pytest.mark.parametrize("calendar_line", ["holiday_calendar: no", "holiday_calendar: off"])
    def test_yaml_boolean_false_is_rejected(self, tmp_path: Path, calendar_line: str) -> None:
        """no·off 는 YAML 에서 False 로 파싱된다 — none 과 헷갈린 값이므로 오류다."""
        with pytest.raises(ConfigError, match=r"holiday_calendar: 'kr' 또는 'none' 이어야 합니다"):
            self._load_yaml_text(tmp_path, calendar_line)

    def test_key_is_known_so_no_unknown_key_warning(self, tmp_path: Path, caplog: Any) -> None:
        self._load(tmp_path, "none")

        messages = [record.getMessage() for record in caplog.records]
        assert not any("holiday_calendar" in message for message in messages)
