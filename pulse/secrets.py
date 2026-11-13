"""토큰 계층 폴백 및 크로스플랫폼 Keyring 리소버."""

import logging
import os
import subprocess
from typing import Literal

import keyring

logger = logging.getLogger(__name__)

Provider = Literal["gitlab", "github"]

KEYRING_SERVICE = "daily-pulse"
KEYRING_USERNAMES = {
    "gitlab": "gitlab",
    "github": "github",
}
ENV_VAR_NAMES = {
    "gitlab": "GITLAB_TOKEN",
    "github": "GITHUB_TOKEN",
}
# 안내 문구에서 env 변수명 → provider 역매핑
_ENV_TO_PROVIDER = {env_var: provider for provider, env_var in ENV_VAR_NAMES.items()}
GH_TIMEOUT_SECONDS = 5


class TokenError(Exception):
    """토큰 저장/조회 실패."""


def missing_token_hint(env_vars: tuple[str, ...]) -> str:
    """미설정 토큰에 대한 설정 방법 안내 문구를 생성한다 (토큰 값 미포함).

    Args:
        env_vars: 누락된 env 변수명 tuple (예: ("GITLAB_TOKEN",))

    Returns:
        env export / keyring 저장 두 방법을 안내하는 한 줄 문구
    """
    parts: list[str] = []
    for env_var in env_vars:
        provider = _ENV_TO_PROVIDER.get(env_var)
        if provider is None:
            parts.append(env_var)
            continue
        parts.append(
            f"{env_var}("
            f"`export {env_var}=...` 또는 "
            f"`python -m pulse.publish token set --provider {provider}`)"
        )
    return "토큰 미설정 — " + " / ".join(parts)


def resolve_token(provider: Provider) -> str | None:
    """
    토큰 확인 계층 폴백.

    1) 환경변수 (GITLAB_TOKEN / GITHUB_TOKEN) 있으면 → 사용
    2) 없으면 keyring에서 조회
    3) 없으면 gh auth token (GitHub만)
    4) 모두 없으면 → None

    예외(keyring backend 없음 등)는 로깅만 하고 폴백 계속.

    Args:
        provider: "gitlab" or "github"

    Returns:
        토큰 값, 또는 None (모두 실패한 경우)
    """
    env_var = ENV_VAR_NAMES[provider]

    # 1) 환경변수 체크
    if env_var in os.environ:
        return os.environ[env_var]

    # 2) keyring 체크
    try:
        username = KEYRING_USERNAMES[provider]
        token = keyring.get_password(KEYRING_SERVICE, username)
        if token:
            return token
    except Exception as e:
        logger.warning("keyring 조회 실패 (%s): %s", provider, type(e).__name__)

    # 3) GitHub의 경우 gh 폴백 (GitLab은 없음)
    if provider == "github":
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token
        except subprocess.TimeoutExpired:
            logger.debug("gh auth token timeout")
        except FileNotFoundError:
            logger.debug("gh CLI 미설치")
        except Exception as e:
            logger.debug("gh auth token 실패: %s", type(e).__name__)

    # 4) 모두 실패
    return None


def store_token(provider: Provider, value: str) -> None:
    """
    토큰 값을 keyring에 저장.

    Args:
        provider: "gitlab" or "github"
        value: 토큰 값 (stdin으로 안전하게 받음)

    Raises:
        TokenError: 저장 실패 (keyring 미지원 등)
    """
    try:
        username = KEYRING_USERNAMES[provider]
        keyring.set_password(KEYRING_SERVICE, username, value)
    except Exception as e:
        raise TokenError(f"keyring 저장 실패 ({provider}): {type(e).__name__}") from e


def token_source(provider: Provider) -> str | None:
    """
    토큰의 출처를 조회 (값 아님).

    Returns:
        "env", "keyring", "gh" 또는 None
    """
    env_var = ENV_VAR_NAMES[provider]

    # 1) 환경변수
    if env_var in os.environ:
        return "env"

    # 2) keyring
    try:
        username = KEYRING_USERNAMES[provider]
        token = keyring.get_password(KEYRING_SERVICE, username)
        if token:
            return "keyring"
    except Exception:
        pass

    # 3) gh (GitHub만)
    if provider == "github":
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT_SECONDS,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "gh"
        except Exception:
            pass

    # 4) 없음
    return None


def clear_token(provider: Provider) -> None:
    """keyring에서 토큰 제거."""
    try:
        username = KEYRING_USERNAMES[provider]
        keyring.delete_password(KEYRING_SERVICE, username)
    except Exception as e:
        raise TokenError(f"keyring 제거 실패 ({provider}): {type(e).__name__}") from e
