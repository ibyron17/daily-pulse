"""author_name NFC 정규화 테스트 (macOS NFD 저장 문제 대응)."""

import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from pulse.grouper.group import aggregate_participants
from pulse.models import CommitInfo, MergeRequestInfo

KST = ZoneInfo("Asia/Seoul")


class TestCommitInfoAuthorNormalization:
    """CommitInfo의 author_name NFC 정규화."""

    def test_nfd_author_name_normalized_to_nfc_on_creation(self) -> None:
        """NFD 형태의 author_name이 NFC로 정규화됨."""
        # Arrange: NFD 형태의 "[DEV]홍길동" 생성
        nfd_name = unicodedata.normalize("NFD", "[DEV]홍길동")
        assert nfd_name != "[DEV]홍길동"  # 실제로 다른 형태인지 확인

        # Act
        commit = CommitInfo(
            sha="abc123",
            author_name=nfd_name,
            authored_at=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
            message="test commit",
            branch="main",
            changed_files=("file.py",),
            web_url="https://example.com/commit/abc123",
        )

        # Assert
        assert commit.author_name == "[DEV]홍길동"  # NFC 정규형
        assert commit.author_name == unicodedata.normalize("NFC", nfd_name)

    def test_nfc_author_name_unchanged(self) -> None:
        """이미 NFC 형태인 author_name은 그대로 유지."""
        # Arrange
        nfc_name = "[DEV]홍길동"

        # Act
        commit = CommitInfo(
            sha="abc123",
            author_name=nfc_name,
            authored_at=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
            message="test commit",
            branch="main",
            changed_files=("file.py",),
            web_url="https://example.com/commit/abc123",
        )

        # Assert
        assert commit.author_name == "[DEV]홍길동"

    def test_from_dict_also_normalizes_author_name(self) -> None:
        """from_dict 경로도 author_name을 NFC로 정규화."""
        # Arrange
        nfd_name = unicodedata.normalize("NFD", "[DEV]홍길동")
        commit_dict = {
            "sha": "abc123",
            "author_name": nfd_name,
            "authored_at": "2026-07-15T09:00:00+09:00",
            "message": "test commit",
            "branch": "main",
            "changed_files": ["file.py"],
            "web_url": "https://example.com/commit/abc123",
        }

        # Act: from_dict 경로 (모델의 from_dict 함수 사용)
        from pulse.models import _commit_from_dict

        commit = _commit_from_dict(commit_dict)

        # Assert
        assert commit.author_name == "[DEV]홍길동"  # NFC 정규형


class TestMergeRequestInfoAuthorNormalization:
    """MergeRequestInfo의 author_name NFC 정규화."""

    def test_nfd_mr_author_name_normalized_to_nfc_on_creation(self) -> None:
        """NFD 형태의 MR author_name이 NFC로 정규화됨."""
        # Arrange
        nfd_name = unicodedata.normalize("NFD", "[DEV]홍길동")

        # Act
        mr = MergeRequestInfo(
            iid=1,
            title="test MR",
            state="open",
            is_draft=False,
            labels=(),
            source_branch="feature",
            target_branch="main",
            author_name=nfd_name,
            created_at=datetime(2026, 7, 14, 9, 0, tzinfo=KST),
            updated_at=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
            merged_at=None,
            reviews=(),
            is_external=False,
            web_url="https://example.com/mr/1",
        )

        # Assert
        assert mr.author_name == "[DEV]홍길동"  # NFC 정규형

    def test_from_dict_also_normalizes_mr_author_name(self) -> None:
        """MR from_dict 경로도 author_name을 NFC로 정규화."""
        # Arrange
        nfd_name = unicodedata.normalize("NFD", "[DEV]홍길동")
        mr_dict = {
            "iid": 1,
            "title": "test MR",
            "state": "open",
            "is_draft": False,
            "labels": [],
            "source_branch": "feature",
            "target_branch": "main",
            "author_name": nfd_name,
            "created_at": "2026-07-14T09:00:00+09:00",
            "updated_at": "2026-07-15T09:00:00+09:00",
            "merged_at": None,
            "reviews": [],
            "is_external": False,
            "web_url": "https://example.com/mr/1",
        }

        # Act
        from pulse.models import _merge_request_from_dict

        mr = _merge_request_from_dict(mr_dict)

        # Assert
        assert mr.author_name == "[DEV]홍길동"  # NFC 정규형


class TestParticipantDeduplicationWithNormalization:
    """NFD/NFC 정규화를 통한 참여자 중복 제거."""

    def test_nfd_and_nfc_same_person_deduplicated(self) -> None:
        """NFD와 NFC 형태의 동일 인물이 1명으로 집계됨."""
        # Arrange
        nfc_name = "[DEV]홍길동"
        nfd_name = unicodedata.normalize("NFD", "[DEV]홍길동")

        commit_nfc = CommitInfo(
            sha="abc123",
            author_name=nfc_name,
            authored_at=datetime(2026, 7, 15, 9, 0, tzinfo=KST),
            message="commit 1",
            branch="main",
            changed_files=("file.py",),
            web_url="https://example.com/abc123",
        )

        commit_nfd = CommitInfo(
            sha="def456",
            author_name=nfd_name,
            authored_at=datetime(2026, 7, 15, 10, 0, tzinfo=KST),
            message="commit 2",
            branch="main",
            changed_files=("file.py",),
            web_url="https://example.com/def456",
        )

        # Act: 두 커밋을 집계해서 참여자 추출
        participants = aggregate_participants((commit_nfc, commit_nfd), ())

        # Assert: 동일 인물(NFC로 정규화됨)로 인식되어 1명만 집계
        assert len(participants) == 1
        assert "[DEV]홍길동" in participants
