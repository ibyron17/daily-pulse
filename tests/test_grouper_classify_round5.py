"""Phase 1 분류 함수 테스트: is_release_line_branch, extract_bracket_scope, extract_issue_keys."""

from pulse.grouper.classify import (
    extract_bracket_scope,
    extract_issue_keys,
    is_release_line_branch,
)


class TestIsReleaseLineBranch:
    """is_release_line_branch 테스트."""

    def test_is_release_line_branch_main(self) -> None:
        """main은 릴리스 라인."""
        patterns = ("main", "master", "develop")
        assert is_release_line_branch("main", patterns) is True

    def test_is_release_line_branch_develop(self) -> None:
        """develop은 릴리스 라인."""
        patterns = ("main", "master", "develop")
        assert is_release_line_branch("develop", patterns) is True

    def test_is_release_line_branch_feature_auth(self) -> None:
        """feature/auth는 릴리스 라인이 아님."""
        patterns = ("main", "master", "develop")
        assert is_release_line_branch("feature/auth", patterns) is False

    def test_is_release_line_branch_case_insensitive(self) -> None:
        """대소문자 무시."""
        patterns = ("main", "develop")
        assert is_release_line_branch("MAIN", patterns) is True
        assert is_release_line_branch("DeveloP", patterns) is True

    def test_is_release_line_branch_custom_pattern(self) -> None:
        """커스텀 패턴."""
        patterns = ("release/v1", "hotfix/bug")
        assert is_release_line_branch("release/v1", patterns) is True
        assert is_release_line_branch("feature/x", patterns) is False


class TestExtractBracketScope:
    """extract_bracket_scope 테스트."""

    def test_extract_bracket_scope_valid(self) -> None:
        """[type][scope] 형식."""
        assert extract_bracket_scope("[feat][auth] 개선") == "auth"

    def test_extract_bracket_scope_no_brackets(self) -> None:
        """브래킷 없음."""
        assert extract_bracket_scope("feat: 개선") is None

    def test_extract_bracket_scope_only_type(self) -> None:
        """[type]만 있음."""
        assert extract_bracket_scope("[feat] 개선") is None

    def test_extract_bracket_scope_special_chars(self) -> None:
        """특수 문자."""
        assert extract_bracket_scope("[type][api-v2] 수정") == "api-v2"


class TestExtractIssueKeys:
    """extract_issue_keys 테스트."""

    def test_extract_issue_keys_single(self) -> None:
        """단일 키."""
        keys = extract_issue_keys("Fix DOCS-123")
        assert keys == ("DOCS-123",)

    def test_extract_issue_keys_multiple(self) -> None:
        """다중 키."""
        keys = extract_issue_keys("DOCS-123 and B20C-456")
        assert keys == ("DOCS-123", "B20C-456")

    def test_extract_issue_keys_duplicates_deduped(self) -> None:
        """중복 제거."""
        keys = extract_issue_keys("DOCS-123 DOCS-123")
        assert keys == ("DOCS-123",)

    def test_extract_issue_keys_lowercase_not_matched(self) -> None:
        """소문자는 매칭 안 함."""
        keys = extract_issue_keys("docs-123")
        assert keys == ()

    def test_extract_issue_keys_from_branch_name(self) -> None:
        """브랜치 이름에서."""
        keys = extract_issue_keys("feature/JIRA-999")
        assert keys == ("JIRA-999",)


class TestNormalizeReleaseLineName:
    """normalize_release_line_name — 라인 그룹명 표준화."""

    def test_normalize_release_line_name_uppercase_label(self) -> None:
        """MR 라벨 유래 대문자 라인명은 패턴 표기로 정규화된다."""
        from pulse.config.loader import DEFAULT_RELEASE_LINE_PATTERNS
        from pulse.grouper.classify import normalize_release_line_name

        assert normalize_release_line_name("DEVQA", DEFAULT_RELEASE_LINE_PATTERNS) == "devqa"
        assert normalize_release_line_name("SQA", DEFAULT_RELEASE_LINE_PATTERNS) == "sqa"

    def test_normalize_release_line_name_exact_passthrough(self) -> None:
        """이미 패턴 표기인 라인명은 그대로 유지된다."""
        from pulse.config.loader import DEFAULT_RELEASE_LINE_PATTERNS
        from pulse.grouper.classify import normalize_release_line_name

        assert normalize_release_line_name("devqa", DEFAULT_RELEASE_LINE_PATTERNS) == "devqa"
        assert normalize_release_line_name("master", DEFAULT_RELEASE_LINE_PATTERNS) == "master"

    def test_normalize_release_line_name_non_line_unchanged(self) -> None:
        """라인 패턴과 무관한 그룹명은 대소문자 포함 원본 유지."""
        from pulse.config.loader import DEFAULT_RELEASE_LINE_PATTERNS
        from pulse.grouper.classify import normalize_release_line_name

        assert (
            normalize_release_line_name("OAuth-Login", DEFAULT_RELEASE_LINE_PATTERNS)
            == "OAuth-Login"
        )
        assert (
            normalize_release_line_name("feature/devqa-fix", DEFAULT_RELEASE_LINE_PATTERNS)
            == "feature/devqa-fix"
        )
