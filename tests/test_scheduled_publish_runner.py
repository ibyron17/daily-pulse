"""정기 발행 러너(scripts/scheduled-publish.sh)의 결과 판정·시간 제한 로직 테스트.

러너는 bash라 판정 함수와 벽시계 제한 함수만 source 해서 호출한다 —
`SCHEDULED_PUBLISH_SOURCE_ONLY=1` 가드가 실행부(claude 기동·로그 기록)를 건너뛴다.
"""

import contextlib
import os
import shlex
import shutil
import signal
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from subprocess import Popen
from subprocess import run as run_process
from typing import NamedTuple

import pytest

# conftest의 mock_gh_cli(autouse)가 subprocess.run 속성을 패치하므로, 모듈 로드 시점에
# 원본을 바인딩해 우회한다 — 여기서 실행하는 건 gh CLI가 아니라 러너 자신의 bash 함수다.

RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "scheduled-publish.sh"
# 운영(launchd)이 쓰는 macOS 기본 bash 3.2 — PATH 앞의 Homebrew bash 5로 돌리면
# 운영과 다른 인터프리터를 검증하게 된다.
BASH = "/bin/bash"

LIMIT_MESSAGE = "You've hit your limit · resets 12pm (Asia/Seoul)"
LOGIN_MESSAGE = "Not logged in · Please run /login"
# 2026-10-02 장애의 실제 한도 메시지 — "extra usage" 문구와 날짜가 붙은 리셋 표기
EXTRA_USAGE_MESSAGE = "You're out of extra usage · resets Oct 4 at 8am (Asia/Seoul)"
TIMEOUT_LINE = "=== TIMEOUT: claude exceeded 2700s, process tree killed ==="
TIMEOUT_LINE_AT_ONE_SECOND = TIMEOUT_LINE.replace("2700", "1")
FALLBACK_WAIT_SECONDS = 3600
MAX_WAIT_SECONDS = 21600
RESET_BUFFER_SECONDS = 120
INCIDENT_BASE = datetime(2026, 10, 2, 9, 30)  # 한도 소진을 확인한 시각
WATCHDOG_TEST_DEADLINE_SECONDS = 30  # 제한 로직이 망가져도 테스트가 매달리지 않게 하는 안전망
PID_FILE_WAIT_SECONDS = 5
PIDS_DEAD_WAIT_SECONDS = 2
STUB_SLEEP_SECONDS = 30


def _call(function: str, *args: str) -> str:
    """러너를 source한 뒤 판정 함수 하나를 호출하고 표준출력을 돌려준다."""
    command = (
        f"source {shlex.quote(str(RUNNER))}; {function} {' '.join(shlex.quote(a) for a in args)}"
    )
    result = run_process(
        [BASH, "-c", command],
        env={**os.environ, "SCHEDULED_PUBLISH_SOURCE_ONLY": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _succeeds(function: str, *args: str) -> bool:
    """판정 함수의 종료 코드로 참/거짓을 읽는다 — 0=참, 1=거짓, 그 외(함수 없음 등)는 오류."""
    command = (
        f"source {shlex.quote(str(RUNNER))}; {function} {' '.join(shlex.quote(a) for a in args)}"
    )
    result = run_process(
        [BASH, "-c", command],
        env={**os.environ, "SCHEDULED_PUBLISH_SOURCE_ONLY": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _epoch_of(moment: datetime) -> str:
    """로컬 시각의 epoch 문자열 — 러너의 date도 로컬 TZ로 계산한다."""
    return str(int(moment.timestamp()))


def _epoch(hour: int, minute: int) -> str:
    """2026-08-05 로컬 시각의 epoch 문자열."""
    return _epoch_of(datetime(2026, 8, 5, hour, minute))


def _seconds_between(start: datetime, end: datetime) -> int:
    return int(end.timestamp() - start.timestamp())


class TestClassifyAttempt:
    """종료 마커 + 대시보드 존재로 시도 결과를 가른다."""

    def test_ok_marker_wins(self, tmp_path: Path) -> None:
        assert (
            _call("classify_attempt", "전부 성공\nPULSE_PUBLISH_OK", str(tmp_path / "none.html"))
            == "ok"
        )

    def test_partial_marker(self, tmp_path: Path) -> None:
        segment = "PULSE_PUBLISH_PARTIAL: 주간 주입 실패"
        assert _call("classify_attempt", segment, str(tmp_path / "none.html")) == "partial"

    def test_dashboard_exists_without_marker_is_partial(self, tmp_path: Path) -> None:
        """2026-08-05 회귀: 한도 소진으로 마커조차 못 냈지만 대시보드는 발행된 경우."""
        dashboard = tmp_path / "pulse-2026-08-05.html"
        dashboard.write_text("<html></html>", encoding="utf-8")
        assert _call("classify_attempt", LIMIT_MESSAGE, str(dashboard)) == "partial"

    def test_limit_without_dashboard_is_limit_exceeded(self, tmp_path: Path) -> None:
        assert (
            _call("classify_attempt", LIMIT_MESSAGE, str(tmp_path / "none.html"))
            == "limit_exceeded"
        )

    def test_login_expired_without_dashboard(self, tmp_path: Path) -> None:
        """2026-07-31 회귀: 기동 직후 로그인 만료는 대시보드가 없다."""
        assert (
            _call("classify_attempt", LOGIN_MESSAGE, str(tmp_path / "none.html")) == "login_expired"
        )

    def test_unknown_failure_is_fail(self, tmp_path: Path) -> None:
        assert (
            _call("classify_attempt", "Traceback: 알 수 없는 오류", str(tmp_path / "none.html"))
            == "fail"
        )

    def test_precheck_ignores_existing_dashboard(self, tmp_path: Path) -> None:
        """precheck는 발행하지 않으므로 기존 대시보드를 성공 근거로 삼으면 안 된다."""
        dashboard = tmp_path / "pulse-2026-08-05.html"
        dashboard.write_text("<html></html>", encoding="utf-8")
        assert _call("classify_attempt", LIMIT_MESSAGE, "") == "limit_exceeded"

    def test_out_of_extra_usage_is_limit_exceeded(self, tmp_path: Path) -> None:
        """2026-10-02 회귀: 'out of extra usage' 문구가 fail로 분류돼 무의미한 재시도로 갔다."""
        assert (
            _call("classify_attempt", EXTRA_USAGE_MESSAGE, str(tmp_path / "none.html"))
            == "limit_exceeded"
        )

    def test_timeout_line_is_timeout(self, tmp_path: Path) -> None:
        segment = f"진행 중...\n{TIMEOUT_LINE}\n=== claude exit code: 143 / end: x ==="
        assert _call("classify_attempt", segment, str(tmp_path / "none.html")) == "timeout"

    def test_timeout_with_dashboard_is_partial(self, tmp_path: Path) -> None:
        """시간 초과여도 대시보드가 이미 발행됐으면 재수집하지 않고 partial이다."""
        dashboard = tmp_path / "pulse-2026-10-03.html"
        dashboard.write_text("<html></html>", encoding="utf-8")
        assert _call("classify_attempt", TIMEOUT_LINE, str(dashboard)) == "partial"

    def test_ok_marker_beats_timeout_line(self, tmp_path: Path) -> None:
        segment = f"PULSE_PUBLISH_OK\n{TIMEOUT_LINE}"
        assert _call("classify_attempt", segment, str(tmp_path / "none.html")) == "ok"

    def test_timeout_wins_over_login_and_limit_text(self, tmp_path: Path) -> None:
        """멈춘 실행의 로그에 로그인·한도 문구가 섞여 있어도 시간 초과가 먼저다."""
        segment = f"{LOGIN_MESSAGE}\n{LIMIT_MESSAGE}\n{TIMEOUT_LINE}"
        assert _call("classify_attempt", segment, str(tmp_path / "none.html")) == "timeout"

    def test_timeout_text_inside_a_line_is_not_the_runner_marker(self, tmp_path: Path) -> None:
        """러너가 직접 남기는 줄만 인정한다 — claude 출력 중간에 낀 문구는 무시한다."""
        segment = f"로그: {TIMEOUT_LINE}"
        assert _call("classify_attempt", segment, str(tmp_path / "none.html")) == "fail"


class TestParseLimitResetDelay:
    """한도 메시지의 리셋 시각까지 대기할 초를 계산한다."""

    def test_afternoon_reset_same_day(self) -> None:
        """09:07에 소진, 리셋 12pm → 2시간 53분 + 버퍼."""
        delay = _call("parse_limit_reset_delay", LIMIT_MESSAGE, _epoch(9, 7))
        assert int(delay) == 2 * 3600 + 53 * 60 + RESET_BUFFER_SECONDS

    def test_reset_with_minutes(self) -> None:
        delay = _call("parse_limit_reset_delay", "resets 12:30pm (Asia/Seoul)", _epoch(9, 7))
        assert int(delay) == 3 * 3600 + 23 * 60 + RESET_BUFFER_SECONDS

    def test_noon_is_twelve_not_midnight(self) -> None:
        """12pm=정오, 12am=자정 — 12시간제 변환이 뒤집히면 반나절이 어긋난다."""
        noon = int(_call("parse_limit_reset_delay", "resets 12pm", _epoch(11, 0)))
        midnight = int(_call("parse_limit_reset_delay", "resets 12am", _epoch(11, 0)))
        assert noon == 3600 + RESET_BUFFER_SECONDS
        assert midnight > noon

    def test_at_prefix_and_uppercase(self) -> None:
        """`resets at 2PM` 같은 표기 변형도 같은 시각으로 읽는다."""
        delay = _call("parse_limit_reset_delay", "resets at 2PM", _epoch(9, 0))
        assert int(delay) == 5 * 3600 + RESET_BUFFER_SECONDS

    def test_past_time_rolls_to_next_day_without_cap(self) -> None:
        """이미 지난 시각은 다음 날로 넘긴다. 상한으로 자르지 않아 호출부가 포기를 판정한다."""
        delay = _call("parse_limit_reset_delay", "resets 3am", _epoch(9, 7))
        assert int(delay) == (24 - 9 + 3) * 3600 - 7 * 60 + RESET_BUFFER_SECONDS

    @pytest.mark.parametrize(
        ("segment", "target"),
        [
            (EXTRA_USAGE_MESSAGE, datetime(2026, 10, 4, 8, 0)),
            ("resets Oct 4 at 8:30pm", datetime(2026, 10, 4, 20, 30)),
            ("resets oct 4, 8AM", datetime(2026, 10, 4, 8, 0)),
            ("resets October 4, at 8:05 PM (Asia/Seoul)", datetime(2026, 10, 4, 20, 5)),
            ("resets Oct 5 at 12am", datetime(2026, 10, 5, 0, 0)),
            ("resets Oct 4 at 12pm", datetime(2026, 10, 4, 12, 0)),
            ("resets Oct 2 at 12pm", datetime(2026, 10, 2, 12, 0)),
        ],
        ids=[
            "incident-message",
            "pm-with-minutes",
            "lowercase-comma",
            "full-month-name-and-spaced-pm",
            "midnight-12am",
            "noon-12pm",
            "same-day-with-date",
        ],
    )
    def test_dated_reset_notation(self, segment: str, target: datetime) -> None:
        """2026-10-02 회귀: 'resets Oct 4 at 8am' 같은 날짜 표기가 폴백(1시간)으로 떨어졌다."""
        delay = _call("parse_limit_reset_delay", segment, _epoch_of(INCIDENT_BASE))
        assert int(delay) == _seconds_between(INCIDENT_BASE, target) + RESET_BUFFER_SECONDS

    def test_dated_reset_across_year_end_rolls_to_next_year(self) -> None:
        base = datetime(2026, 12, 31, 22, 0)
        delay = _call("parse_limit_reset_delay", "resets Jan 1 at 8am", _epoch_of(base))
        expected = _seconds_between(base, datetime(2027, 1, 1, 8, 0)) + RESET_BUFFER_SECONDS
        assert int(delay) == expected

    @pytest.mark.parametrize(
        "segment",
        [
            "You've hit your limit",
            "resets soon",
            "resets 25pm",
            "resets Foo 4 at 8am",
            "resets Oct 45 at 8am",
            "resets Oct 4 at 8am (UTC)",
            "resets 12pm (America/New_York)",
        ],
        ids=[
            "no-reset-clause",
            "no-time",
            "invalid-hour",
            "unknown-month",
            "invalid-day",
            "dated-foreign-timezone",
            "time-only-foreign-timezone",
        ],
    )
    def test_unparsable_falls_back(self, segment: str) -> None:
        assert int(_call("parse_limit_reset_delay", segment, _epoch(9, 7))) == FALLBACK_WAIT_SECONDS


class TestExceedsLimitMaxWait:
    """리셋이 대기 상한을 넘으면 상한까지 기다려도 실패가 확정이라 재시도를 포기한다."""

    @pytest.mark.parametrize(
        ("delay", "expected"),
        [
            (FALLBACK_WAIT_SECONDS, False),
            (MAX_WAIT_SECONDS, False),
            (MAX_WAIT_SECONDS + 1, True),
        ],
        ids=["fallback", "exactly-at-limit", "just-over-limit"],
    )
    def test_boundary(self, delay: int, expected: bool) -> None:
        assert _succeeds("exceeds_limit_max_wait", str(delay)) is expected

    def test_incident_message_gives_up(self) -> None:
        """2026-10-02: 리셋이 이틀 뒤라 6시간을 기다려도 소용없었다."""
        delay = _call("parse_limit_reset_delay", EXTRA_USAGE_MESSAGE, _epoch_of(INCIDENT_BASE))
        assert _succeeds("exceeds_limit_max_wait", delay) is True

    def test_near_reset_keeps_retrying(self) -> None:
        delay = _call("parse_limit_reset_delay", LIMIT_MESSAGE, _epoch(9, 7))
        assert _succeeds("exceeds_limit_max_wait", delay) is False


# 3단 트리(루트 → 자식 bash → 손자 sleep)를 만들고 각 pid를 기록하는 스텁.
# 실제 장애는 claude가 멈춘 `security`를 자식으로 달고 있던 구조다.
# TERM 무시 변형은 상속돼 손자까지 TERM을 무시하므로 KILL 단계가 있어야만 정리된다.
TREE_STUB = """#!/bin/bash
{ignore_term}
echo $$ > "$1/root.pid"
/bin/bash -c 'echo $$ > "$0/child.pid"; sleep {sleep_seconds} &
  echo $! > "$0/grandchild.pid"; wait' "$1" &
wait
"""
PID_FILE_NAMES = ("root.pid", "child.pid", "grandchild.pid")


class LimitedRun(NamedTuple):
    """벽시계 제한 함수를 한 번 돌린 결과."""

    stdout: str
    exit_code: int
    elapsed_seconds: float
    leftover_children: str  # 함수가 끝난 뒤에도 호출 셸의 자식으로 남은 pid들


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _recorded_pids(pid_dir: Path) -> list[int]:
    return [
        int((pid_dir / name).read_text().strip())
        for name in PID_FILE_NAMES
        if (pid_dir / name).exists()
    ]


def _wait_until_dead(pids: list[int]) -> bool:
    """고아가 된 손자는 init이 수거하는 데 잠깐 걸리므로 짧게 기다리며 확인한다."""
    deadline = time.monotonic() + PIDS_DEAD_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return not any(_alive(pid) for pid in pids)


@pytest.fixture
def pid_dir(tmp_path: Path) -> Iterator[Path]:
    """스텁이 pid를 기록하는 디렉터리. 제한 로직이 망가져 프로세스가 남아도 정리한다."""
    directory = tmp_path / "pids"
    directory.mkdir()
    yield directory
    for pid in _recorded_pids(directory):
        if _alive(pid):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def _write_tree_stub(directory: Path, *, ignore_term: bool) -> Path:
    stub = directory / "tree_stub.sh"
    stub.write_text(
        TREE_STUB.format(
            ignore_term="trap '' TERM" if ignore_term else "",
            sleep_seconds=STUB_SLEEP_SECONDS,
        )
    )
    stub.chmod(0o755)
    return stub


def _runner_env(timeout_seconds: int) -> dict[str, str]:
    return {
        **os.environ,
        "SCHEDULED_PUBLISH_SOURCE_ONLY": "1",
        "ATTEMPT_TIMEOUT_SECONDS": str(timeout_seconds),
    }


def _run_limited(tmp_path: Path, timeout_seconds: int, *stub_command: str) -> LimitedRun:
    """명령을 벽시계 제한 함수로 돌리고, 끝난 시점에 남은 자식 프로세스를 함께 기록한다."""
    leftover_file = tmp_path / "leftover.txt"
    command = " ".join(shlex.quote(part) for part in stub_command)
    script = (
        f"source {shlex.quote(str(RUNNER))}; "
        f"run_with_wall_clock_limit {command}; "
        'echo "exit=$?"; '
        f"pgrep -P $$ >{shlex.quote(str(leftover_file))}"
    )
    started = time.monotonic()
    result = run_process(
        [BASH, "-c", script],
        env=_runner_env(timeout_seconds),
        capture_output=True,
        text=True,
        timeout=WATCHDOG_TEST_DEADLINE_SECONDS,
    )
    elapsed = time.monotonic() - started
    exit_line = next(line for line in result.stdout.splitlines() if line.startswith("exit="))
    return LimitedRun(
        stdout=result.stdout,
        exit_code=int(exit_line.removeprefix("exit=")),
        elapsed_seconds=elapsed,
        leftover_children=leftover_file.read_text().strip(),
    )


class TestRunWithWallClockLimit:
    """시도별 벽시계 제한 — 2026-10-03 장애(키체인 대기로 3일간 안 끝남)의 재발 방지."""

    @pytest.mark.parametrize("ignore_term", [False, True], ids=["term-respected", "term-ignored"])
    def test_overtime_kills_whole_descendant_tree(
        self, tmp_path: Path, pid_dir: Path, ignore_term: bool
    ) -> None:
        stub = _write_tree_stub(tmp_path, ignore_term=ignore_term)

        run = _run_limited(tmp_path, 1, BASH, str(stub), str(pid_dir))

        pids = _recorded_pids(pid_dir)
        assert len(pids) == len(PID_FILE_NAMES)
        assert _wait_until_dead(pids), "제한 초과 후에도 자손 프로세스가 살아 있다"
        assert run.elapsed_seconds < STUB_SLEEP_SECONDS / 2
        assert TIMEOUT_LINE_AT_ONE_SECOND in run.stdout.splitlines()
        assert run.exit_code != 0
        assert run.leftover_children == ""

    def test_timeout_output_is_classified_as_timeout(self, tmp_path: Path, pid_dir: Path) -> None:
        """러너가 남기는 줄과 판정 함수의 기대 형식이 어긋나지 않는지 이어서 확인한다."""
        stub = _write_tree_stub(tmp_path, ignore_term=False)

        run = _run_limited(tmp_path, 1, BASH, str(stub), str(pid_dir))

        assert _call("classify_attempt", run.stdout, str(tmp_path / "none.html")) == "timeout"

    def test_partial_line_output_does_not_swallow_timeout_marker(self, tmp_path: Path) -> None:
        """개행 없는 부분 줄을 낸 채 멈춰도 TIMEOUT 줄이 줄 시작에 와야 timeout으로 판정된다.

        붙어 버리면 줄 시작 고정 검사에 안 걸려 fail로 판정되고 무관한 재시도 경로를 탄다.
        """
        stub_command = f"printf '진행 중 3단계...'; sleep {STUB_SLEEP_SECONDS}"

        run = _run_limited(tmp_path, 1, BASH, "-c", stub_command)

        assert TIMEOUT_LINE_AT_ONE_SECOND in run.stdout.splitlines()
        assert _call("classify_attempt", run.stdout, str(tmp_path / "none.html")) == "timeout"

    @pytest.mark.parametrize("exit_code", [0, 7])
    def test_quick_command_is_untouched(self, tmp_path: Path, exit_code: int) -> None:
        run = _run_limited(tmp_path, 60, BASH, "-c", f"echo 정상 출력; exit {exit_code}")

        assert run.exit_code == exit_code
        assert "정상 출력" in run.stdout
        assert "TIMEOUT" not in run.stdout
        assert run.elapsed_seconds < WATCHDOG_TEST_DEADLINE_SECONDS / 2
        assert run.leftover_children == ""

    def test_termination_of_runner_kills_the_claude_tree(
        self, tmp_path: Path, pid_dir: Path
    ) -> None:
        """수동 실행 중 Ctrl-C·TERM이 오면 백그라운드 claude가 고아로 남아 이중 발행되면 안 된다."""
        stub = _write_tree_stub(tmp_path, ignore_term=False)
        script = (
            f"source {shlex.quote(str(RUNNER))}; "
            f"run_with_wall_clock_limit {BASH} {shlex.quote(str(stub))} {shlex.quote(str(pid_dir))}"
        )
        runner = Popen([BASH, "-c", script], env=_runner_env(600))
        try:
            deadline = time.monotonic() + PID_FILE_WAIT_SECONDS
            while len(_recorded_pids(pid_dir)) < len(PID_FILE_NAMES):
                assert time.monotonic() < deadline, "스텁이 pid를 기록하지 않았다"
                time.sleep(0.05)

            runner.send_signal(signal.SIGTERM)
            return_code = runner.wait(timeout=WATCHDOG_TEST_DEADLINE_SECONDS)
        finally:
            if runner.poll() is None:
                runner.kill()

        assert return_code == 130
        assert _wait_until_dead(_recorded_pids(pid_dir))


class TestProjectDirResolution:
    """저장소 위치는 러너가 자기 위치에서 구한다 — 작성자 홈 아래 고정 경로에 묶이면 안 된다."""

    def test_project_dir_is_derived_from_runner_location(self, tmp_path: Path) -> None:
        repository_root = tmp_path / "repo"
        scripts_directory = repository_root / "scripts"
        scripts_directory.mkdir(parents=True)
        copied_runner = scripts_directory / RUNNER.name
        shutil.copy(RUNNER, copied_runner)

        result = run_process(
            [BASH, "-c", f'source {shlex.quote(str(copied_runner))}; printf "%s" "$PROJECT_DIR"'],
            env={**os.environ, "SCHEDULED_PUBLISH_SOURCE_ONLY": "1"},
            capture_output=True,
            text=True,
            check=True,
        )

        assert Path(result.stdout).resolve() == repository_root.resolve()
