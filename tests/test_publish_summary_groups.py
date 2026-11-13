"""extract_summary_input_by_repo의 groups 섹션 테스트."""

from datetime import date, datetime

from pulse.models import CommitInfo, DashboardModel, FeatureGroup, MergeRequestInfo, TaskSummary
from pulse.publish import MAX_SUMMARY_CHARS_PER_GROUP, extract_summary_input_by_repo


def test_extract_summary_input_by_repo_groups_basic() -> None:
    """extract_summary_input_by_repo가 groups 섹션을 포함한다."""
    commits = (
        CommitInfo(
            sha="abc123",
            author_name="alice",
            authored_at=date(2024, 1, 1),  # type: ignore
            message="Fix bug",
            branch="main",
            changed_files=("file.py",),
            web_url="",
        ),
    )

    mrs = (
        MergeRequestInfo(
            iid=1,
            title="PR: Fix",
            state="open",
            is_draft=False,
            labels=(),
            source_branch="fix/bug",
            target_branch="main",
            author_name="alice",
            created_at=date(2024, 1, 1),  # type: ignore
            updated_at=date(2024, 1, 1),  # type: ignore
            merged_at=None,
            reviews=(),
            is_external=False,
            web_url="",
        ),
    )

    task_summary = TaskSummary(
        commit_titles=("Fix bug",),
        open_mr_titles=("PR: Fix",),
        active_branch_names=("fix/bug",),
    )

    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=commits,
            merge_requests=mrs,
            branch_names=("fix/bug",),
            participants=(),
            task_summary=task_summary,
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=groups,
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
        period="daily",
    )

    result = extract_summary_input_by_repo(model)

    # groups 섹션이 있는지 확인
    assert "groups" in result
    groups_dict = result.get("groups")
    assert isinstance(groups_dict, dict)

    # key는 "org/repo::Feature A" 형태
    key = "org/repo::Feature A"
    assert key in groups_dict

    group_data = groups_dict[key]
    assert group_data["name"] == "Feature A"
    assert group_data["stage"] == "developing"
    assert group_data["commit_titles"] == ["Fix bug"]
    assert group_data["branch_names"] == ["fix/bug"]
    assert group_data["mr_titles"] == ["PR: Fix"]


def test_extract_summary_input_by_repo_groups_multiple() -> None:
    """extract_summary_input_by_repo가 여러 그룹을 올바르게 처리한다."""
    # Feature A 커밋들
    commit_a = CommitInfo(
        sha="abc123",
        author_name="alice",
        authored_at=datetime(2024, 1, 1),
        message="Commit A",
        branch="branch-a",
        changed_files=(),
        web_url="",
    )

    # Feature B 커밋들 (내림차순으로 정렬되므로 최신순)
    commit_b1 = CommitInfo(
        sha="def456",
        author_name="bob",
        authored_at=datetime(2024, 1, 2),
        message="Commit B",
        branch="branch-b",
        changed_files=(),
        web_url="",
    )

    commit_b2 = CommitInfo(
        sha="ghi789",
        author_name="bob",
        authored_at=datetime(2024, 1, 1),
        message="Commit B2",
        branch="branch-b",
        changed_files=(),
        web_url="",
    )

    task_summary_a = TaskSummary(
        commit_titles=("Commit A",),
        open_mr_titles=("MR A",),
        active_branch_names=("branch-a",),
    )

    task_summary_b = TaskSummary(
        commit_titles=("Commit B", "Commit B2"),
        open_mr_titles=(),
        active_branch_names=("branch-b",),
    )

    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo1",
            commits=(commit_a,),
            merge_requests=(),
            branch_names=(),
            participants=(),
            task_summary=task_summary_a,
        ),
        FeatureGroup(
            name="Feature B",
            source_rule="label",
            evidence="",
            stage="reviewing",
            repo_full_path="org/repo1",
            commits=(commit_b1, commit_b2),
            merge_requests=(),
            branch_names=(),
            participants=(),
            task_summary=task_summary_b,
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=groups,
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo1",),
        period="daily",
    )

    result = extract_summary_input_by_repo(model)

    groups_dict = result.get("groups")
    assert isinstance(groups_dict, dict)
    assert "org/repo1::Feature A" in groups_dict
    assert "org/repo1::Feature B" in groups_dict

    # Feature A 확인
    feature_a = groups_dict["org/repo1::Feature A"]
    assert feature_a["name"] == "Feature A"
    assert feature_a["stage"] == "developing"
    assert feature_a["commit_titles"] == ["Commit A"]

    # Feature B 확인
    feature_b = groups_dict["org/repo1::Feature B"]
    assert feature_b["name"] == "Feature B"
    assert feature_b["stage"] == "reviewing"
    assert feature_b["commit_titles"] == ["Commit B", "Commit B2"]
    assert feature_b["mr_titles"] == []


def test_extract_summary_input_by_repo_groups_empty() -> None:
    """extract_summary_input_by_repo가 그룹이 없으면 빈 groups dict를 반환한다."""
    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
        period="daily",
    )

    result = extract_summary_input_by_repo(model)

    groups_dict = result.get("groups")
    assert isinstance(groups_dict, dict)
    assert len(groups_dict) == 0


def test_extract_summary_input_by_repo_groups_cross_repo() -> None:
    """extract_summary_input_by_repo가 다중 레포의 그룹을 올바르게 처리한다."""
    task_summary = TaskSummary(
        commit_titles=(),
        open_mr_titles=(),
        active_branch_names=(),
    )

    groups = (
        FeatureGroup(
            name="Feature X",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo-a",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            task_summary=task_summary,
        ),
        FeatureGroup(
            name="Feature Y",
            source_rule="label",
            evidence="",
            stage="reviewing",
            repo_full_path="org/repo-b",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
            task_summary=task_summary,
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=groups,
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo-a", "org/repo-b"),
        period="daily",
    )

    result = extract_summary_input_by_repo(model)

    groups_dict = result.get("groups")
    assert isinstance(groups_dict, dict)
    assert "org/repo-a::Feature X" in groups_dict
    assert "org/repo-b::Feature Y" in groups_dict

    # 레포별 그룹 분리 확인
    feature_x = groups_dict["org/repo-a::Feature X"]
    assert feature_x["name"] == "Feature X"
    assert feature_x["stage"] == "developing"

    feature_y = groups_dict["org/repo-b::Feature Y"]
    assert feature_y["name"] == "Feature Y"
    assert feature_y["stage"] == "reviewing"


def _make_commit_with_files(
    sha: str,
    changed_files: tuple[str, ...],
    changed_files_summary: str | None,
) -> CommitInfo:
    """changed_files 메타 검증용 커밋 생성."""
    return CommitInfo(
        sha=sha,
        author_name="alice",
        authored_at=date(2024, 1, 1),  # type: ignore
        message="msg",
        branch="main",
        changed_files=changed_files,
        web_url="",
        changed_files_summary=changed_files_summary,
    )


def _make_model_with_single_group(commits: tuple[CommitInfo, ...]) -> DashboardModel:
    """커밋 구성만 다른 단일 그룹 모델 생성."""
    group = FeatureGroup(
        name="Feature A",
        source_rule="branch",
        evidence="",
        stage="developing",
        repo_full_path="org/repo",
        commits=commits,
        merge_requests=(),
        branch_names=(),
        participants=(),
        task_summary=TaskSummary(
            commit_titles=("Fix bug",),
            open_mr_titles=(),
            active_branch_names=(),
        ),
    )
    return DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=(group,),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo",),
        period="daily",
    )


def test_extract_groups_includes_changed_files_meta() -> None:
    """seed에 changed_files_count(합집합)와 changed_files_summary(발췌 병합)가 포함된다."""
    commits = (
        _make_commit_with_files("sha1", ("a.py", "b.py"), "a.py (+1/-0)\nb.py (+2/-1)"),
        _make_commit_with_files("sha2", ("b.py", "c.py"), "c.py (+5/-0) @@ def run"),
    )
    result = extract_summary_input_by_repo(_make_model_with_single_group(commits))

    groups_dict = result["groups"]
    assert isinstance(groups_dict, dict)
    group_data = groups_dict["org/repo::Feature A"]

    assert group_data["changed_files_count"] == 3  # a, b, c — 중복 제거
    assert group_data["changed_files_summary"] == (
        "a.py (+1/-0)\nb.py (+2/-1)\nc.py (+5/-0) @@ def run"
    )


def test_extract_groups_changed_files_summary_none_when_absent() -> None:
    """커밋에 발췌가 없으면(구 스냅샷 재사용) summary는 None, count는 유지된다."""
    commits = (_make_commit_with_files("sha1", ("a.py",), None),)
    result = extract_summary_input_by_repo(_make_model_with_single_group(commits))

    groups_dict = result["groups"]
    assert isinstance(groups_dict, dict)
    group_data = groups_dict["org/repo::Feature A"]

    assert group_data["changed_files_count"] == 1
    assert group_data["changed_files_summary"] is None


def test_extract_groups_changed_files_summary_truncated_to_group_limit() -> None:
    """그룹 병합 발췌는 MAX_SUMMARY_CHARS_PER_GROUP에서 절단된다."""
    long_summary = "x" * (MAX_SUMMARY_CHARS_PER_GROUP + 500)
    commits = (_make_commit_with_files("sha1", ("a.py",), long_summary),)
    result = extract_summary_input_by_repo(_make_model_with_single_group(commits))

    groups_dict = result["groups"]
    assert isinstance(groups_dict, dict)
    group_data = groups_dict["org/repo::Feature A"]

    assert len(group_data["changed_files_summary"]) == MAX_SUMMARY_CHARS_PER_GROUP
