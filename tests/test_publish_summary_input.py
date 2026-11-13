"""발행 스킬용 요약 입력 데이터 추출 및 스니펫 생성 테스트 (레포별)."""

import tempfile
from datetime import date
from pathlib import Path

from pulse.models import (
    DashboardModel,
    FeatureGroup,
    NewWorkSignal,
    WarningSignal,
)
from pulse.publish import (
    _inject_into_saved_reports,
    build_share_snippet,
    extract_summary_input,
    extract_summary_input_by_repo,
)
from pulse.renderer.html import ai_summary_slot


def test_extract_summary_input_basic() -> None:
    """extract_summary_input이 기본 필드를 추출한다."""
    model = DashboardModel(
        team_name="Test Team",
        report_date=date(2024, 1, 15),
        lookback_hours=24,
        summary_line="요약 줄",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.1,
        period="daily",
    )

    result = extract_summary_input(model)

    assert result["team_name"] == "Test Team"
    assert result["report_date"] == "2024-01-15"
    assert result["lookback_hours"] == 24
    assert result["period"] == "daily"
    assert result["group_count"] == 0
    assert result["new_work_count"] == 0
    assert result["warning_count"] == 0


def test_extract_summary_input_with_groups() -> None:
    """extract_summary_input이 group_names와 group_count를 포함한다."""
    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="branch: feature-a",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        ),
        FeatureGroup(
            name="Feature B",
            source_rule="label",
            evidence="label: feature-b",
            stage="reviewing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
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
    )

    result = extract_summary_input(model)

    assert result["group_count"] == 2
    assert result["group_names"] == ["Feature A", "Feature B"]


def test_extract_summary_input_with_warnings() -> None:
    """extract_summary_input이 warning_titles를 포함한다."""
    warnings = (
        WarningSignal(
            kind="stale_mr",
            title="PR #123 정체",
            description="3일 이상 리뷰 대기",
            days=3,
            web_url="https://example.com/pr/123",
        ),
        WarningSignal(
            kind="stale_branch",
            title="develop 브랜치 방치",
            description="7일 이상 푸시 없음",
            days=7,
            web_url="https://example.com/branches/develop",
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=(),
        new_work=(),
        warnings=warnings,
        unclassified_ratio=0.0,
    )

    result = extract_summary_input(model)

    assert result["warning_count"] == 2
    assert "PR #123 정체" in result.get("warning_titles", [])  # type: ignore
    assert "develop 브랜치 방치" in result.get("warning_titles", [])  # type: ignore


def test_extract_summary_input_with_new_work() -> None:
    """extract_summary_input이 new_work_count를 포함한다."""
    new_work = (
        NewWorkSignal(
            title="Feature X",
            repo_full_path="org/repo",
            branch_or_mr="feature-x",
            web_url="https://example.com/branches/feature-x",
        ),
        NewWorkSignal(
            title="Bugfix Y",
            repo_full_path="org/repo",
            branch_or_mr="hotfix/y",
            web_url="https://example.com/branches/hotfix/y",
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=(),
        new_work=new_work,
        warnings=(),
        unclassified_ratio=0.0,
    )

    result = extract_summary_input(model)

    assert result["new_work_count"] == 2


def test_extract_summary_input_repos() -> None:
    """extract_summary_input이 repos 목록을 포함한다."""
    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        repos=("org/repo1", "org/repo2", "org/repo3"),
    )

    result = extract_summary_input(model)

    assert result["repos"] == ["org/repo1", "org/repo2", "org/repo3"]


def test_extract_summary_input_period_weekly() -> None:
    """extract_summary_input이 주간 period를 반영한다."""
    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 8),
        lookback_hours=168,
        summary_line="",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.0,
        period="weekly",
    )

    result = extract_summary_input(model)

    assert result["period"] == "weekly"
    assert result["lookback_hours"] == 168


def test_extract_summary_input_no_personal_names() -> None:
    """extract_summary_input이 개인 이름을 포함하지 않는다."""
    groups = (
        FeatureGroup(
            name="Feature",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=("alice", "bob"),  # 개인 이름은 제외됨
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
    )

    result = extract_summary_input(model)

    # group_names는 있지만 participants는 없어야 함
    assert "group_names" in result
    assert "alice" not in str(result)
    assert "bob" not in str(result)


def test_extract_summary_input_by_repo_basic() -> None:
    """extract_summary_input_by_repo가 기본 필드를 추출한다."""
    model = DashboardModel(
        team_name="Test Team",
        report_date=date(2024, 1, 15),
        lookback_hours=24,
        summary_line="요약 줄",
        groups=(),
        new_work=(),
        warnings=(),
        unclassified_ratio=0.1,
        period="daily",
        repos=("org/repo1", "org/repo2"),
    )

    result = extract_summary_input_by_repo(model)

    assert result["team_name"] == "Test Team"
    assert result["report_date"] == "2024-01-15"
    assert result["period"] == "daily"
    assert isinstance(result["repos"], dict)
    assert "org/repo1" in result["repos"]
    assert "org/repo2" in result["repos"]


def test_extract_summary_input_by_repo_filters_by_repo() -> None:
    """extract_summary_input_by_repo가 레포별로 groups/warnings/new_work을 필터링한다."""
    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo1",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        ),
        FeatureGroup(
            name="Feature B",
            source_rule="label",
            evidence="",
            stage="reviewing",
            repo_full_path="org/repo2",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
        ),
    )

    warnings = (
        WarningSignal(
            kind="stale_mr",
            title="PR #1",
            description="",
            days=3,
            web_url="",
            repo_full_path="org/repo1",
        ),
        WarningSignal(
            kind="stale_branch",
            title="PR #2",
            description="",
            days=7,
            web_url="",
            repo_full_path="org/repo2",
        ),
    )

    new_work = (
        NewWorkSignal(
            title="Feature X",
            repo_full_path="org/repo1",
            branch_or_mr="feature-x",
            web_url="",
        ),
        NewWorkSignal(
            title="Feature Y",
            repo_full_path="org/repo2",
            branch_or_mr="feature-y",
            web_url="",
        ),
    )

    model = DashboardModel(
        team_name="Test",
        report_date=date(2024, 1, 1),
        lookback_hours=24,
        summary_line="",
        groups=groups,
        new_work=new_work,
        warnings=warnings,
        unclassified_ratio=0.0,
        repos=("org/repo1", "org/repo2"),
    )

    result = extract_summary_input_by_repo(model)

    # repo1: Feature A 1개, Warning 1개, NewWork 1개
    repo1_data = result["repos"]["org/repo1"]  # type: ignore
    assert repo1_data["group_count"] == 1
    assert repo1_data["group_names"] == ["Feature A"]
    assert repo1_data["warning_count"] == 1
    assert repo1_data["warning_titles"] == ["PR #1"]
    assert repo1_data["new_work_count"] == 1

    # repo2: Feature B 1개, Warning 1개, NewWork 1개
    repo2_data = result["repos"]["org/repo2"]  # type: ignore
    assert repo2_data["group_count"] == 1
    assert repo2_data["group_names"] == ["Feature B"]
    assert repo2_data["warning_count"] == 1
    assert repo2_data["warning_titles"] == ["PR #2"]
    assert repo2_data["new_work_count"] == 1


def test_extract_summary_input_by_repo_no_cross_contamination() -> None:
    """extract_summary_input_by_repo가 레포간 데이터 오염을 방지한다."""
    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo-a",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
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
    )

    result = extract_summary_input_by_repo(model)

    # repo-a: Feature A 1개
    repo_a_data = result["repos"]["org/repo-a"]  # type: ignore
    assert repo_a_data["group_count"] == 1
    assert repo_a_data["group_names"] == ["Feature A"]

    # repo-b: 데이터 없음 (오염되지 않음)
    repo_b_data = result["repos"]["org/repo-b"]  # type: ignore
    assert repo_b_data["group_count"] == 0
    assert repo_b_data["group_names"] == []
    assert repo_b_data["warning_count"] == 0
    assert repo_b_data["new_work_count"] == 0


def test_extract_summary_input_by_repo_includes_commit_and_mr_counts() -> None:
    """extract_summary_input_by_repo가 commit_count와 mr_count를 포함한다."""
    from pulse.models import CommitInfo, MergeRequestInfo

    commits_repo1 = (
        CommitInfo(
            sha="abc123",
            author_name="alice",
            authored_at=date(2024, 1, 1),  # type: ignore
            message="Fix bug",
            branch="main",
            changed_files=("file1.py",),
            web_url="https://example.com/commits/abc123",
        ),
        CommitInfo(
            sha="def456",
            author_name="bob",
            authored_at=date(2024, 1, 1),  # type: ignore
            message="Add feature",
            branch="main",
            changed_files=("file2.py",),
            web_url="https://example.com/commits/def456",
        ),
    )

    mr_repo1 = (
        MergeRequestInfo(
            iid=1,
            title="PR #1",
            state="open",
            is_draft=False,
            labels=(),
            source_branch="feature",
            target_branch="main",
            author_name="alice",
            created_at=date(2024, 1, 1),  # type: ignore
            updated_at=date(2024, 1, 1),  # type: ignore
            merged_at=None,
            reviews=(),
            is_external=False,
            web_url="https://example.com/mr/1",
        ),
        MergeRequestInfo(
            iid=2,
            title="PR #2",
            state="merged",
            is_draft=False,
            labels=(),
            source_branch="hotfix",
            target_branch="main",
            author_name="bob",
            created_at=date(2024, 1, 1),  # type: ignore
            updated_at=date(2024, 1, 1),  # type: ignore
            merged_at=date(2024, 1, 1),  # type: ignore
            reviews=(),
            is_external=False,
            web_url="https://example.com/mr/2",
        ),
    )

    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo1",
            commits=commits_repo1,
            merge_requests=mr_repo1,
            branch_names=(),
            participants=(),
        ),
        FeatureGroup(
            name="Feature B",
            source_rule="label",
            evidence="",
            stage="reviewing",
            repo_full_path="org/repo1",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
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
    )

    result = extract_summary_input_by_repo(model)
    repo1_data = result["repos"]["org/repo1"]  # type: ignore

    # repo1에는 2개 그룹이 있고, 첫 번째 그룹에 2개 커밋과 2개 MR이 있음
    # 두 번째 그룹에는 아무것도 없음
    # 따라서 total: 2 commits, 2 MRs
    assert repo1_data["commit_count"] == 2
    assert repo1_data["mr_count"] == 2


def test_extract_summary_input_by_repo_zero_commits_and_mrs() -> None:
    """extract_summary_input_by_repo가 0개 커밋/MR을 정확히 반영한다."""
    groups = (
        FeatureGroup(
            name="Feature A",
            source_rule="branch",
            evidence="",
            stage="developing",
            repo_full_path="org/repo1",
            commits=(),
            merge_requests=(),
            branch_names=(),
            participants=(),
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
    )

    result = extract_summary_input_by_repo(model)
    repo1_data = result["repos"]["org/repo1"]  # type: ignore

    assert repo1_data["commit_count"] == 0
    assert repo1_data["mr_count"] == 0


def test_build_share_snippet_with_daily_repos() -> None:
    """build_share_snippet이 일간 레포별 요약을 포함한다."""
    summaries = {
        "daily": {
            "org/repo1": "오늘 신규 기능 2개 진행 중",
            "org/repo2": "버그 3개 수정",
        },
        "weekly": {},
    }

    result = build_share_snippet(summaries)

    assert "## Daily Pulse 요약" in result
    assert "### org/repo1" in result
    assert "오늘 신규 기능 2개 진행 중" in result
    assert "### org/repo2" in result
    assert "버그 3개 수정" in result


def test_build_share_snippet_daily_only() -> None:
    """build_share_snippet이 일간 요약만 있을 때 처리한다."""
    summaries = {"daily": {"org/repo": "오늘 요약"}, "weekly": {}}

    result = build_share_snippet(summaries)

    assert "## Daily Pulse 요약" in result
    assert "### org/repo" in result
    assert "오늘 요약" in result


def test_build_share_snippet_empty() -> None:
    """build_share_snippet이 빈 요약을 처리한다."""
    summaries: dict[str, dict[str, str]] = {"daily": {}, "weekly": {}}

    result = build_share_snippet(summaries)

    assert "## Daily Pulse 요약" in result


def test_build_share_snippet_missing_keys() -> None:
    """build_share_snippet이 missing keys를 처리한다."""
    summaries = {"daily": {"org/repo": "일간 요약"}}

    result = build_share_snippet(summaries)

    assert "## Daily Pulse 요약" in result
    assert "### org/repo" in result
    assert "일간 요약" in result


def test_build_share_snippet_whitespace_handling() -> None:
    """build_share_snippet이 앞뒤 공백을 제거한다."""
    summaries = {"daily": {"org/repo": "  일간 요약  "}, "weekly": {}}

    result = build_share_snippet(summaries)

    assert "일간 요약" in result
    assert "  일간 요약" not in result


def test_inject_into_saved_reports_all_files() -> None:
    """_inject_into_saved_reports가 4개 파일(dated + latest, daily/weekly) 모두
    레포별로 치환한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # 4개 파일: latest.html, latest-weekly.html, pulse-DATE.html, pulse-weekly-DATE.html
        repo_slot = ai_summary_slot("org/repo")
        html_template = f"""<!DOCTYPE html>
<html>
<body>
{repo_slot}
<p>Content</p>
</body>
</html>"""

        (output_dir / "latest.html").write_text(html_template, encoding="utf-8")
        (output_dir / "latest-weekly.html").write_text(html_template, encoding="utf-8")
        (output_dir / "pulse-2024-01-15.html").write_text(html_template, encoding="utf-8")
        (output_dir / "pulse-weekly-2024-01-15.html").write_text(html_template, encoding="utf-8")

        summaries = {
            "daily": {"org/repo": "일간 요약 텍스트"},
            "weekly": {"org/repo": "주간 요약 텍스트"},
        }
        _inject_into_saved_reports(output_dir, summaries)

        # 모든 파일에서 슬롯이 사라졌는지 확인
        latest = (output_dir / "latest.html").read_text(encoding="utf-8")
        assert repo_slot not in latest
        assert "일간 요약 텍스트" in latest

        latest_weekly = (output_dir / "latest-weekly.html").read_text(encoding="utf-8")
        assert repo_slot not in latest_weekly
        assert "주간 요약 텍스트" in latest_weekly

        pulse_dated = (output_dir / "pulse-2024-01-15.html").read_text(encoding="utf-8")
        assert repo_slot not in pulse_dated
        assert "일간 요약 텍스트" in pulse_dated

        pulse_weekly_dated = (output_dir / "pulse-weekly-2024-01-15.html").read_text(
            encoding="utf-8"
        )
        assert repo_slot not in pulse_weekly_dated
        assert "주간 요약 텍스트" in pulse_weekly_dated


def test_inject_into_saved_reports_pollution_prevention() -> None:
    """_inject_into_saved_reports가 daily/weekly 파일과 레포별 요약을 올바르게 분리하여 주입한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        slot_a = ai_summary_slot("org/repo-a")
        slot_b = ai_summary_slot("org/repo-b")
        html_template = f"""<!DOCTYPE html>
<html>
<body>
{slot_a}
{slot_b}
<p>Content</p>
</body>
</html>"""

        # daily 파일: latest.html, pulse-2024-01-15.html
        # weekly 파일: latest-weekly.html, pulse-weekly-2024-01-15.html
        (output_dir / "latest.html").write_text(html_template, encoding="utf-8")
        (output_dir / "pulse-2024-01-15.html").write_text(html_template, encoding="utf-8")
        (output_dir / "latest-weekly.html").write_text(html_template, encoding="utf-8")
        (output_dir / "pulse-weekly-2024-01-15.html").write_text(html_template, encoding="utf-8")

        summaries = {
            "daily": {
                "org/repo-a": "DAILY_UNIQUE_TEXT_A",
                "org/repo-b": "DAILY_UNIQUE_TEXT_B",
            },
            "weekly": {
                "org/repo-a": "WEEKLY_UNIQUE_TEXT_A",
                "org/repo-b": "WEEKLY_UNIQUE_TEXT_B",
            },
        }
        _inject_into_saved_reports(output_dir, summaries)

        # daily 파일에는 daily 요약만, 레포별 분리
        latest = (output_dir / "latest.html").read_text(encoding="utf-8")
        assert "DAILY_UNIQUE_TEXT_A" in latest
        assert "DAILY_UNIQUE_TEXT_B" in latest
        assert "WEEKLY_UNIQUE_TEXT_A" not in latest
        assert "WEEKLY_UNIQUE_TEXT_B" not in latest

        pulse_dated = (output_dir / "pulse-2024-01-15.html").read_text(encoding="utf-8")
        assert "DAILY_UNIQUE_TEXT_A" in pulse_dated
        assert "DAILY_UNIQUE_TEXT_B" in pulse_dated
        assert "WEEKLY_UNIQUE_TEXT_A" not in pulse_dated
        assert "WEEKLY_UNIQUE_TEXT_B" not in pulse_dated

        # weekly 파일에는 weekly 요약만, 레포별 분리
        latest_weekly = (output_dir / "latest-weekly.html").read_text(encoding="utf-8")
        assert "WEEKLY_UNIQUE_TEXT_A" in latest_weekly
        assert "WEEKLY_UNIQUE_TEXT_B" in latest_weekly
        assert "DAILY_UNIQUE_TEXT_A" not in latest_weekly
        assert "DAILY_UNIQUE_TEXT_B" not in latest_weekly

        pulse_weekly_dated = (output_dir / "pulse-weekly-2024-01-15.html").read_text(
            encoding="utf-8"
        )
        assert "WEEKLY_UNIQUE_TEXT_A" in pulse_weekly_dated
        assert "WEEKLY_UNIQUE_TEXT_B" in pulse_weekly_dated
        assert "DAILY_UNIQUE_TEXT_A" not in pulse_weekly_dated
        assert "DAILY_UNIQUE_TEXT_B" not in pulse_weekly_dated


def test_inject_into_saved_reports_missing_file() -> None:
    """_inject_into_saved_reports가 존재하지 않는 파일을 예외 없이 스킵한다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        repo_slot = ai_summary_slot("org/repo")
        html_template = f"""<!DOCTYPE html>
<body>{repo_slot}<p>Content</p></body>
</html>"""

        # 하나의 파일만 생성
        (output_dir / "latest.html").write_text(html_template, encoding="utf-8")

        summaries = {"daily": {"org/repo": "요약"}, "weekly": {"org/repo": "주간 요약"}}

        # 이 함수는 예외를 발생시키지 않아야 함 (missing file은 그냥 스킵)
        _inject_into_saved_reports(output_dir, summaries)

        # 존재하는 파일은 정상 처리됨
        latest = (output_dir / "latest.html").read_text(encoding="utf-8")
        assert repo_slot not in latest
        assert "요약" in latest


def test_inject_into_saved_reports_no_slot() -> None:
    """_inject_into_saved_reports가 슬롯이 없는 파일(이미 주입됨)을 재주입하지 않는다."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        html_without_slot = """<!DOCTYPE html>
<body><p>Already has summary</p></body>
</html>"""

        (output_dir / "latest.html").write_text(html_without_slot, encoding="utf-8")

        summaries = {"daily": {"org/repo": "새로운 요약"}, "weekly": {"org/repo": "주간 요약"}}
        _inject_into_saved_reports(output_dir, summaries)

        # 슬롯이 없으므로 재주입되지 않음, 원본 내용 유지
        latest = (output_dir / "latest.html").read_text(encoding="utf-8")
        assert "Already has summary" in latest
        assert "새로운 요약" not in latest
