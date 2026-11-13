"""daily_pulse 진입점의 exit code 정책 E2E 테스트.

PRD 계약: 성공/일부 실패 = 0 (대시보드에 실패 표시), 전 레포 실패·토큰 미설정 = 1,
config 오류 = 2.
"""

from pathlib import Path

import pytest

import daily_pulse
from pulse.models import RepoActivity
from tests.conftest import make_repo_activity, make_repo_ref

EXIT_SUCCESS = 0
EXIT_PIPELINE_ERROR = 1
EXIT_CONFIG_ERROR = 2


def _write_config(tmp_path: Path, repos: list[str] | None = None) -> Path:
    """tmp_path 안에서만 동작하는 최소 config.yaml을 생성한다."""
    if repos is None:
        repos = ["test/repo"]
    config_file = tmp_path / "config.yaml"
    repos_yaml = "\n  ".join(f"- {repo}" for repo in repos)
    config_file.write_text(
        f"""
team_name: "테스트팀"
gitlab_url: "http://test.example"
repos:
  {repos_yaml}
output_dir: "{tmp_path / "reports"}"
data_dir: "{tmp_path / "data"}"
""",
        encoding="utf-8",
    )
    return config_file


def _run_main(monkeypatch: pytest.MonkeyPatch, config_file: Path) -> int:
    """--config 인자로 main()을 실행하고 exit code를 반환한다."""
    monkeypatch.setattr("sys.argv", ["daily_pulse", "--config", str(config_file)])
    return daily_pulse.main()


def _patch_collect(monkeypatch: pytest.MonkeyPatch, activities: list[RepoActivity]) -> None:
    """pipeline이 사용하는 collect_repos를 고정 결과로 대체한다."""
    monkeypatch.setattr(
        "pulse.pipeline.collect_repos",
        lambda config, now=None, save_snapshots=True: activities,
    )


def test_main_returns_zero_on_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """일부 레포 실패 시 exit 0이고, 대시보드에 수집 실패가 표시된다."""
    # Arrange
    config_file = _write_config(tmp_path)
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    ok_activity = make_repo_activity()
    failed_activity = make_repo_activity(
        repo=make_repo_ref(namespace="test", name="broken-repo"),
        status="failed",
        failure_reason="접근 권한 없음",
        commits=(),
        active_branches=(),
        merge_requests=(),
    )
    _patch_collect(monkeypatch, [ok_activity, failed_activity])

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_SUCCESS
    latest_html = (tmp_path / "reports" / "latest.html").read_text(encoding="utf-8")
    assert "수집 실패" in latest_html
    assert "broken-repo" in latest_html


def test_main_returns_one_when_all_repos_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """전 레포 실패 시 exit 1 (PRD: 전체 실패만 비 0)."""
    # Arrange
    config_file = _write_config(tmp_path)
    monkeypatch.setenv("GITLAB_TOKEN", "test-token")
    failed = make_repo_activity(
        status="failed",
        failure_reason="서버 오류",
        commits=(),
        active_branches=(),
        merge_requests=(),
    )
    _patch_collect(monkeypatch, [failed])

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_PIPELINE_ERROR


def test_main_returns_one_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GITLAB_TOKEN 미설정 시 파이프라인 실행 전에 exit 1."""
    # Arrange
    config_file = _write_config(tmp_path)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_PIPELINE_ERROR


def test_main_returns_two_on_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """config 파일 부재 시 exit 2."""
    # Act
    exit_code = _run_main(monkeypatch, tmp_path / "nonexistent.yaml")

    # Assert
    assert exit_code == EXIT_CONFIG_ERROR


def test_main_github_repo_requires_github_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub 레포만 있을 때 GITHUB_TOKEN 미설정 시 exit 1."""
    # Arrange
    config_file = _write_config(tmp_path, ["https://github.com/torvalds/linux"])
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_PIPELINE_ERROR


def test_main_github_repo_with_github_token_passes_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub 레포만 있을 때 GITHUB_TOKEN 설정되면 검증 통과 (파이프라인은 mock)."""
    # Arrange
    config_file = _write_config(tmp_path, ["https://github.com/torvalds/linux"])
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    ok_activity = make_repo_activity(repo=make_repo_ref(provider="github"))
    _patch_collect(monkeypatch, [ok_activity])

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_SUCCESS


def test_main_mixed_repos_requires_both_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitLab과 GitHub 혼합 시 둘 다 필요."""
    # Arrange
    config_file = _write_config(
        tmp_path,
        ["test/repo", "https://github.com/torvalds/linux"],
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_PIPELINE_ERROR


def test_main_mixed_repos_with_both_tokens_passes_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitLab과 GitHub 혼합 시 둘 다 설정되면 검증 통과."""
    # Arrange
    config_file = _write_config(
        tmp_path,
        ["test/repo", "https://github.com/torvalds/linux"],
    )
    monkeypatch.setenv("GITLAB_TOKEN", "test-gitlab-token")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    gitlab_activity = make_repo_activity(repo=make_repo_ref(provider="gitlab"))
    github_activity = make_repo_activity(repo=make_repo_ref(provider="github"))
    _patch_collect(monkeypatch, [gitlab_activity, github_activity])

    # Act
    exit_code = _run_main(monkeypatch, config_file)

    # Assert
    assert exit_code == EXIT_SUCCESS
