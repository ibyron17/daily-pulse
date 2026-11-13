"""cached 플래그 재평가 테스트."""

import tempfile
from pathlib import Path
from typing import Any

from pulse.analysis_cache import evaluate_cached_status, save_analysis_cache


def test_evaluate_cached_status_existing_cache() -> None:
    """분석 캐시에 존재하는 그룹은 cached=true로 설정된다."""
    # 캐시 설정
    cache_data = {
        "org/repo::feature@weekly": {
            "seed_fingerprint": "abc123",
            "title": "Feature Title",
            "analysis": "Feature Analysis",
        }
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        cache_path = data_dir / "analysis" / "cache.json"

        # 캐시 저장
        save_analysis_cache(cache_data, cache_path)

        # 테스트할 주간 섹션
        weekly_section: dict[str, Any] = {
            "report_date": "2026-07-28",
            "groups": {
                "org/repo::feature": {
                    "name": "feature",
                    "repo_full_path": "org/repo",
                    "stage": "reviewing",
                    "cached": False,
                    "cached_title": None,
                    "cached_analysis": None,
                }
            },
        }

        # 재평가 (실제로는 load_analysis_cache를 호출해야 함)
        # 여기서는 직접 캐시를 로드해서 테스트
        from pulse.analysis_cache import load_analysis_cache

        loaded_cache = load_analysis_cache(cache_path)
        evaluate_cached_status(weekly_section, loaded_cache)

        groups = weekly_section["groups"]
        assert isinstance(groups, dict)
        group = groups["org/repo::feature"]
        assert group["cached"] is True
        assert group["cached_title"] == "Feature Title"
        assert group["cached_analysis"] == "Feature Analysis"


def test_evaluate_cached_status_missing_cache() -> None:
    """분석 캐시에 없는 그룹은 cached=false로 설정된다."""
    weekly_section: dict[str, Any] = {
        "report_date": "2026-07-28",
        "groups": {
            "org/repo::feature": {
                "name": "feature",
                "repo_full_path": "org/repo",
                "stage": "reviewing",
                "cached": True,  # 초기값이 True일 수도 있음
                "cached_title": "Old Title",
                "cached_analysis": "Old Analysis",
            }
        },
    }

    # 재평가 (빈 캐시)
    evaluate_cached_status(weekly_section, {})

    groups = weekly_section["groups"]
    assert isinstance(groups, dict)
    group = groups["org/repo::feature"]
    assert group["cached"] is False
    assert group["cached_title"] is None
    assert group["cached_analysis"] is None


def test_evaluate_cached_status_empty_groups() -> None:
    """빈 groups dict는 안전하게 처리된다."""
    weekly_section = {
        "report_date": "2026-07-28",
        "groups": {},
    }

    evaluate_cached_status(weekly_section, {})

    assert weekly_section["groups"] == {}


def test_evaluate_cached_status_multiple_groups() -> None:
    """여러 그룹이 올바르게 처리된다."""
    cache_data = {
        "org/repo1::feature1@weekly": {
            "seed_fingerprint": "abc123",
            "title": "Feature 1",
            "analysis": "Analysis 1",
        }
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        cache_path = data_dir / "analysis" / "cache.json"

        save_analysis_cache(cache_data, cache_path)

        from pulse.analysis_cache import load_analysis_cache

        loaded_cache = load_analysis_cache(cache_path)

        weekly_section = {
            "report_date": "2026-07-28",
            "groups": {
                "org/repo1::feature1": {
                    "name": "feature1",
                    "repo_full_path": "org/repo1",
                    "stage": "reviewing",
                    "cached": False,
                    "cached_title": None,
                    "cached_analysis": None,
                },
                "org/repo2::feature2": {
                    "name": "feature2",
                    "repo_full_path": "org/repo2",
                    "stage": "merged",
                    "cached": True,
                    "cached_title": "Old",
                    "cached_analysis": "Old",
                },
            },
        }

        evaluate_cached_status(weekly_section, loaded_cache)

        groups = weekly_section["groups"]
        assert isinstance(groups, dict)

        # feature1은 캐시 있음
        feature1 = groups["org/repo1::feature1"]
        assert feature1["cached"] is True
        assert feature1["cached_title"] == "Feature 1"

        # feature2는 캐시 없음
        feature2 = groups["org/repo2::feature2"]
        assert feature2["cached"] is False
        assert feature2["cached_title"] is None


def test_evaluate_cached_status_no_cache_param() -> None:
    """캐시 파라미터가 None이면 안전하게 처리된다."""
    weekly_section: dict[str, Any] = {
        "report_date": "2026-07-28",
        "groups": {
            "org/repo::feature": {
                "name": "feature",
                "repo_full_path": "org/repo",
                "stage": "reviewing",
                "cached": True,
                "cached_title": "Old",
                "cached_analysis": "Old",
            }
        },
    }

    evaluate_cached_status(weekly_section, None)

    groups = weekly_section["groups"]
    assert isinstance(groups, dict)
    group = groups["org/repo::feature"]
    assert group["cached"] is False
    assert group["cached_title"] is None
