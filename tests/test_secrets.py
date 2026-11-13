"""토큰 폴백 리소버 테스트."""

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pulse.secrets import (
    TokenError,
    clear_token,
    missing_token_hint,
    resolve_token,
    store_token,
    token_source,
)


class TestResolveToken:
    """resolve_token 함수 테스트."""

    def test_resolve_token_env_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 설정되면 env 값 반환."""
        monkeypatch.setenv("GITLAB_TOKEN", "env_token")
        result = resolve_token("gitlab")
        assert result == "env_token"

    def test_resolve_token_env_absent_keyring_present(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """env 없고 keyring에 있으면 keyring 값 반환."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = "keyring_token"

        result = resolve_token("gitlab")
        assert result == "keyring_token"
        mock_keyring.get_password.assert_called_once_with("daily-pulse", "gitlab")

    def test_resolve_token_both_absent_gh_present_github_only(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """env/keyring 없고 gh 있으면 gh 값 반환 (GitHub만)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        with patch("pulse.secrets.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="gh_token\n")
            result = resolve_token("github")
            assert result == "gh_token"
            mock_run.assert_called_once()

    def test_resolve_token_github_no_gh_fallback(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """gitlab은 gh 폴백 없음."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        result = resolve_token("gitlab")
        assert result is None

    def test_resolve_token_all_absent(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """모두 없으면 None 반환."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        result = resolve_token("gitlab")
        assert result is None

    def test_resolve_token_keyring_exception_fallback_to_env(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """keyring 예외 발생하면 env로 폴백."""
        monkeypatch.setenv("GITLAB_TOKEN", "env_token")
        mock_keyring.get_password.side_effect = Exception("keyring error")

        result = resolve_token("gitlab")
        assert result == "env_token"

    def test_resolve_token_gh_timeout(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """gh auth token timeout하면 None으로 계속."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        with patch("pulse.secrets.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("gh", 5)
            result = resolve_token("github")
            assert result is None

    def test_resolve_token_gh_not_installed(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """gh CLI 미설치하면 None으로 계속."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        with patch("pulse.secrets.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")
            result = resolve_token("github")
            assert result is None


class TestStoreToken:
    """store_token 함수 테스트."""

    def test_store_token_success(self, mock_keyring: MagicMock) -> None:
        """토큰 저장 성공."""
        store_token("gitlab", "test_token")
        mock_keyring.set_password.assert_called_once_with("daily-pulse", "gitlab", "test_token")

    def test_store_token_keyring_failure(self, mock_keyring: MagicMock) -> None:
        """keyring 저장 실패하면 TokenError 발생."""
        mock_keyring.set_password.side_effect = Exception("save failed")

        with pytest.raises(TokenError, match="keyring 저장 실패"):
            store_token("gitlab", "test_token")


class TestTokenSource:
    """token_source 함수 테스트."""

    def test_token_source_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 설정되면 "env" 반환."""
        monkeypatch.setenv("GITLAB_TOKEN", "env_token")
        result = token_source("gitlab")
        assert result == "env"

    def test_token_source_keyring(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """env 없고 keyring에 있으면 "keyring" 반환."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = "keyring_token"

        result = token_source("gitlab")
        assert result == "keyring"

    def test_token_source_gh(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """env/keyring 없고 gh 있으면 "gh" 반환 (GitHub만)."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        with patch("pulse.secrets.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="gh_token\n")
            result = token_source("github")
            assert result == "gh"

    def test_token_source_none(
        self, monkeypatch: pytest.MonkeyPatch, mock_keyring: MagicMock
    ) -> None:
        """모두 없으면 None 반환."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.return_value = None

        result = token_source("gitlab")
        assert result is None


class TestClearToken:
    """clear_token 함수 테스트."""

    def test_clear_token_success(self, mock_keyring: MagicMock) -> None:
        """토큰 제거 성공."""
        clear_token("gitlab")
        mock_keyring.delete_password.assert_called_once_with("daily-pulse", "gitlab")

    def test_clear_token_failure(self, mock_keyring: MagicMock) -> None:
        """제거 실패하면 TokenError 발생."""
        mock_keyring.delete_password.side_effect = Exception("delete failed")

        with pytest.raises(TokenError, match="keyring 제거 실패"):
            clear_token("gitlab")


class TestTokenValueNotLogged:
    """토큰 값이 로그에 포함되지 않음을 확인."""

    def test_resolve_token_logging_no_value_in_keyring_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_keyring: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """keyring 조회 예외 시 로그에 토큰 값 미포함."""
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mock_keyring.get_password.side_effect = Exception("keyring error details with secrets")

        with caplog.at_level(logging.WARNING):
            resolve_token("gitlab")

        # 로그에 토큰 값이 포함되지 않았는지 확인 (provider와 source만)
        for record in caplog.records:
            assert "keyring error details with secrets" not in record.message

    def test_store_token_error_no_value_in_message(self, mock_keyring: MagicMock) -> None:
        """토큰 저장 실패 메시지에 토큰 값 미포함."""
        mock_keyring.set_password.side_effect = Exception("backend error")

        with pytest.raises(TokenError) as exc_info:
            store_token("gitlab", "my_secret_token")

        # 예외 메시지에 토큰 값 미포함
        assert "my_secret_token" not in str(exc_info.value)


class TestMissingTokenHint:
    """missing_token_hint 안내 문구."""

    def test_hint_gitlab_includes_both_methods(self) -> None:
        """GitLab 미설정 안내에 env export·keyring 저장 두 방법이 모두 포함된다."""
        hint = missing_token_hint(("GITLAB_TOKEN",))

        assert "GITLAB_TOKEN" in hint
        assert "export GITLAB_TOKEN" in hint
        assert "token set --provider gitlab" in hint

    def test_hint_multiple_providers_each_guided(self) -> None:
        """여러 provider 미설정 시 각각의 저장 방법이 안내된다."""
        hint = missing_token_hint(("GITLAB_TOKEN", "GITHUB_TOKEN"))

        assert "token set --provider gitlab" in hint
        assert "token set --provider github" in hint

    def test_hint_unknown_env_var_falls_back_to_name(self) -> None:
        """매핑에 없는 env 변수명은 그대로 표기한다 (KeyError 없이)."""
        hint = missing_token_hint(("UNKNOWN_TOKEN",))

        assert "UNKNOWN_TOKEN" in hint
