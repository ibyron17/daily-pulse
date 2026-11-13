"""브랜치 히스토리 저장소 테스트."""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pulse.branch_history import (
    SCHEMA_VERSION,
    BranchHistoryEntry,
    BranchHistoryStore,
    build_entry,
    build_history_view,
    entries_as_dict,
    history_key,
    load_store,
    needs_refresh,
    save_store,
    store_path,
    update_store,
)
from pulse.models import BranchHistoryFetch, HistoryCommit

RUN_DATE = date(2026, 7, 27)


def make_fetch(
    *,
    branch: str = "feature/x",
    head_sha: str = "head1",
    commits: tuple[tuple[str, str], ...] = (),
    total_commits: int | None = None,
    truncated: bool = False,
    behind_count: int | None = None,
    base_branch: str = "develop",
) -> BranchHistoryFetch:
    """(ISO 날짜, 제목) 쌍으로 조회 결과를 만든다."""
    history_commits = tuple(
        HistoryCommit(
            sha=f"sha{index}",
            worked_at=datetime.fromisoformat(f"{day}T12:00:00+00:00"),
            title=title,
        )
        for index, (day, title) in enumerate(commits)
    )
    return BranchHistoryFetch(
        branch_name=branch,
        base_branch=base_branch,
        merge_base_sha="base1",
        head_sha=head_sha,
        commits=history_commits,
        total_commits=total_commits if total_commits is not None else len(history_commits),
        truncated=truncated,
        behind_count=behind_count,
    )


class TestNeedsRefresh:
    def test_missing_entry_needs_refresh(self) -> None:
        assert needs_refresh(None, "abc") is True

    def test_same_head_skips_refresh(self) -> None:
        entry = build_entry(None, make_fetch(head_sha="abc"), RUN_DATE)
        assert needs_refresh(entry, "abc") is False

    def test_changed_head_needs_refresh(self) -> None:
        entry = build_entry(None, make_fetch(head_sha="abc"), RUN_DATE)
        assert needs_refresh(entry, "def") is True


class TestBuildEntry:
    def test_aggregates_dates_and_tags(self) -> None:
        fetch = make_fetch(
            commits=(
                ("2026-05-27", "[feat] 시작"),
                ("2026-05-27", "[feat] 이어서"),
                ("2026-06-10", "[fix] 수정"),
            )
        )
        entry = build_entry(None, fetch, RUN_DATE)
        assert entry.first_commit_on == "2026-05-27"
        assert entry.date_commit_counts == (("2026-05-27", 2), ("2026-06-10", 1))
        assert entry.tag_counts == (("feat", 2), ("fix", 1))
        assert entry.tag_recognized == 3
        assert entry.tag_total == 3
        assert entry.updated_on == "2026-07-27"

    def test_extracts_issue_keys_in_order(self) -> None:
        fetch = make_fetch(
            commits=(
                ("2026-07-20", "[feat] DOCS-4812 작업"),
                ("2026-07-21", "[fix] DOCS-4812 보정"),
                ("2026-07-22", "[feat] B20C-45 추가"),
            )
        )
        entry = build_entry(None, fetch, RUN_DATE)
        assert entry.issue_keys == ("DOCS-4812", "B20C-45")

    def test_same_day_recollect_overwrites_without_double_counting(self) -> None:
        first = build_entry(None, make_fetch(commits=(("2026-07-20", "[feat] a"),)), RUN_DATE)
        # 같은 날짜를 다시 조회 — 카운트가 누적되면 안 된다
        second = build_entry(
            first,
            make_fetch(
                head_sha="head2",
                commits=(("2026-07-20", "[feat] a"), ("2026-07-20", "[feat] b")),
            ),
            RUN_DATE,
        )
        assert dict(second.date_commit_counts)["2026-07-20"] == 2

    def test_truncated_fetch_preserves_earlier_dates(self) -> None:
        """상한으로 절단된 조회가 과거 활동일을 지우지 않아야 한다."""
        earlier = build_entry(None, make_fetch(commits=(("2026-05-27", "[feat] 시작"),)), RUN_DATE)
        truncated = build_entry(
            earlier,
            make_fetch(
                head_sha="head2",
                commits=(("2026-07-27", "[fix] 최근"),),
                total_commits=1500,
                truncated=True,
            ),
            RUN_DATE,
        )
        assert truncated.first_commit_on == "2026-05-27"
        assert truncated.truncated is True
        assert truncated.total_commits == 1500

    def test_complete_refetch_replaces_stale_dates(self) -> None:
        """완전한 재조회는 이전 집계의 날짜를 유령으로 남기지 않아야 한다.

        커밋 날짜가 다시 쓰이면(리베이스) 이전 fetch의 날짜는 존재하지 않는
        커밋의 기록이다 — 병합하면 같은 커밋이 두 날짜로 이중 집계된다.
        """
        before_rebase = build_entry(
            None,
            make_fetch(commits=(("2026-07-24", "[feat] a"), ("2026-07-24", "[feat] b"))),
            RUN_DATE,
        )
        after_rebase = build_entry(
            before_rebase,
            make_fetch(
                head_sha="head2",
                commits=(("2026-07-29", "[feat] a"), ("2026-07-29", "[feat] b")),
            ),
            RUN_DATE,
        )
        assert after_rebase.date_commit_counts == (("2026-07-29", 2),)
        assert after_rebase.first_commit_on == "2026-07-29"

    def test_empty_fetch_falls_back_to_run_date(self) -> None:
        entry = build_entry(None, make_fetch(commits=()), RUN_DATE)
        assert entry.first_commit_on == "2026-07-27"


class TestUpdateStore:
    def test_adds_and_replaces_entries(self) -> None:
        store = BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc))
        updated = update_store(
            store,
            "org/repo",
            (make_fetch(branch="feature/a", commits=(("2026-07-20", "[feat] a"),)),),
            RUN_DATE,
        )
        key = history_key("org/repo", "feature/a")
        assert key in entries_as_dict(updated)

        again = update_store(
            updated,
            "org/repo",
            (
                make_fetch(
                    branch="feature/a",
                    head_sha="head2",
                    commits=(("2026-07-21", "[fix] b"),),
                ),
            ),
            RUN_DATE,
        )
        entry = entries_as_dict(again)[key]
        assert entry.last_sha == "head2"
        # 완전한 재조회는 교체 — 이전 날짜(07-20)는 남지 않는다
        assert dict(entry.date_commit_counts) == {"2026-07-21": 1}

    def test_keys_are_sorted(self) -> None:
        store = BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc))
        updated = update_store(
            store,
            "org/repo",
            (make_fetch(branch="zeta"), make_fetch(branch="alpha")),
            RUN_DATE,
        )
        keys = [key for key, _ in updated.entries]
        assert keys == sorted(keys)


class TestBuildHistoryView:
    def test_reports_real_start_not_observation_date(self) -> None:
        entry = build_entry(
            None,
            make_fetch(
                commits=(("2026-05-27", "[feat] 시작"), ("2026-07-27", "[fix] 최근")),
                behind_count=90,
            ),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.started_on == "2026-05-27"
        assert view.total_days == 62  # 5/27 ~ 7/27 포함
        assert view.active_days == 2
        assert view.behind_count == 90
        assert view.base_branch == "develop"

    def test_week_counts_are_summed_per_week(self) -> None:
        entry = build_entry(
            None,
            make_fetch(
                commits=(
                    ("2026-07-20", "[feat] a"),
                    ("2026-07-22", "[feat] b"),
                    ("2026-07-27", "[feat] c"),
                )
            ),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.week_commit_counts == (("2026-07-20", 2), ("2026-07-27", 1))

    def test_longest_silent_gap(self) -> None:
        entry = build_entry(
            None,
            make_fetch(commits=(("2026-06-01", "[feat] a"), ("2026-06-11", "[feat] b"))),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.silent_gap_days == 9

    def test_single_active_day_has_no_gap(self) -> None:
        entry = build_entry(None, make_fetch(commits=(("2026-07-20", "[feat] a"),)), RUN_DATE)
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.silent_gap_days == 0

    def test_tags_hidden_when_coverage_below_threshold(self) -> None:
        entry = build_entry(
            None,
            make_fetch(
                commits=(
                    ("2026-07-20", "[feat] a"),
                    ("2026-07-20", "자유 서술 b"),
                    ("2026-07-20", "자유 서술 c"),
                    ("2026-07-20", "자유 서술 d"),
                )
            ),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.tags is None

    def test_tags_shown_when_coverage_meets_threshold(self) -> None:
        entry = build_entry(
            None,
            make_fetch(commits=(("2026-07-20", "[feat] a"), ("2026-07-20", "자유 b"))),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.tags is not None
        assert view.tags.coverage == 0.5


class TestPrehistoryTrimming:
    """체리픽 등으로 딸려 온 옛 커밋이 시작일을 부풀리지 않아야 한다.

    실측: 1년 전 authored 커밋 2건이 섞인 브랜치가 "399일차 · 공백 363일"로 표시됐다.
    본편(커밋의 75% 이상)과 30일 넘게 끊긴 소수 선행 구간은 전사로 보고 잘라낸다.
    """

    def test_year_old_stray_commits_are_excluded_from_start(self) -> None:
        entry = build_entry(
            None,
            make_fetch(
                commits=(
                    ("2025-06-27", "[feat] 승계 a"),
                    ("2025-06-27", "[feat] 승계 b"),
                    ("2026-06-26", "[feat] 준비"),
                    ("2026-07-07", "[feat] 시작"),
                    ("2026-07-08", "[feat] c"),
                    ("2026-07-08", "[feat] d"),
                    ("2026-07-08", "[feat] e"),
                    ("2026-07-08", "[feat] f"),
                    ("2026-07-13", "[feat] g"),
                    ("2026-07-24", "[feat] h"),
                )
            ),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        # 1년 전 2건(20%)은 잘리고, 11일 간격의 06-26(30일 이내)은 본편에 남는다
        assert view.started_on == "2026-06-26"
        assert view.total_days == 32  # 6/26 ~ 7/27 포함
        assert view.active_days == 5
        # 주별 추이에도 2025년 막대가 없다
        assert all(week >= "2026-06-22" for week, _ in view.week_commit_counts)
        # 저장 집계는 원본 그대로다 (뷰만 자른다)
        assert entry.first_commit_on == "2025-06-27"
        # 브랜치 고유 커밋 총수는 전사를 포함한다
        assert view.total_commits == 10

    def test_midlife_pause_is_not_trimmed(self) -> None:
        """작업의 25% 이상이 이뤄진 뒤의 긴 휴지기는 본편의 일부다."""
        entry = build_entry(
            None,
            make_fetch(
                commits=(
                    ("2026-04-01", "[feat] a"),
                    ("2026-04-02", "[feat] b"),
                    ("2026-06-01", "[feat] c"),  # 60일 휴지 후 재개
                    ("2026-06-02", "[feat] d"),
                )
            ),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.started_on == "2026-04-01"
        assert view.active_days == 4

    def test_contiguous_history_is_untouched(self) -> None:
        entry = build_entry(
            None,
            make_fetch(commits=(("2026-07-07", "[feat] a"), ("2026-07-20", "[feat] b"))),
            RUN_DATE,
        )
        view = build_history_view(entry, RUN_DATE, min_tag_coverage=0.5)
        assert view.started_on == "2026-07-07"


class TestPersistence:
    def test_round_trip(self) -> None:
        store = update_store(
            BranchHistoryStore(schema_version=1, updated_at=datetime.now(timezone.utc)),
            "org/repo",
            (
                make_fetch(
                    commits=(("2026-05-27", "[feat] DOCS-1 시작"),),
                    behind_count=7,
                    truncated=True,
                    total_commits=2000,
                ),
            ),
            RUN_DATE,
        )
        with TemporaryDirectory() as tmp:
            path = store_path(Path(tmp))
            save_store(store, path)
            loaded = load_store(path)

        original = entries_as_dict(store)
        restored = entries_as_dict(loaded)
        assert restored == original

    def test_missing_file_yields_empty_store(self) -> None:
        with TemporaryDirectory() as tmp:
            assert load_store(store_path(Path(tmp))).entries == ()

    def test_corrupt_json_yields_empty_store(self, caplog: object) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "branches.json"
            path.write_text("{not json", encoding="utf-8")
            with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
                assert load_store(path).entries == ()

    def test_unsupported_schema_yields_empty_store(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "branches.json"
            path.write_text(json.dumps({"schema_version": 99, "entries": {}}), encoding="utf-8")
            assert load_store(path).entries == ()

    def test_malformed_entry_is_skipped_others_kept(self) -> None:
        good = BranchHistoryEntry(
            base_branch="develop",
            merge_base_sha="b1",
            first_commit_on="2026-05-27",
            last_sha="h1",
            total_commits=3,
            truncated=False,
            date_commit_counts=(("2026-05-27", 3),),
            tag_counts=(("feat", 3),),
            tag_recognized=3,
            tag_total=3,
            week_fix_ratios=(("2026-05-25", 0, 3),),
            issue_keys=(),
            behind_count=None,
            updated_on="2026-07-27",
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "branches.json"
            save_store(
                BranchHistoryStore(
                    schema_version=SCHEMA_VERSION,
                    updated_at=datetime.now(timezone.utc),
                    entries=(("org/repo::good", good),),
                ),
                path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entries"]["org/repo::bad"] = {"base_branch": "develop"}  # 필수 키 누락
            path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = entries_as_dict(load_store(path))

        assert "org/repo::good" in loaded
        assert "org/repo::bad" not in loaded
