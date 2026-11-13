"""HTML 및 JavaScript 이스케이프 유틸."""

import html as html_module

# URL 스킴 화이트리스트
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def escape_html(text: str) -> str:
    """HTML에서 특수 문자를 이스케이프한다.

    Args:
        text: 원본 텍스트

    Returns:
        이스케이프된 텍스트
    """
    return html_module.escape(text)


def escape_attr(value: str) -> str:
    """HTML 속성값을 이스케이프한다.

    Args:
        value: 속성값

    Returns:
        이스케이프된 속성값
    """
    return html_module.escape(value, quote=True)


def escape_url(url: str) -> str:
    """href용 URL 이스케이프. http/https 외 스킴은 빈 문자열로 무력화한다.

    javascript:, data: 같은 위험 스킴을 차단하여 XSS를 방지한다.

    Args:
        url: 원본 URL

    Returns:
        안전한 URL 문자열 (허용 스킴만) 또는 빈 문자열 (차단됨)
    """
    if not url.startswith(_ALLOWED_URL_SCHEMES):
        return ""
    return html_module.escape(url, quote=True)
