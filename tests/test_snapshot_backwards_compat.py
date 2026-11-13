"""스냅샷 하위호환성 테스트 — changed_files_summary 필드 부재 처리."""

from pulse.models import _commit_from_dict


class TestCommitFromDictBackwardsCompat:
    """_commit_from_dict의 하위호환성 검증."""

    def test_old_snapshot_without_changed_files_summary(self) -> None:
        """기존 스냅샷(changed_files_summary 없음) 로드."""
        old_data = {
            "sha": "abc123",
            "author_name": "Alice",
            "authored_at": "2026-07-22T10:00:00+09:00",
            "message": "feat: add feature",
            "branch": "main",
            "changed_files": ("path/a.py", "path/b.py"),
            "web_url": "http://example.com/commit/abc123",
            # changed_files_summary는 없음!
        }
        commit = _commit_from_dict(old_data)
        assert commit.sha == "abc123"
        assert commit.changed_files == ("path/a.py", "path/b.py")
        assert commit.changed_files_summary is None

    def test_new_snapshot_with_changed_files_summary(self) -> None:
        """신규 스냅샷(changed_files_summary 포함) 로드."""
        new_data = {
            "sha": "def456",
            "author_name": "Bob",
            "authored_at": "2026-07-22T11:00:00+09:00",
            "message": "fix: bug fix",
            "branch": "develop",
            "changed_files": ("path/c.py",),
            "web_url": "http://example.com/commit/def456",
            "changed_files_summary": "path/c.py (+10/-5) @@ def fix_bug",
        }
        commit = _commit_from_dict(new_data)
        assert commit.sha == "def456"
        assert commit.changed_files_summary == "path/c.py (+10/-5) @@ def fix_bug"

    def test_dataclass_default_field_order(self) -> None:
        """dataclass 기본 필드 순서 유지."""
        # CommitInfo 생성자에 변수 순서대로 전달
        data = {
            "sha": "xyz",
            "author_name": "Charlie",
            "authored_at": "2026-07-22T12:00:00+09:00",
            "message": "test",
            "branch": "test",
            "changed_files": (),
            "web_url": "http://example.com/xyz",
            "changed_files_summary": None,
        }
        commit = _commit_from_dict(data)
        # 모든 필드가 정상 설정되었는지 확인
        assert commit.web_url is not None
        assert commit.changed_files_summary is None
