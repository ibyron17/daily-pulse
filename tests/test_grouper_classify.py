"""분류 규칙 단위 테스트 (Task 1 - classify.py)."""

from zoneinfo import ZoneInfo

from pulse.config.loader import GroupingHints
from pulse.grouper.classify import (
    classify_branch,
    classify_by_directory,
    classify_commit,
    classify_merge_request,
    extract_prefix_and_name,
    extract_scope,
    extract_ticket_from_branch,
)
from tests.conftest import make_commit, make_merge_request

KST = ZoneInfo("Asia/Seoul")


class TestExtractTicket:
    """branch에서 ticket 번호 추출."""

    def test_jira_format(self) -> None:
        """JIRA-123 형식."""
        assert extract_ticket_from_branch("feature/JIRA-123") == "JIRA-123"
        assert extract_ticket_from_branch("feature-JIRA-456") == "JIRA-456"

    def test_hash_format(self) -> None:
        """#123 형식."""
        assert extract_ticket_from_branch("feature/#789") == "#789"
        assert extract_ticket_from_branch("fix/#42") == "#42"

    def test_no_ticket(self) -> None:
        """ticket이 없는 경우."""
        assert extract_ticket_from_branch("feature/editor") is None
        assert extract_ticket_from_branch("develop") is None


class TestExtractPrefixAndName:
    """branch에서 prefix와 name 추출."""

    def test_slash_separator(self) -> None:
        """slash 구분자."""
        assert extract_prefix_and_name("feature/JIRA-123") == ("feature", "JIRA-123")
        assert extract_prefix_and_name("fix/editor") == ("fix", "editor")

    def test_dash_separator(self) -> None:
        """dash 구분자."""
        assert extract_prefix_and_name("feature-JIRA-123") == ("feature", "JIRA-123")

    def test_no_separator(self) -> None:
        """구분자 없음."""
        assert extract_prefix_and_name("develop") is None

    def test_colon_separator(self) -> None:
        """colon 구분자."""
        assert extract_prefix_and_name("feat:auth") == ("feat", "auth")
        assert extract_prefix_and_name("fix:bug") == ("fix", "bug")


class TestExtractScope:
    """conventional commit에서 scope 추출."""

    def test_standard_scope(self) -> None:
        """feat(scope): message."""
        assert extract_scope("feat(auth): add login") == "auth"
        assert extract_scope("fix(editor): typo") == "editor"

    def test_no_scope(self) -> None:
        """scope 없음."""
        assert extract_scope("feat: add feature") is None
        assert extract_scope("Merge branch") is None

    def test_nested_scope(self) -> None:
        """nested scope."""
        assert extract_scope("feat(user/profile): update") == "user/profile"

    def test_scope_with_dashes(self) -> None:
        """scope에 대시."""
        assert extract_scope("feat(auth-service): add") == "auth-service"


class TestClassifyByDirectory:
    """파일 경로 기반 디렉토리 분류 (경로 길이 내림차순)."""

    def test_single_match(self) -> None:
        """단일 매칭."""
        hints = GroupingHints(directories=(("src/editor", "에디터"),))
        result = classify_by_directory(("src/editor/index.ts",), hints)
        assert result is not None
        assert result.group_name == "에디터"

    def test_longest_path_first(self) -> None:
        """경로 길이 내림차순: src/components/editor > src/components."""
        hints = GroupingHints(
            directories=(
                ("src/components", "컴포넌트"),
                ("src/components/editor", "에디터"),
            )
        )
        result = classify_by_directory(("src/components/editor/Button.tsx",), hints)
        assert result is not None
        assert result.group_name == "에디터"

    def test_no_match(self) -> None:
        """매칭 없음."""
        hints = GroupingHints(directories=(("src/api", "API"),))
        result = classify_by_directory(("tests/test.ts",), hints)
        assert result is None

    def test_empty_changed_files(self) -> None:
        """빈 파일 목록."""
        hints = GroupingHints(directories=(("src", "소스"),))
        result = classify_by_directory((), hints)
        assert result is None

    def test_multiple_files_first_match(self) -> None:
        """여러 파일, 첫 매칭만 사용."""
        hints = GroupingHints(directories=(("src/editor", "에디터"),))
        result = classify_by_directory(("src/editor/index.ts", "src/api/api.ts"), hints)
        assert result is not None
        assert result.group_name == "에디터"


class TestClassifyCommit:
    """커밋 5단계 분류."""

    def test_hints_priority(self) -> None:
        """hints가 최우선."""
        hints = GroupingHints(
            branch_prefixes=(("feature", "기능"),),
            directories=(("src/editor", "에디터"),),
        )
        commit = make_commit(
            branch="feature/anything",
            changed_files=("src/editor/index.ts",),
        )
        result = classify_commit(commit, hints)
        assert result.group_name == "기능"
        assert result.source_rule == "hints"

    def test_branch_rule(self) -> None:
        """hints 없으면 branch."""
        commit = make_commit(branch="feature/editor-autosave")
        hints = GroupingHints()
        result = classify_commit(commit, hints)
        assert result.group_name == "editor-autosave"
        assert result.source_rule == "branch"

    def test_directory_rule(self) -> None:
        """hints, branch 없으면 directory."""
        commit = make_commit(
            branch="some-branch",
            changed_files=("src/editor/index.ts",),
        )
        hints = GroupingHints(directories=(("src/editor", "에디터"),))
        result = classify_commit(commit, hints)
        assert result.group_name == "에디터"
        assert result.source_rule == "directory"

    def test_scope_rule(self) -> None:
        """directory 없으면 scope."""
        commit = make_commit(
            branch="something",
            message="feat(auth): add login",
            changed_files=("src/index.ts",),
        )
        hints = GroupingHints()
        result = classify_commit(commit, hints)
        assert result.group_name == "auth"
        assert result.source_rule == "scope"

    def test_unclassified(self) -> None:
        """브랜치 정보 없으면 unclassified."""
        commit = make_commit(
            branch="",
            message="some commit",
            changed_files=("index.ts",),
        )
        hints = GroupingHints()
        result = classify_commit(commit, hints)
        assert result.group_name == "unclassified"
        assert result.source_rule == "unclassified"


class TestClassifyMergeRequest:
    """MR 5단계 분류 (hints → branch → label → unclassified)."""

    def test_hints_priority(self) -> None:
        """hints가 최우선."""
        hints = GroupingHints(branch_prefixes=(("feature", "기능"),))
        mr = make_merge_request(source_branch="feature/editor")
        result = classify_merge_request(mr, hints)
        assert result.group_name == "기능"
        assert result.source_rule == "hints"

    def test_branch_rule(self) -> None:
        """hints 없으면 source_branch."""
        mr = make_merge_request(source_branch="feature/auth-service")
        hints = GroupingHints()
        result = classify_merge_request(mr, hints)
        assert result.group_name == "auth-service"
        assert result.source_rule == "branch"

    def test_label_rule(self) -> None:
        """branch 없으면 label (첫 라벨)."""
        mr = make_merge_request(
            source_branch="develop",
            labels=("backend", "database"),
        )
        hints = GroupingHints()
        result = classify_merge_request(mr, hints)
        assert result.group_name == "backend"
        assert result.source_rule == "label"

    def test_unclassified(self) -> None:
        """source_branch 정보 없으면 unclassified."""
        mr = make_merge_request(
            source_branch="",
            labels=(),
        )
        hints = GroupingHints()
        result = classify_merge_request(mr, hints)
        assert result.group_name == "unclassified"
        assert result.source_rule == "unclassified"


class TestClassifyBranch:
    """브랜치명 5단계 분류 (hints → branch → unclassified)."""

    def test_hints_priority(self) -> None:
        """hints가 최우선."""
        hints = GroupingHints(branch_prefixes=(("feature", "기능"),))
        result = classify_branch("feature/editor", hints)
        assert result.group_name == "기능"
        assert result.source_rule == "hints"

    def test_branch_rule(self) -> None:
        """hints 없으면 branch 규칙."""
        result = classify_branch("feature/auth-service", GroupingHints())
        assert result.group_name == "auth-service"
        assert result.source_rule == "branch"

    def test_branch_name_fallback(self) -> None:
        """규칙 미적용 시 branch-name 폴백."""
        result = classify_branch("develop", GroupingHints())
        assert result.group_name == "develop"
        assert result.source_rule == "branch-name"


class TestEdgeCases:
    """엣지 케이스."""

    def test_empty_branch_name(self) -> None:
        """빈 브랜치명은 branch-name 폴백 (빈 이름으로)."""
        result = classify_branch("", GroupingHints())
        assert result.source_rule == "branch-name"
        assert result.group_name == ""

    def test_special_characters_in_directory(self) -> None:
        """디렉토리에 특수문자."""
        hints = GroupingHints(directories=(("src/ui-components", "UI"),))
        result = classify_by_directory(("src/ui-components/Button.tsx",), hints)
        assert result is not None
        assert result.group_name == "UI"

    def test_case_sensitivity_in_hints(self) -> None:
        """hints는 정확히 매칭 (대소문자 구분)."""
        hints = GroupingHints(branch_prefixes=(("Feature", "기능"),))
        # 소문자 "feature"는 매칭 안 됨
        result = classify_branch("feature/something", hints)
        assert result.source_rule == "branch"

    def test_scope_with_special_chars(self) -> None:
        """scope에 특수문자."""
        scope = extract_scope("feat(user-profile): update")
        assert scope == "user-profile"
