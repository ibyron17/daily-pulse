"""GitLab REST API v4를 통한 활동 수집."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from pulse.collector.diff_summary import DiffFileStat, summarize_diff
from pulse.collector.http_client import GitLabClient, RateLimitStats
from pulse.collector.snapshot import load_or_create
from pulse.collector.subtree import touches_subtree
from pulse.models import (
    BranchHistoryFetch,
    BranchHistoryRequest,
    BranchInfo,
    CommitInfo,
    MergeRequestInfo,
    MRState,
    RepoActivity,
    RepoRef,
    ReviewEvent,
)

logger = logging.getLogger(__name__)


class CollectionError(Exception):
    """수집 실패. 메시지에 원인을 포함한다."""

    pass


def _normalize_mr_state(gitlab_state: str) -> MRState:
    """
    GitLab API 상태값을 모델 타입으로 정규화한다.
    GitLab: "opened", "merged", "closed"
    모델: "open", "merged", "closed"
    알 수 없는 값 → CollectionError 발생 (수집 중단)
    """
    if gitlab_state == "opened":
        return "open"
    if gitlab_state == "merged":
        return "merged"
    if gitlab_state == "closed":
        return "closed"
    raise CollectionError(f"알 수 없는 MR 상태: {gitlab_state}")


def _fallback_commit_url(repo_web_url: str, sha: str) -> str:
    """web_url 미제공 커밋의 폴백 URL을 만든다.

    구버전 GitLab만 web_url을 생략하므로 구버전 경로 형식(/commit/)을 쓴다.
    """
    return f"{repo_web_url}/commit/{sha}"


def _fallback_branch_url(repo_web_url: str, branch_name: str) -> str:
    """web_url 미제공 브랜치의 폴백 URL을 만든다.

    구버전 GitLab만 web_url을 생략하므로 구버전 경로 형식(/tree/)을 쓴다.
    """
    return f"{repo_web_url}/tree/{quote(branch_name, safe='/')}"


class GitLab:
    """GitLab REST API v4 기반 수집 구현체."""

    def __init__(
        self,
        base_url: str,
        token: str,
        stats: RateLimitStats | None = None,
    ) -> None:
        """GitLab 서버 연결 초기화."""
        self.base_url = base_url
        self.client = GitLabClient(base_url, token, stats)

    def get_repo_version(self, repo: RepoRef) -> str:
        """GitLab 서버 버전을 확인한다."""
        try:
            version = self.client.get_version()
            logger.info("GitLab 버전: %s", version)
            return version
        except CollectionError as error:
            raise CollectionError(f"버전 확인 실패: {error}") from error

    def _get_project_id(self, repo: RepoRef) -> str:
        """레포 path를 GitLab project ID(URL-encoded path)로 변환한다."""
        return quote(repo.full_path, safe="")

    def _get_lookback_range(self, lookback_hours: int, now: datetime) -> tuple[datetime, str]:
        """
        lookback_hours 기반으로 시간 범위를 계산한다.

        Args:
            lookback_hours: 조회 범위 (시간 단위)
            now: 기준 시각 (UTC aware datetime)

        Returns:
            (시작 datetime, ISO 문자열)
        """
        since_dt = now - timedelta(hours=lookback_hours)
        since_iso = since_dt.isoformat()
        return since_dt, since_iso

    def _filter_active_branches(
        self,
        branches: list[dict[str, Any]],
        lookback_hours: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """
        lookback 시간 내에 push가 있었던 브랜치만 선별.
        각 브랜치의 commit.committed_date를 기준.

        Args:
            branches: GitLab API로부터의 브랜치 목록
            lookback_hours: 조회 범위 (시간 단위)
            now: 기준 시각 (UTC aware datetime)

        Returns:
            활동 브랜치 목록
        """
        since_dt, _ = self._get_lookback_range(lookback_hours, now)

        active = []
        for branch in branches:
            commit_data = branch.get("commit", {})
            committed_date_str = commit_data.get("committed_date")
            if not committed_date_str:
                continue
            committed_dt = datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
            if committed_dt >= since_dt:  # 둘 다 aware datetime
                active.append(branch)
        return active

    def _should_include_commit(
        self,
        author_name: str,
        exclude_bot_authors: tuple[str, ...],
    ) -> bool:
        """봇 작성자 제외 필터 적용."""
        return not any(excluded in author_name for excluded in exclude_bot_authors)

    def _build_commit_info(
        self,
        project_id: str,
        commit_data: dict[str, Any],
        branch_name: str,
        repo_web_url: str,
    ) -> CommitInfo:
        """커밋 데이터로부터 CommitInfo 객체 생성."""
        changed_files, changed_files_summary = self._get_commit_changed_files(
            project_id, commit_data["id"]
        )
        return CommitInfo(
            sha=commit_data["id"],
            author_name=commit_data.get("author_name", "unknown"),
            authored_at=datetime.fromisoformat(commit_data["authored_date"].replace("Z", "+00:00")),
            message=commit_data["message"],
            branch=branch_name,
            changed_files=changed_files,
            web_url=commit_data.get("web_url")
            or _fallback_commit_url(repo_web_url, commit_data["id"]),
            changed_files_summary=changed_files_summary,
        )

    def _collect_commits_for_branch(
        self,
        project_id: str,
        branch_name: str,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        now: datetime,
        repo_web_url: str,
        subtree_path: str | None = None,
    ) -> tuple[CommitInfo, ...]:
        """지정 브랜치의 활동 커밋을 수집한다.

        subtree_path가 있으면 서버 사이드 path 필터로 조회를 좁히고, 커밋마다 이미
        받은 changed_files로 한 번 더 확인한다 — 서버가 path를 무시해도(구버전 GitLab)
        정확성은 보장된다. subtree_path가 None이면 기존 요청과 완전히 동일하다.
        """
        _, since_iso = self._get_lookback_range(lookback_hours, now)
        try:
            if subtree_path is None:
                commits_data = self.client.list_commits(project_id, branch_name, since_iso)
            else:
                commits_data = self.client.list_commits(
                    project_id, branch_name, since_iso, path=subtree_path
                )
        except CollectionError as error:
            logger.warning("브랜치 %s 커밋 조회 실패: %s", branch_name, error)
            return ()

        commits = []
        for c in commits_data:
            author_name = c.get("author_name", "unknown")
            if not self._should_include_commit(author_name, exclude_bot_authors):
                continue
            commit = self._build_commit_info(project_id, c, branch_name, repo_web_url)
            if subtree_path is not None and not touches_subtree(commit.changed_files, subtree_path):
                continue
            commits.append(commit)

        return tuple(commits)

    def _get_commit_changed_files(
        self, project_id: str, commit_sha: str
    ) -> tuple[tuple[str, ...], str | None]:
        """
        커밋의 변경 파일 경로와 발췌를 조회한다.
        응답 필드 (각 파일): new_path, old_path, diff.
        신규/변경은 new_path, 삭제는 old_path 사용.

        Returns:
            (changed_files 경로 튜플, changed_files_summary 발췌 문자열)
        """
        try:
            diff_data = self.client.get_commit_diff(project_id, commit_sha)
            files = set()
            diff_file_stats = []

            for diff_item in diff_data:
                new_path = diff_item.get("new_path")
                old_path = diff_item.get("old_path")
                file_path = new_path if new_path else old_path

                if file_path:
                    files.add(file_path)

                    # diff 텍스트 파싱해서 DiffFileStat 생성
                    diff_text = diff_item.get("diff", "")
                    from pulse.collector.diff_summary import (
                        _count_added_deleted_lines,
                        _extract_hunk_headers,
                    )

                    added, deleted = _count_added_deleted_lines(diff_text)
                    headers = _extract_hunk_headers(diff_text)
                    diff_file_stats.append(
                        DiffFileStat(
                            path=file_path,
                            added_lines=added,
                            deleted_lines=deleted,
                            hunk_headers=headers,
                        )
                    )

            changed_files = tuple(sorted(files))
            changed_files_summary = (
                summarize_diff(tuple(diff_file_stats)) if diff_file_stats else None
            )
            return changed_files, changed_files_summary

        except CollectionError as error:
            logger.debug("diff 조회 실패 (%s): %s", commit_sha, error)
            return (), None

    def _get_mr_author_name(self, mr_data: dict[str, Any]) -> str:
        """MR 작성자명 추출 (표시 이름 우선, username 폴백).

        표시 이름(name) 우선: 커밋 author 이름과 네임스페이스 정렬.
        username 폴백: 표시 이름이 비어있으면 로그인 ID 사용.
        둘 다 없으면: "unknown".
        """
        author = mr_data.get("author", {})
        return cast(str, author.get("name") or author.get("username") or "unknown")

    def _build_merge_request_info(
        self,
        project_id: str,
        mr_data: dict[str, Any],
        normalized_state: MRState,
        mr_updated_at: datetime,
    ) -> MergeRequestInfo:
        """MR 데이터로부터 MergeRequestInfo 객체 생성."""
        reviews = self._collect_mr_reviews(project_id, mr_data["iid"], mr_updated_at)
        return MergeRequestInfo(
            iid=mr_data["iid"],
            title=mr_data["title"],
            state=normalized_state,
            is_draft=mr_data.get("draft", False) or mr_data.get("work_in_progress", False),
            labels=tuple(mr_data.get("labels", [])),
            source_branch=mr_data["source_branch"],
            target_branch=mr_data["target_branch"],
            author_name=self._get_mr_author_name(mr_data),
            created_at=datetime.fromisoformat(mr_data["created_at"].replace("Z", "+00:00")),
            updated_at=mr_updated_at,
            merged_at=self._resolve_merged_at(mr_data, normalized_state, mr_updated_at),
            reviews=reviews,
            is_external=mr_data.get("source_project_id") != mr_data.get("target_project_id"),
            web_url=mr_data["web_url"],
            description=mr_data.get("description"),
        )

    def _resolve_merged_at(
        self,
        mr_data: dict[str, Any],
        state: MRState,
        mr_updated_at: datetime,
    ) -> datetime | None:
        """merged_at을 결정한다.

        구버전 GitLab 응답에는 merged_at 필드가 없으므로,
        merged 상태에 한해 updated_at으로 근사한다 (없으면 merged 단계 판정 불가).
        """
        merged_at_str = mr_data.get("merged_at")
        if merged_at_str:
            return datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
        if state == "merged":
            return mr_updated_at
        return None

    def _try_normalize_mr_state(self, mr_data: dict[str, Any]) -> MRState | None:
        """MR 상태 정규화 시도. 실패하면 None 반환."""
        try:
            return _normalize_mr_state(mr_data.get("state", "opened"))
        except CollectionError as error:
            logger.warning("MR %d 상태 정규화 실패: %s", mr_data.get("iid", -1), error)
            return None

    def _get_mr_changed_files(self, project_id: str, mr_iid: int) -> tuple[str, ...] | None:
        """MR 변경 파일 경로를 조회한다. 조회 실패 시 None(= 판정 불가).

        None(판정 불가)과 ()(변경 파일이 진짜 없음)을 타입으로 구분한다 —
        하나로 합치면 조회 실패가 "서브트리 밖"으로 둔갑해 활동이 조용히 사라진다.
        """
        try:
            changes = self.client.get_merge_request_changes(project_id, mr_iid)
        except CollectionError as error:
            logger.warning(
                "MR %d 변경 파일 조회 실패 — 서브트리 판정 불가로 포함 처리: %s", mr_iid, error
            )
            return None

        files = set()
        for item in changes:
            new_path = item.get("new_path")
            old_path = item.get("old_path")
            file_path = new_path if new_path else old_path
            if file_path:
                files.add(file_path)
        return tuple(sorted(files))

    def _is_mr_in_subtree(self, project_id: str, mr_iid: int, subtree_path: str) -> bool:
        """MR이 서브트리를 건드렸는지 판정한다. 판정 불가면 True(포함, fail-open).

        빠진 MR은 화면에서 보이지 않아 아무도 모른다. 반대로 섞여 들어온 MR은
        화면에 보이고 사람이 이상함을 알아챌 수 있다 — 기존 노트·승인 조회 실패도
        같은 방향(포함)으로 처리한다.
        """
        changed_files = self._get_mr_changed_files(project_id, mr_iid)
        if changed_files is None:
            return True
        return touches_subtree(changed_files, subtree_path)

    def _process_single_mr(
        self,
        project_id: str,
        mr_data: dict[str, Any],
        exclude_bot_authors: tuple[str, ...],
        subtree_path: str | None = None,
    ) -> MergeRequestInfo | None:
        """단일 MR 처리. 봇 작성자/정규화 실패/서브트리 밖이면 None 반환.

        서브트리 게이트는 _build_merge_request_info(승인·노트 조회) 호출 전에 둔다 —
        범위 밖 MR은 그 조회 비용을 아예 지불하지 않는다.
        """
        author_name = self._get_mr_author_name(mr_data)
        if not self._should_include_commit(author_name, exclude_bot_authors):
            return None

        normalized_state = self._try_normalize_mr_state(mr_data)
        if normalized_state is None:
            return None

        if subtree_path is not None and not self._is_mr_in_subtree(
            project_id, mr_data["iid"], subtree_path
        ):
            return None

        mr_updated_at = datetime.fromisoformat(mr_data["updated_at"].replace("Z", "+00:00"))
        return self._build_merge_request_info(project_id, mr_data, normalized_state, mr_updated_at)

    def _collect_merge_requests(
        self,
        project_id: str,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        now: datetime,
        subtree_path: str | None = None,
    ) -> tuple[MergeRequestInfo, ...]:
        """시간 범위 내 MR을 수집한다."""
        _, since_iso = self._get_lookback_range(lookback_hours, now)
        try:
            mrs_data = self.client.list_merge_requests(project_id, since_iso)
        except CollectionError as error:
            logger.warning("MR 조회 실패: %s", error)
            return ()

        mrs = []
        for mr_data in mrs_data:
            mr = self._process_single_mr(project_id, mr_data, exclude_bot_authors, subtree_path)
            if mr is not None:
                mrs.append(mr)

        return tuple(mrs)

    def _collect_recent_merge_requests(
        self,
        project_id: str,
        limit: int,
        exclude_bot_authors: tuple[str, ...],
    ) -> tuple[MergeRequestInfo, ...]:
        """최근 N개 MR을 수집한다 (state=all, order_by=updated_at, sort=desc).

        실패 시 빈 튜플 반환 + 경고 로그 (레포 수집 전체를 실패시키지 않음).
        """
        try:
            mrs_data = self.client.list_recent_merge_requests(project_id, limit)
        except CollectionError as error:
            logger.warning("최근 MR 조회 실패 (%s, limit=%d): %s", project_id, limit, error)
            return ()

        mrs = []
        for mr_data in mrs_data:
            mr = self._process_single_mr(project_id, mr_data, exclude_bot_authors)
            if mr is not None:
                mrs.append(mr)

        return tuple(mrs)

    def _collect_approvals(
        self,
        project_id: str,
        mr_iid: int,
        mr_updated_at: datetime,
    ) -> tuple[ReviewEvent, ...]:
        """
        MR 승인 이벤트를 수집한다.
        occurred_at: approver의 approved_at 필드가 있으면 사용, 없으면 mr_updated_at 사용
        """
        approvals_list = []
        try:
            approvals = self.client.get_merge_request_approvals(project_id, mr_iid)
            for approver in approvals.get("approved_by", []):
                user_info = approver.get("user", {})
                approved_at_str = approver.get("approved_at")
                if approved_at_str:
                    occurred_at = datetime.fromisoformat(approved_at_str.replace("Z", "+00:00"))
                else:
                    occurred_at = mr_updated_at
                approvals_list.append(
                    ReviewEvent(
                        kind="approved",
                        actor_name=user_info.get("username") or user_info.get("name", "unknown"),
                        occurred_at=occurred_at,
                    )
                )
        except CollectionError:
            logger.debug("MR %d 승인 API 실패", mr_iid)
        return tuple(approvals_list)

    def _collect_mr_notes(
        self,
        project_id: str,
        mr_iid: int,
    ) -> tuple[ReviewEvent, ...]:
        """MR 댓글 이벤트를 수집한다. 시스템 노트는 제외."""
        notes_list = []
        try:
            notes = self.client.get_merge_request_notes(project_id, mr_iid)
            for note in notes:
                if note.get("system"):
                    continue
                author = note.get("author", {})
                notes_list.append(
                    ReviewEvent(
                        kind="commented",
                        actor_name=author.get("username") or author.get("name", "unknown"),
                        occurred_at=datetime.fromisoformat(
                            note.get("created_at", "").replace("Z", "+00:00")
                        ),
                    )
                )
        except CollectionError:
            logger.debug("MR %d 노트 조회 실패", mr_iid)
        return tuple(notes_list)

    def _collect_mr_reviews(
        self,
        project_id: str,
        mr_iid: int,
        mr_updated_at: datetime,
    ) -> tuple[ReviewEvent, ...]:
        """
        MR의 모든 리뷰 이벤트(승인, 댓글)를 수집한다.
        occurred_at 규칙:
        - 승인: approved_at 필드가 있으면 사용, 없으면 mr_updated_at
        - 댓글: created_at 필드 사용
        """
        approvals = self._collect_approvals(project_id, mr_iid, mr_updated_at)
        notes = self._collect_mr_notes(project_id, mr_iid)
        return approvals + notes

    def _collect_all_commits(
        self,
        project_id: str,
        active_branches_data: list[dict[str, Any]],
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        now: datetime,
        repo_web_url: str,
        subtree_path: str | None = None,
    ) -> list[CommitInfo]:
        """활동 브랜치들의 모든 커밋을 수집한다."""
        all_commits: list[CommitInfo] = []
        for branch_data in active_branches_data:
            branch_name = branch_data["name"]
            commits = self._collect_commits_for_branch(
                project_id,
                branch_name,
                lookback_hours,
                exclude_bot_authors,
                now,
                repo_web_url,
                subtree_path,
            )
            all_commits.extend(commits)
        return all_commits

    def _dedup_commits(self, commits: list[CommitInfo]) -> list[CommitInfo]:
        """SHA 기준 중복 제거."""
        seen_shas: set[str] = set()
        deduped: list[CommitInfo] = []
        for commit in commits:
            if commit.sha not in seen_shas:
                deduped.append(commit)
                seen_shas.add(commit.sha)
        return deduped

    def _build_branch_snapshots(
        self,
        repo: RepoRef,
        branches_data: list[dict[str, Any]],
        snapshot_dir: Path,
        now: datetime,
    ) -> tuple[set[str], set[str]]:
        """브랜치 스냅샷 저장 및 diff 계산. 첫 수집 시 created/deleted는 빈값."""
        today = now.strftime("%Y-%m-%d")
        current_branches = {b["name"] for b in branches_data}

        # 첫 수집 여부 확인
        snapshot, is_first_collection, previous = load_or_create(
            snapshot_dir, repo.slug, current_branches, today
        )

        # 첫 수집이면 created/deleted 모두 빈값
        if is_first_collection:
            logger.info("첫 수집 레포: %s (생성 브랜치 신호 제외)", repo.full_path)
            return set(), set()

        # 이후 수집이면 diff 계산
        created_branches: set[str] = set()
        deleted_branches: set[str] = set()
        if previous:
            created_branches, deleted_branches = snapshot.diff_against(previous)

        return created_branches, deleted_branches

    def _build_active_branch_objs(
        self,
        active_branches_data: list[dict[str, Any]],
        repo_web_url: str,
    ) -> tuple[BranchInfo, ...]:
        """활동 브랜치 객체 생성."""
        branch_objs = [
            BranchInfo(
                name=b["name"],
                last_commit_sha=b["commit"]["id"],
                last_pushed_at=datetime.fromisoformat(
                    b["commit"]["committed_date"].replace("Z", "+00:00")
                ),
                web_url=b.get("web_url") or _fallback_branch_url(repo_web_url, b["name"]),
            )
            for b in active_branches_data
        ]
        return tuple(branch_objs)

    def _is_stale_branch(
        self,
        branch: dict[str, Any],
        stale_threshold: datetime,
    ) -> bool:
        """브랜치가 stale인지 판별."""
        if branch.get("merged") or branch.get("default"):
            return False
        commit_data = branch.get("commit", {})
        committed_date_str = commit_data.get("committed_date")
        if not committed_date_str:
            return False
        committed_dt = datetime.fromisoformat(committed_date_str.replace("Z", "+00:00"))
        return committed_dt < stale_threshold

    def _make_stale_branch_info(
        self,
        branch: dict[str, Any],
        repo_web_url: str,
    ) -> BranchInfo:
        """브랜치 데이터에서 BranchInfo 생성."""
        commit_data = branch.get("commit", {})
        committed_dt = datetime.fromisoformat(
            commit_data.get("committed_date", "").replace("Z", "+00:00")
        )
        return BranchInfo(
            name=branch["name"],
            last_commit_sha=commit_data["id"],
            last_pushed_at=committed_dt,
            web_url=branch.get("web_url") or _fallback_branch_url(repo_web_url, branch["name"]),
        )

    def _collect_stale_branches(
        self,
        branches_data: list[dict[str, Any]],
        stale_branch_days: int,
        now: datetime,
        repo_web_url: str,
    ) -> tuple[BranchInfo, ...]:
        """
        merged != true, default != true, 마지막 커밋이 stale_branch_days 이전인 브랜치 수집.
        예외 발생 시 로깅 후 빈 tuple 반환.
        """
        stale_threshold = now - timedelta(days=stale_branch_days)
        stale = []

        try:
            for branch in branches_data:
                if self._is_stale_branch(branch, stale_threshold):
                    stale.append(self._make_stale_branch_info(branch, repo_web_url))
        except CollectionError as error:
            logger.warning("정체 브랜치 수집 실패: %s", error)
            return ()

        return tuple(stale)

    def _collect_all_open_mrs(
        self,
        project_id: str,
        exclude_bot_authors: tuple[str, ...],
        subtree_path: str | None = None,
    ) -> tuple[MergeRequestInfo, ...]:
        """
        상태별 제한 없이 전체 open MR 조회 (중복 제거).
        """
        try:
            mrs_data = self.client.list_open_merge_requests(project_id)
        except CollectionError as error:
            logger.warning("전체 open MR 조회 실패: %s", error)
            return ()

        mrs = []
        seen_iids: set[int] = set()
        for mr_data in mrs_data:
            iid = mr_data.get("iid")
            if iid is None or not isinstance(iid, int):
                continue
            if iid in seen_iids:
                continue
            seen_iids.add(iid)

            mr = self._process_single_mr(project_id, mr_data, exclude_bot_authors, subtree_path)
            if mr is not None:
                mrs.append(mr)

        return tuple(mrs)

    def _merge_window_and_all_mrs(
        self,
        window_mrs: tuple[MergeRequestInfo, ...],
        project_id: str,
        exclude_bot_authors: tuple[str, ...],
        subtree_path: str | None = None,
    ) -> tuple[MergeRequestInfo, ...]:
        """
        윈도 내 MR과 전체 오픈 MR을 병합한다.
        윈도 조회 결과를 우선한다 (리뷰·노트가 이미 붙어 있음).
        """
        all_mrs = self._collect_all_open_mrs(project_id, exclude_bot_authors, subtree_path)

        # 윈도 MR을 dict로 인덱싱 (iid → MR)
        window_by_iid = {mr.iid: mr for mr in window_mrs}

        # 모든 MR 중 윈도에 없는 것만 추가
        merged = list(window_mrs)
        for mr in all_mrs:
            if mr.iid not in window_by_iid:
                merged.append(mr)

        return tuple(merged)

    def _build_successful_activity(
        self,
        repo: RepoRef,
        deduped_commits: list[CommitInfo],
        active_branch_objs: tuple[BranchInfo, ...],
        created: tuple[str, ...],
        deleted: tuple[str, ...],
        merge_requests: tuple[MergeRequestInfo, ...],
        stale_branches: tuple[BranchInfo, ...],
        now: datetime,
        recent_merge_requests: tuple[MergeRequestInfo, ...] = (),
    ) -> RepoActivity:
        """성공적인 수집 결과를 RepoActivity로 변환한다."""
        return RepoActivity(
            repo=repo,
            status="ok",
            failure_reason=None,
            commits=tuple(deduped_commits),
            active_branches=active_branch_objs,
            created_branches=created,
            deleted_branches=deleted,
            merge_requests=merge_requests,
            stale_branches=stale_branches,
            recent_merge_requests=recent_merge_requests,
            collected_at=now,
        )

    def _collect_commit_and_mr_data(
        self,
        project_id: str,
        active_branches_data: list[dict[str, Any]],
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        now: datetime,
        repo_web_url: str,
        recent_mr_limit: int = 50,
        subtree_path: str | None = None,
    ) -> tuple[list[CommitInfo], tuple[MergeRequestInfo, ...], tuple[MergeRequestInfo, ...]]:
        """커밋과 MR 데이터를 수집한다 (윈도 내 MR + 전체 오픈 MR 병합, 최근 MR 포함).

        subtree_path가 있으면 커밋·MR을 그 경로를 건드린 것만으로 좁힌다.
        recent_merge_requests(릴리스 열차용)는 레포 전체 기준을 유지한다 —
        이 필터를 넘기지 않는다(3.3(c): 사다리 공백 방지).

        반환값: (deduped_commits, merge_requests, recent_merge_requests)
        """
        all_commits = self._collect_all_commits(
            project_id,
            active_branches_data,
            lookback_hours,
            exclude_bot_authors,
            now,
            repo_web_url,
            subtree_path,
        )
        deduped_commits = self._dedup_commits(all_commits)
        window_mrs = self._collect_merge_requests(
            project_id, lookback_hours, exclude_bot_authors, now, subtree_path
        )
        # 윈도 조회 결과와 전체 오픈 MR 병합: 윈도 우선 (리뷰·노트 이미 있음)
        merge_requests = self._merge_window_and_all_mrs(
            window_mrs, project_id, exclude_bot_authors, subtree_path
        )
        # 최근 MR 수집 (릴리스 열차 구축용) — 서브트리 필터 미적용 (레포 전체 기준 유지)
        recent_merge_requests = self._collect_recent_merge_requests(
            project_id, recent_mr_limit, exclude_bot_authors
        )
        return deduped_commits, merge_requests, recent_merge_requests

    def _collect_branch_and_snapshot_data(
        self,
        repo: RepoRef,
        branches_data: list[dict[str, Any]],
        stale_branch_days: int,
        snapshot_dir: Path | None,
        now: datetime,
    ) -> tuple[tuple[BranchInfo, ...], tuple[str, ...], tuple[str, ...]]:
        """stale 브랜치, 스냅샷, created/deleted 브랜치 수집."""
        stale_branches = self._collect_stale_branches(
            branches_data, stale_branch_days, now, repo.web_url
        )
        created_branches: set[str] = set()
        deleted_branches: set[str] = set()
        if snapshot_dir:
            created_branches, deleted_branches = self._build_branch_snapshots(
                repo, branches_data, snapshot_dir, now
            )
        return stale_branches, tuple(created_branches), tuple(deleted_branches)

    def _run_collection_pipeline(
        self,
        repo: RepoRef,
        project_id: str,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        snapshot_dir: Path | None,
        stale_branch_days: int,
        now: datetime,
        recent_mr_limit: int = 50,
        subtree_path: str | None = None,
    ) -> RepoActivity:
        """수집 파이프라인 실행 (예외 처리 외부에서 수행)."""
        branches_data = self.client.list_branches(project_id)
        active_branches_data = self._filter_active_branches(branches_data, lookback_hours, now)
        (
            deduped_commits,
            merge_requests,
            recent_merge_requests,
        ) = self._collect_commit_and_mr_data(
            project_id,
            active_branches_data,
            lookback_hours,
            exclude_bot_authors,
            now,
            repo.web_url,
            recent_mr_limit=recent_mr_limit,
            subtree_path=subtree_path,
        )
        stale_branches, created, deleted = self._collect_branch_and_snapshot_data(
            repo, branches_data, stale_branch_days, snapshot_dir, now
        )
        active_branch_objs = self._build_active_branch_objs(active_branches_data, repo.web_url)
        return self._build_successful_activity(
            repo,
            deduped_commits,
            active_branch_objs,
            created,
            deleted,
            merge_requests,
            stale_branches,
            now,
            recent_merge_requests=recent_merge_requests,
        )

    def _build_failed_repo_activity(
        self,
        repo: RepoRef,
        now: datetime,
        error: CollectionError,
    ) -> RepoActivity:
        """실패한 레포 수집 결과를 생성한다."""
        return RepoActivity(
            repo=repo,
            status="failed",
            failure_reason=str(error),
            commits=(),
            active_branches=(),
            created_branches=(),
            deleted_branches=(),
            merge_requests=(),
            collected_at=now,
        )

    def collect_repo_activity(
        self,
        repo: RepoRef,
        lookback_hours: int,
        exclude_bot_authors: tuple[str, ...],
        snapshot_dir: Path | None = None,
        stale_branch_days: int = 7,
        now: datetime | None = None,
        recent_mr_limit: int = 50,
    ) -> RepoActivity:
        """
        레포의 모든 활동을 동기적으로 수집한다.

        상태가 "failed"인 경우 failure_reason을 포함.
        snapshot_dir이 지정되면 브랜치 스냅샷을 저장하고 diff 계산.

        Args:
            repo: 레포 참조
            lookback_hours: 조회 범위 (시간 단위)
            exclude_bot_authors: 제외할 봇 author 목록
            snapshot_dir: 브랜치 스냅샷 저장 디렉토리
            stale_branch_days: 정체 브랜치 판별 일 수
            now: 기준 시각 (UTC aware datetime, None이면 현재 시각 사용)
            recent_mr_limit: 최근 MR 조회 건수 (기본값 50)

        Returns:
            RepoActivity
        """
        project_id = self._get_project_id(repo)
        if now is None:
            now = datetime.now(tz=timezone.utc)

        try:
            return self._run_collection_pipeline(
                repo,
                project_id,
                lookback_hours,
                exclude_bot_authors,
                snapshot_dir,
                stale_branch_days,
                now,
                recent_mr_limit=recent_mr_limit,
                subtree_path=repo.subtree_path,
            )
        except CollectionError as error:
            logger.error("레포 %s 수집 실패: %s", repo.full_path, error)
            return self._build_failed_repo_activity(repo, now, error)

    def collect_branch_history(
        self,
        repo: RepoRef,
        branches: tuple[BranchHistoryRequest, ...],
        base_branch_hint: str | None,
        max_commits: int,
    ) -> tuple[BranchHistoryFetch, ...]:
        """분기점부터의 브랜치 히스토리를 수집한다 (gitlab_history 모듈에 위임)."""
        from pulse.collector.gitlab_history import collect_branch_history

        return collect_branch_history(
            self.client,
            self._get_project_id(repo),
            branches,
            base_branch_hint,
            max_commits,
        )
