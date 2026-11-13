"""서브트리 경로 포함 판정 (순수 — 네트워크·파일시스템에 닿지 않는다)."""


def is_path_in_subtree(file_path: str, subtree_path: str) -> bool:
    """파일 경로가 서브트리 안(또는 그 경로 자체)인지 판정한다.

    subtree_path는 config 로더가 정규화한 형태(선행·후행 슬래시 없음)임을 전제한다.
    세그먼트 경계를 명시적으로 확인한다 — 단순 startswith(subtree_path)를 쓰면
    "sample-model2/x.ts"가 "sample-model"에 잘못 걸린다.
    대소문자는 접지 않는다 — git 경로는 대소문자를 구분한다.
    """
    return file_path == subtree_path or file_path.startswith(subtree_path + "/")


def touches_subtree(file_paths: tuple[str, ...], subtree_path: str) -> bool:
    """변경 파일 중 하나라도 서브트리에 속하면 True."""
    return any(is_path_in_subtree(path, subtree_path) for path in file_paths)
