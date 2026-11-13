"""그룹 분석 캐시 로드/저장·지문 계산 테스트."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pulse.analysis_cache import (
    compute_group_seed_fingerprint,
    load_analysis_cache,
    load_pending,
    save_analysis_cache,
    save_pending,
)
from pulse.models import CommitInfo, FeatureGroup, TaskSummary


@pytest.fixture
def sample_group() -> FeatureGroup:
    """테스트 그룹 생성."""
    task_summary = TaskSummary(
        commit_titles=("feat: add auth", "fix: redirect"),
        active_branch_names=("feature/oauth",),
        open_mr_titles=("OAuth implementation",),
    )
    return FeatureGroup(
        name="feature/oauth",
        source_rule="branch",
        evidence="feature/oauth branch exists",
        stage="developing",
        repo_full_path="org/auth",
        commits=(),
        merge_requests=(),
        branch_names=("feature/oauth",),
        participants=(),
        task_summary=task_summary,
    )


def test_compute_seed_fingerprint_consistency(sample_group: FeatureGroup) -> None:
    """같은 그룹의 지문은 일관성 있게 계산된다."""
    fp1 = compute_group_seed_fingerprint(sample_group)
    fp2 = compute_group_seed_fingerprint(sample_group)
    assert fp1 == fp2
    assert len(fp1) == 16  # SHA-256의 첫 16자


def test_compute_seed_fingerprint_changes_on_title_change(sample_group: FeatureGroup) -> None:
    """커밋 제목이 변경되면 지문이 변경된다."""
    fp1 = compute_group_seed_fingerprint(sample_group)

    # 커밋 제목 변경
    modified_group = FeatureGroup(
        name=sample_group.name,
        source_rule=sample_group.source_rule,
        evidence=sample_group.evidence,
        stage=sample_group.stage,
        repo_full_path=sample_group.repo_full_path,
        commits=sample_group.commits,
        merge_requests=sample_group.merge_requests,
        branch_names=sample_group.branch_names,
        participants=sample_group.participants,
        task_summary=TaskSummary(
            commit_titles=("feat: add auth", "fix: different"),
            active_branch_names=sample_group.task_summary.active_branch_names,
            open_mr_titles=sample_group.task_summary.open_mr_titles,
        ),
    )
    fp2 = compute_group_seed_fingerprint(modified_group)
    assert fp1 != fp2


def test_load_empty_cache(tmp_path: Path) -> None:
    """존재하지 않는 캐시 파일은 빈 dict를 반환한다."""
    cache_path = tmp_path / "cache.json"
    cache = load_analysis_cache(cache_path)
    assert cache == {}


def test_save_and_load_cache(tmp_path: Path) -> None:
    """캐시를 저장하고 로드하는 round-trip."""
    cache_path = tmp_path / "cache.json"
    original = {
        "org/auth::feature/oauth@daily": {
            "period": "daily",
            "seed_fingerprint": "abc123def456",
            "title": "OAuth 통합",
            "analysis": "분석 내용",
            "cached_at": "2026-07-22T10:00:00+09:00",
        },
    }

    save_analysis_cache(original, cache_path)
    assert cache_path.exists()

    loaded = load_analysis_cache(cache_path)
    assert loaded == original


def test_save_cache_creates_directory(tmp_path: Path) -> None:
    """캐시 저장 시 디렉토리가 없으면 생성한다."""
    cache_path = tmp_path / "deep" / "nested" / "cache.json"
    cache_data = {"test": "data"}

    save_analysis_cache(cache_data, cache_path)
    assert cache_path.exists()
    assert cache_path.parent.exists()


def test_load_pending_empty(tmp_path: Path) -> None:
    """존재하지 않는 pending 파일은 빈 dict를 반환한다."""
    pending_path = tmp_path / "pending.json"
    pending = load_pending(pending_path)
    assert pending == {}


def test_save_and_load_pending(tmp_path: Path) -> None:
    """pending을 저장하고 로드하는 round-trip."""
    pending_path = tmp_path / "pending.json"
    original = {
        "report_date": "2026-07-22",
        "daily": {
            "org/auth::feature/oauth": "abc123def456",
            "org/auth::feature/mfa": "xyz789uv0123",
        },
        "weekly": {
            "org/auth::feature/oauth": "xyzabc123456",
        },
    }

    save_pending(original, pending_path)
    assert pending_path.exists()

    loaded = load_pending(pending_path)
    assert loaded == original


def test_save_pending_creates_directory(tmp_path: Path) -> None:
    """pending 저장 시 디렉토리가 없으면 생성한다."""
    pending_path = tmp_path / "data" / "analysis" / "pending.json"
    pending_data = {"report_date": "2026-07-22", "daily": {}}

    save_pending(pending_data, pending_path)
    assert pending_path.exists()
    assert pending_path.parent.exists()


def test_cache_hit_detection(tmp_path: Path, sample_group: FeatureGroup) -> None:
    """캐시 지문 일치 판정."""
    fp = compute_group_seed_fingerprint(sample_group)
    cache_key = "org/auth::feature/oauth@daily"

    cache = {
        cache_key: {
            "seed_fingerprint": fp,
            "title": "OAuth 통합",
            "analysis": "캐시된 분석",
        },
    }

    # 지문 일치 → 캐시 히트
    entry = cache.get(cache_key)
    assert entry is not None
    assert entry.get("seed_fingerprint") == fp


def test_cache_miss_detection(tmp_path: Path, sample_group: FeatureGroup) -> None:
    """캐시 지문 불일치 판정."""
    fp1 = compute_group_seed_fingerprint(sample_group)
    fp2 = "different_fingerprint_"

    cache_key = "org/auth::feature/oauth@daily"
    cache = {
        cache_key: {
            "seed_fingerprint": fp2,
            "title": "OAuth 통합",
            "analysis": "캐시된 분석",
        },
    }

    # 지문 불일치 → 캐시 미스
    entry = cache.get(cache_key)
    assert entry is not None
    assert entry.get("seed_fingerprint") != fp1


def _commit_with_diff_summary(changed_files_summary: str | None) -> CommitInfo:
    """지문 안정성 검증용 커밋 생성 (발췌만 다르게)."""
    return CommitInfo(
        sha="abc123",
        author_name="alice",
        authored_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        message="feat: add auth",
        branch="feature/oauth",
        changed_files=("auth.py",),
        web_url="",
        changed_files_summary=changed_files_summary,
    )


def test_fingerprint_unchanged_when_only_diff_summary_differs(
    sample_group: FeatureGroup,
) -> None:
    """changed_files_summary만 달라도 지문이 동일하다 → 캐시 히트 유지 (PRP 결정 2)."""
    group_a = replace(sample_group, commits=(_commit_with_diff_summary("auth.py (+1/-0)"),))
    group_b = replace(
        sample_group,
        commits=(_commit_with_diff_summary("auth.py (+99/-9) @@ def refactored"),),
    )

    assert compute_group_seed_fingerprint(group_a) == compute_group_seed_fingerprint(group_b)


def test_fingerprint_unchanged_when_diff_summary_added(
    sample_group: FeatureGroup,
) -> None:
    """구 캐시(발췌 없던 시절)와 새 seed(발췌 추가)의 지문이 동일하다 → 업그레이드 후 캐시 유지."""
    group_without = replace(sample_group, commits=(_commit_with_diff_summary(None),))
    group_with = replace(sample_group, commits=(_commit_with_diff_summary("auth.py (+1/-0)"),))

    assert compute_group_seed_fingerprint(group_without) == compute_group_seed_fingerprint(
        group_with
    )
