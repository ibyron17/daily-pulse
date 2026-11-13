#!/bin/bash
# Daily Pulse 정기 발행 러너 — launchd(com.daily-pulse.publish)가 매일 09:00에 호출.
#
# [작성자 운영 예시] 이 러너는 작성자 환경을 전제로 한 예시다. 다른 환경에서는 참고용으로 본다.
#   전제: macOS launchd / Claude 계정 한도 메시지의 리셋 시간대 Asia/Seoul
#   범용 본체는 pulse/ 와 발행 스킬 2종(daily-pulse-publish-daily·weekly)이다.
#
# 동작: scheduled-publish-prompt.md의 {{TODAY}}를 오늘 날짜로 치환해
#       claude -p (헤드리스)로 발행 파이프라인을 실행하고,
#       종료 마커(PULSE_PUBLISH_OK/PARTIAL/FAIL)로 성공 여부를 판정한다.
# 실패/부분 실패 시 macOS 알림을 띄운다. 로그: ~/Library/Logs/daily-pulse/
#
# 재시도 정책 — 대시보드가 발행되지 못한 실패만 1회 재시도한다.
#   * 부분 실패(대시보드는 발행됨): 재시도 없음. 재수집은 신규 작업 판정을
#     초기화하므로 남은 단계(주간 주입 등)만 수동 처리하는 편이 안전하다.
#   * 로그인 만료: 30분 후. 실측(2026-07-31) 09:00 실패 → 09:18 재로그인으로 복구.
#   * 사용량 한도: 로그가 알려주는 리셋 시각까지 대기 후. 실측(2026-08-05) 09:07
#     소진 시 리셋이 12pm이라, 30분 후 재시도는 실패가 확정돼 있었다.
#     리셋이 대기 상한을 넘으면(실측 2026-10-02: 이틀 뒤 리셋) 재시도를 포기한다.
#   * 시간 초과: 시도별 벽시계 제한(45분)을 넘기면 프로세스 트리를 정리하고 30분 후.
#     실측(2026-10-03) claude가 GUI 키체인 승인 대기에 걸려 3일간 안 끝났고, 그동안
#     launchd가 정기 실행을 시작하지 못했다(정상 실행은 약 10분).
# 수동 실행 중 대기는 Ctrl-C로 중단.
#
# 수동 실행:            scripts/scheduled-publish.sh
# 사전 점검만(발행 없음): scripts/scheduled-publish.sh --precheck (재시도 없음)
#
# 스케줄 (재)설치 — 저장소 루트에서. plist 는 자리표시자가 든 예시라 경로를 채워 렌더한다:
#   sed -e "s|/path/to/daily-pulse|$(pwd)|g" -e "s|/Users/USERNAME|$HOME|g" \
#     scripts/com.daily-pulse.publish.plist.example > ~/Library/LaunchAgents/com.daily-pulse.publish.plist
#   launchctl bootout gui/$(id -u)/com.daily-pulse.publish 2>/dev/null
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.daily-pulse.publish.plist

set -u

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 이 러너가 든 저장소 — 스크립트 위치에서 구한다(launchd 의 절대경로 실행과 테스트의 source 모두 성립).
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/daily-pulse"
PROMPT_FILE="$PROJECT_DIR/scripts/scheduled-publish-prompt.md"
MAX_TURNS=200
LOG_RETENTION_DAYS=30
RETRY_DELAY_SECONDS=1800
MARKER_SEARCH_LINES=30
# 한도 리셋 재시도: 리셋 정각에 바로 붙으면 아직 안 풀렸을 수 있어 버퍼를 둔다.
# 상한 6시간은 09:00 실행 기준 15:00까지라 다음 날 정기 실행과 겹치지 않는다.
# 리셋이 상한보다 멀면 상한까지 기다려도 실패가 확정이라 재시도하지 않는다.
LIMIT_RESET_BUFFER_SECONDS=120
LIMIT_MAX_WAIT_SECONDS=21600
LIMIT_FALLBACK_WAIT_SECONDS=3600
# 한도 메시지의 "(Asia/Seoul)" — 다른 시간대 표기는 이 러너의 로컬 시각으로 환산할 수 없다.
LIMIT_RESET_TIMEZONE="Asia/Seoul"
SECONDS_PER_DAY=86400
# 시도별 벽시계 제한. 정상 실행은 약 10분(실측)이라 45분이면 넉넉하다.
# 환경변수로 덮어쓸 수 있다(테스트에서 1~2초로 줄여 쓴다).
ATTEMPT_TIMEOUT_SECONDS="${ATTEMPT_TIMEOUT_SECONDS:-2700}"
# 제한 초과 시 TERM으로 정리할 시간을 주고, 남은 프로세스는 KILL한다.
WATCHDOG_POLL_SECONDS=1
KILL_GRACE_SECONDS=3
KILL_GRACE_POLL_SECONDS=0.2
INTERRUPTED_EXIT_CODE=130
# 한도 메시지의 리셋 표기. 괄호 그룹은 선택 그룹의 껍데기가 섞여 번호가 띄엄띄엄하다.
#   날짜 포함: 1=월 2=일 4=시 6=분(선택) 7=am/pm 9=시간대(선택)
#   시각만:    2=시 4=분(선택) 5=am/pm 7=시간대(선택)
RESET_WITH_DATE_PATTERN='resets[[:space:]]+([A-Za-z]{3,9})\.?[[:space:]]+([0-9]{1,2}),?[[:space:]]+(at[[:space:]]+)?([0-9]{1,2})(:([0-9]{2}))?[[:space:]]*([AaPp][Mm])([[:space:]]*\(([^)]+)\))?'
RESET_TIME_ONLY_PATTERN='resets[[:space:]]+(at[[:space:]]+)?([0-9]{1,2})(:([0-9]{2}))?[[:space:]]*([AaPp][Mm])([[:space:]]*\(([^)]+)\))?'

notify() {
  osascript -e "display notification \"$1 — 로그: $LOG_FILE\" with title \"Daily Pulse 정기 발행\"" 2>/dev/null
}

# 시도 결과를 ok|partial|timeout|login_expired|limit_exceeded|fail 로 판정한다.
# $1: 이번 시도의 로그 구간, $2: 오늘자 대시보드 경로(빈 문자열이면 파일 판정 생략)
classify_attempt() {
  local segment=$1
  local dashboard_file=$2

  if grep -q "PULSE_PUBLISH_OK" <<<"$segment"; then
    echo "ok"
    return
  fi
  if grep -q "PULSE_PUBLISH_PARTIAL" <<<"$segment"; then
    echo "partial"
    return
  fi
  # 마커가 없어도 오늘자 대시보드가 있으면 4단계까지는 성공한 것이다.
  # 한도 소진처럼 마커를 출력할 여력조차 없이 끊긴 실행을 미발행으로 오판하지 않는다.
  if [[ -n "$dashboard_file" && -f "$dashboard_file" ]]; then
    echo "partial"
    return
  fi
  # 멈춘 실행의 로그에는 로그인·한도 문구가 섞일 수 있어 그 검사보다 먼저 본다.
  # 러너가 직접 남긴 줄만 인정한다(줄 시작 고정) — claude 출력 중간의 같은 문구는 무시.
  if grep -q "^=== TIMEOUT: claude exceeded" <<<"$segment"; then
    echo "timeout"
    return
  fi
  if grep -qE "Not logged in|Please run /login" <<<"$segment"; then
    echo "login_expired"
    return
  fi
  # 실측(2026-10-02): "out of extra usage" 문구가 빠져 fail로 분류되고 무의미한 30분 재시도로 갔다.
  if grep -qE "hit your limit|usage limit|rate limit|out of extra usage" <<<"$segment"; then
    echo "limit_exceeded"
    return
  fi
  echo "fail"
}

# 12시간제 시각을 24시간제로 바꿔 출력한다. 12am은 0시, 12pm은 12시.
# $1: 시, $2: am|pm(소문자)
to_24_hour() {
  local hour=$1
  local meridiem=$2

  if [[ "$meridiem" == "pm" && "$hour" -ne 12 ]]; then
    hour=$((hour + 12))
  elif [[ "$meridiem" == "am" && "$hour" -eq 12 ]]; then
    hour=0
  fi
  echo "$hour"
}

# 영문 월 이름(약어·전체, 대소문자 무관)을 1~12로 바꿔 출력한다. 월 이름이 아니면 실패한다.
month_number() {
  local month_name
  month_name=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')

  case "$month_name" in
    jan | january) echo 1 ;;
    feb | february) echo 2 ;;
    mar | march) echo 3 ;;
    apr | april) echo 4 ;;
    may) echo 5 ;;
    jun | june) echo 6 ;;
    jul | july) echo 7 ;;
    aug | august) echo 8 ;;
    sep | sept | september) echo 9 ;;
    oct | october) echo 10 ;;
    nov | november) echo 11 ;;
    dec | december) echo 12 ;;
    *) return 1 ;;
  esac
}

# 리셋 표기를 "월 일 시 분"(24시간제) 한 줄로 풀어 출력한다. 날짜 없는 표기는 월·일이 0이다.
# 읽을 수 없거나 괄호 안 시간대가 LIMIT_RESET_TIMEZONE이 아니면 아무것도 출력하지 않는다.
parse_reset_clause() {
  local segment=$1
  local month=0 day=0 hour minute meridiem timezone

  if [[ "$segment" =~ $RESET_WITH_DATE_PATTERN ]]; then
    month=$(month_number "${BASH_REMATCH[1]}") || return 0
    day=$((10#${BASH_REMATCH[2]}))
    if [[ "$day" -lt 1 || "$day" -gt 31 ]]; then
      return 0
    fi
    hour=$((10#${BASH_REMATCH[4]}))
    minute=${BASH_REMATCH[6]:-00}
    meridiem=${BASH_REMATCH[7]}
    timezone=${BASH_REMATCH[9]:-$LIMIT_RESET_TIMEZONE}
  elif [[ "$segment" =~ $RESET_TIME_ONLY_PATTERN ]]; then
    hour=$((10#${BASH_REMATCH[2]}))
    minute=${BASH_REMATCH[4]:-00}
    meridiem=${BASH_REMATCH[5]}
    timezone=${BASH_REMATCH[7]:-$LIMIT_RESET_TIMEZONE}
  else
    return 0
  fi
  if [[ "$timezone" != "$LIMIT_RESET_TIMEZONE" ]]; then
    return 0
  fi

  meridiem=$(printf '%s' "$meridiem" | tr '[:upper:]' '[:lower:]')
  hour=$(to_24_hour "$hour" "$meridiem")
  if [[ "$hour" -gt 23 ]]; then
    return 0
  fi
  echo "$month $day $hour $minute"
}

# 로컬 시각의 epoch을 출력한다. $1: YYYY-MM-DD, $2: 시, $3: 분. 해석할 수 없으면 빈 출력.
local_epoch() {
  date -j -f "%Y-%m-%d %H:%M:%S" "$1 $(printf '%02d:%s:00' "$2" "$3")" +%s 2>/dev/null
}

# 날짜 없는 표기("resets 3am")의 리셋 epoch. 이미 지난 시각이면 다음 날 같은 시각이다.
# $1: 시, $2: 분, $3: 기준 epoch
reset_epoch_without_date() {
  local hour=$1 minute=$2 base_epoch=$3
  local target_epoch

  target_epoch=$(local_epoch "$(date -r "$base_epoch" +%Y-%m-%d)" "$hour" "$minute")
  if [[ -n "$target_epoch" && "$target_epoch" -le "$base_epoch" ]]; then
    target_epoch=$((target_epoch + SECONDS_PER_DAY))
  fi
  echo "$target_epoch"
}

# 날짜 있는 표기("resets Oct 4 at 8am")의 리셋 epoch. 올해 그 시각이 이미 지났으면 내년이다.
# $1: 월, $2: 일, $3: 시, $4: 분, $5: 기준 epoch
reset_epoch_with_date() {
  local month=$1 day=$2 hour=$3 minute=$4 base_epoch=$5
  local year target_epoch

  year=$(date -r "$base_epoch" +%Y)
  target_epoch=$(local_epoch "$(printf '%04d-%02d-%02d' "$year" "$month" "$day")" "$hour" "$minute")
  if [[ -n "$target_epoch" && "$target_epoch" -le "$base_epoch" ]]; then
    year=$((year + 1))
    target_epoch=$(local_epoch "$(printf '%04d-%02d-%02d' "$year" "$month" "$day")" "$hour" "$minute")
  fi
  echo "$target_epoch"
}

# 한도 메시지("... resets 12pm (Asia/Seoul)", "... resets Oct 4 at 8am (Asia/Seoul)")의
# 리셋 시각까지 대기할 초를 계산한다. 상한(LIMIT_MAX_WAIT_SECONDS)으로 자르지 않는다 —
# 상한을 넘는지는 호출부가 exceeds_limit_max_wait로 판정해 재시도를 포기한다.
# $1: 로그 구간, $2: 기준 epoch(생략 시 현재). 파싱 실패·비정상 표기는 폴백 대기로 떨어진다.
parse_limit_reset_delay() {
  local segment=$1
  local base_epoch=${2:-$(date +%s)}
  local month day hour minute target_epoch

  read -r month day hour minute <<<"$(parse_reset_clause "$segment")"
  if [[ -z "$minute" ]]; then
    echo "$LIMIT_FALLBACK_WAIT_SECONDS"
    return
  fi

  if [[ "$month" -eq 0 ]]; then
    target_epoch=$(reset_epoch_without_date "$hour" "$minute" "$base_epoch")
  else
    target_epoch=$(reset_epoch_with_date "$month" "$day" "$hour" "$minute" "$base_epoch")
  fi
  if [[ -z "$target_epoch" ]]; then
    echo "$LIMIT_FALLBACK_WAIT_SECONDS"
    return
  fi
  echo $((target_epoch - base_epoch + LIMIT_RESET_BUFFER_SECONDS))
}

# 계산된 대기($1, 초)가 상한을 넘으면 참 — 상한까지만 기다려도 리셋 전이라 재시도가 실패한다.
exceeds_limit_max_wait() {
  [[ "$1" -gt "$LIMIT_MAX_WAIT_SECONDS" ]]
}

# 프로세스와 그 자손의 pid를 자식 먼저, 루트 마지막 순서로 한 줄씩 출력한다.
list_process_tree() {
  local parent_pid=$1
  local child_pid

  for child_pid in $(pgrep -P "$parent_pid" 2>/dev/null); do
    list_process_tree "$child_pid"
  done
  echo "$parent_pid"
}

# 인자로 받은 pid 중 아직 살아 있는 것만 출력한다.
filter_alive_pids() {
  local pid

  for pid in "$@"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
    fi
  done
}

# 프로세스 트리 전체를 TERM → 유예 → KILL 로 정리한다.
# 부모가 먼저 죽으면 자식이 init에 입양돼 트리를 못 찾으므로 pid 목록은 죽이기 전에 확보한다.
terminate_process_tree() {
  local tree_pids alive_pids deadline

  tree_pids=$(list_process_tree "$1")
  kill -TERM $tree_pids 2>/dev/null
  deadline=$((SECONDS + KILL_GRACE_SECONDS))
  alive_pids=$(filter_alive_pids $tree_pids)
  while [[ -n "$alive_pids" && "$SECONDS" -lt "$deadline" ]]; do
    sleep "$KILL_GRACE_POLL_SECONDS"
    alive_pids=$(filter_alive_pids $alive_pids)
  done
  if [[ -n "$alive_pids" ]]; then
    kill -KILL $alive_pids 2>/dev/null
  fi
}

# 명령을 벽시계 제한(ATTEMPT_TIMEOUT_SECONDS) 안에서 실행하는 감시자 — macOS엔 GNU timeout이 없다.
# 제한을 넘기면 자손 트리까지 정리하고 TIMEOUT 줄을 남긴다. 종료 코드는 명령의 것을 그대로
# 돌려준다(정리된 경우 128+시그널). 별도 감시 프로세스를 두지 않고 러너가 직접 경과를 점검하므로
# 남는 sleep·플래그 파일이 없고, 시간은 $SECONDS(실제 시각 기준)라 절전 중 흐른 시간도 잡힌다.
# 단점: Mac이 실행 도중 절전했다가 깨어나면 멈춘 적 없는 정상 claude도 깨어난 직후 제한 초과로
# TERM될 수 있다. 이후 판정이 대시보드 있으면 partial, 없으면 timeout→30분 후 재시도라 복구된다.
run_with_wall_clock_limit() {
  local command_pid started_at exit_code

  "$@" &
  command_pid=$!
  # 러너가 INT/TERM으로 중단되면 백그라운드 claude가 고아로 남아 다음 실행과 이중 발행될 수 있다.
  trap "terminate_process_tree $command_pid; exit $INTERRUPTED_EXIT_CODE" INT TERM
  started_at=$SECONDS
  while kill -0 "$command_pid" 2>/dev/null; do
    if [[ $((SECONDS - started_at)) -ge "$ATTEMPT_TIMEOUT_SECONDS" ]]; then
      terminate_process_tree "$command_pid"
      # 앞의 \n: claude가 개행 없는 부분 줄을 낸 채 멈췄으면 TIMEOUT 줄이 거기에 붙어
      # 줄 시작 고정 검사(classify_attempt)에 안 걸려 fail로 오판된다.
      printf '\n=== TIMEOUT: claude exceeded %ss, process tree killed ===\n' "$ATTEMPT_TIMEOUT_SECONDS"
      break
    fi
    sleep "$WATCHDOG_POLL_SECONDS"
  done
  wait "$command_pid"
  exit_code=$?
  trap - INT TERM
  return "$exit_code"
}

# 시도 결과는 전역으로 전달한다 — 대기 시간 계산에 직전 시도의 로그 구간이 필요하다.
attempt_result=""
attempt_segment=""

run_publish_attempt() {
  local attempt_number=$1
  local start_line dashboard_file
  start_line=$(($(wc -l <"$LOG_FILE") + 1))
  {
    echo "=== daily-pulse publish start: $(date +%Y-%m-%dT%H:%M:%S%z) (args: $RUN_MODE, attempt: $attempt_number) ==="
    run_with_wall_clock_limit claude -p "$PROMPT" \
      --permission-mode acceptEdits \
      --allowedTools "$ALLOWED_TOOLS" \
      --max-turns "$MAX_TURNS"
    echo "=== claude exit code: $? / end: $(date +%Y-%m-%dT%H:%M:%S%z) ==="
  } >>"$LOG_FILE" 2>&1
  # 하루 로그 파일을 시도들이 공유하므로 이번 시도 구간만 검사한다
  attempt_segment=$(tail -n +"$start_line" "$LOG_FILE" | tail -"$MARKER_SEARCH_LINES")
  # precheck는 발행하지 않는다 — 이전에 발행된 대시보드를 성공 근거로 삼으면 안 된다
  dashboard_file=""
  if [[ "$RUN_MODE" != "--precheck" ]]; then
    dashboard_file="$PROJECT_DIR/reports/pulse-$TODAY.html"
  fi
  attempt_result=$(classify_attempt "$attempt_segment" "$dashboard_file")
}

# 판정 함수만 테스트에서 가져다 쓰기 위한 가드 (tests/test_scheduled_publish_runner.py)
if [[ "${SCHEDULED_PUBLISH_SOURCE_ONLY:-}" == "1" ]]; then
  return 0 2>/dev/null || exit 0
fi

mkdir -p "$LOG_DIR"
TODAY=$(date +%F)
LOG_FILE="$LOG_DIR/publish-$TODAY.log"
RUN_MODE="${1:-none}"
touch "$LOG_FILE"

cd "$PROJECT_DIR" || exit 1

if [[ "$RUN_MODE" == "--precheck" ]]; then
  PROMPT="헤드리스 사전 점검만 수행하고 종료한다. 아무 파일도 수정·생성하지 말 것:
1. .venv/bin/python -m pulse.publish token status 실행 결과 보고 (gitlab ✓ 여부)
2. 성공이면 마지막 줄에 PULSE_PUBLISH_OK, 아니면 PULSE_PUBLISH_FAIL: <사유> 출력"
else
  PROMPT=$(sed "s/{{TODAY}}/$TODAY/g" "$PROMPT_FILE")
fi

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,TodoWrite,Skill"

run_publish_attempt 1

find "$LOG_DIR" -name 'publish-*.log' -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null

retry_delay=$RETRY_DELAY_SECONDS

case "$attempt_result" in
  ok) exit 0 ;;
  partial)
    notify "부분 실패 — 대시보드는 발행됨(재수집 불필요). 로그에서 남은 단계 확인 필요"
    exit 1
    ;;
  login_expired)
    notify "Claude 로그인 만료 — 터미널에서 claude /login 실행 필요. 30분 후 1회 재시도"
    ;;
  timeout)
    # 대시보드가 미발행이라 재시도 흐름은 fail과 같다.
    notify "시간 초과($((ATTEMPT_TIMEOUT_SECONDS / 60))분) — 프로세스 정리함, 30분 후 1회 재시도"
    ;;
  limit_exceeded)
    retry_delay=$(parse_limit_reset_delay "$attempt_segment")
    if exceeds_limit_max_wait "$retry_delay"; then
      notify "사용량 한도 초과 — 리셋이 $((retry_delay / 3600))시간 뒤라 재시도하지 않음. 한도 회복 후 scripts/scheduled-publish.sh 수동 실행 필요"
      exit 1
    fi
    notify "사용량 한도 초과 — 리셋까지 약 $((retry_delay / 60))분 대기 후 1회 재시도"
    ;;
  *)
    notify "발행 실패 — 30분 후 1회 재시도"
    ;;
esac

if [[ "$RUN_MODE" == "--precheck" ]]; then
  exit 1
fi

sleep "$retry_delay"

# 한도 리셋 대기는 몇 시간에 이른다 — 그 사이 수동 발행이 끝났을 수 있다.
# 재수집은 신규 작업 판정을 초기화하므로 이미 발행됐으면 재시도하지 않는다.
if [[ -f "$PROJECT_DIR/reports/pulse-$TODAY.html" ]]; then
  notify "대기 중 대시보드가 발행돼 재시도를 건너뜁니다 — 로그에서 남은 단계 확인 필요"
  exit 1
fi

run_publish_attempt 2

case "$attempt_result" in
  ok)
    notify "재시도 성공 — 발행 완료"
    exit 0
    ;;
  partial)
    notify "재시도: 부분 실패 — 대시보드는 발행됨. 로그에서 남은 단계 확인 필요"
    exit 1
    ;;
  timeout)
    notify "재시도도 시간 초과 — 로그 확인 필요"
    exit 1
    ;;
  login_expired)
    notify "재시도 실패 — 로그인 만료 지속. claude /login 후 scripts/scheduled-publish.sh 수동 실행 필요"
    exit 1
    ;;
  limit_exceeded)
    notify "재시도 실패 — 사용량 한도 지속. 한도 회복 후 scripts/scheduled-publish.sh 수동 실행 필요"
    exit 1
    ;;
  *)
    notify "재시도 실패 — 로그 확인 필요"
    exit 1
    ;;
esac
