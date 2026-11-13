---
name: daily-pulse-publish-weekly
description: 팀 깃 활동을 주간 기준으로 수집·렌더하고 AI 흐름 요약을 얹어 주간 대시보드를 발행한다(배포는 별도).
---

## When to Activate

- "주간 발행해줘"/"주간 브리핑 만들어줘" 등 주간 대시보드 발행 요청
- **영업일 첫 실행에만 자동 발행**(월요일이 공휴일이면 그 주 다음 영업일). 같은 주에는 기존 대시보드를 재활용하고,
  다시 내려면 `--force-weekly` — 조회 기간은 항상 그 주 월요일 00:00 기준 지난주 월~일, 제목 날짜는 실행일

## Scope Boundaries

- 주간 발행까지만. 대시보드 파일의 외부 배포(호스팅 업로드 등)는 하지 않는다.
- 개인 실적 지표(커밋수·라인수 랭킹) 및 요약 내 개인 이름 금지.
- LLM API 호출·anthropic 라이브러리 사용 금지(요약은 이 대화의 Claude가 직접 작성).

## Publish Workflow

1. **토큰 확인 (계층 폴백: env → keyring → gh)**:
   - `python -m pulse.publish token status` 실행해 출처(env/keyring/gh/none) 표시
   - 필요한 provider(GitLab/GitHub)의 토큰이 없으면:
     - 사용자에게 토큰 값을 채팅에서 받은 후
     - `printf '%s' "$TOKEN_VALUE" | python -m pulse.publish token set --provider gitlab` 실행
     - 이렇게 하면 OS 비밀 저장소(keyring)에 저장돼 다음부터 자동 로드됨
     - 또는 환경변수 `export GITLAB_TOKEN="..."` 설정해도 됨 (최우선)

2. **발행 게이트 확인**:
   - 첫 수집 명령에서 `published_weekly: false`가 나오면:
     ```
     이번 주 주간은 이미 발행됐거나 오늘이 영업일이 아니어서 기존 주간 대시보드를 재활용합니다.
     다시 발행하려면 --force-weekly 옵션을 지시하세요
     (기간은 지난주 월~일, 제목 날짜는 오늘).
     ```
     안내 후 중단.
   - 사용자가 강제 발행을 지시하면, 다시 실행 시 `--force-weekly` 붙여 재실행.
   - 게이트는 **영업일(월~금, 공휴일·`extra_holidays` 제외) ∧ 이번 주 미발행**이다. 월요일이 공휴일이면 그날은
     주간을 내지 않고 그 주 다음 영업일에 낸다. 「이번 주 발행됨」은 `data/weekly_publish/latest.json`의
     조회 기간 끝(`window_end`)이 이번 주 월요일 00:00 이상인지로 코드가 판단한다(실행 로그의 「주간 발행 판단」 한 줄).

3. **대상 레포 확인**: config의 `repos`를 읽어 대화창에 목록을 표로 보여주고 진행한다
   (nickname·url·provider·lookback_hours·team_name). 목적은 "무엇을 수집할지"를
   실행 직전에 눈으로 확인시키는 것. 레포가 예상과 다르면 사용자가 중단·수정을
   요청할 수 있게 한다. 표시만 하고 진행하며, 별도 승인 대기는 하지 않는다
   (자동 스케줄 실행 시에는 로그로 남는다).

4. **수집 실행**: 
   ```bash
   python -m pulse.publish collect --config config.yaml --period weekly
   ```
   
   또는 강제 발행:
   ```bash
   python -m pulse.publish collect --config config.yaml --period weekly --force-weekly
   ```
   
   **날짜 지정 (선택사항)**: 특정 날짜/시각 기준으로 수집하려면:
   ```bash
   python -m pulse.publish collect --config config.yaml --period weekly \
     --now "2026-07-27T00:00:00+09:00" [--force-weekly]
   ```
   - `--now`: ISO 8601 타임스탬프 (**타임존 필수** — 영업일·이번 주 발행 여부 판정도 이 시각 기준)
   - `--force-weekly`: 게이트(영업일·이번 주 미발행)를 우회해 이번 주 주간을 다시 발행 (옵션, **`--period weekly` 전용**)
   - 생략 시: 현재 시각 기준 (기존 동작)
   - **날짜만 전달받은 경우**: 사용자/cowork가 조회 날짜만 넘기면(예: "2026-07-27")
     스킬이 `{날짜}T00:00:00+09:00`(config.timezone, 달력 정렬) 형식으로 변환해 `--now`로 전달한다.
     그 날짜가 영업일이고 이번 주 주간이 아직 없으면 게이트가 자동 통과된다. 아니면 `--force-weekly`가 필요하다.
   - **정기 실행과 같은 날 수동으로 돌릴 때는 `--now <오늘>T00:00:00+09:00`**을 쓴다. 낮 시각(예: 월요일 09:00)을 그대로
     주면 그날 수집 기록(raw)이 낮 시각 기준으로 남아 다음 날 일간의 「신규」 판정 기준이 반나절 움직인다.
   - **주간 조회 기간은 코드가 그 주 월요일 기준으로 맞춘다**: `--now`가 어느 요일·시각이든 발행일이 속한 주의 월요일 00:00을 A라 하면
     조회 기간은 A의 7일 전 월요일 00:00 ~ A(월~일, 주말 커밋 포함)이다. 이름표(`report_date`·`published_at`·
     파일명 `pulse-weekly-<날짜>.html`)는 **실행일**(`--now`의 날짜)이다.
     예: `--now "2026-10-06T00:00:00+09:00"`(화, 월요일이 공휴일이라 보완 발행) → 기간 2026-09-28 ~ 2026-10-04,
     파일 `pulse-weekly-2026-10-06.html`. 그래서 날짜를 월요일로 직접 계산해 넘길 필요가 없다.
   - **`--period weekly` 외(`both`·`daily`)에는 `--force-weekly`를 붙이지 않는다**: 시각과 무관하게 거부(exit 2)되고
     `--period weekly`로 따로 실행하라는 안내가 나온다. `--period both`는 일간과 함께, 게이트를 통과하는 날에만 주간을 발행한다.
   - **`--force-weekly` 강제 재발행은 운영 기록(일별 수집 원본·브랜치 스냅샷·진행 일수 등록부·브랜치 이력·보존 정리)을
     쓰지 않는다.** 그날의 운영 기록은 정기 실행 몫이다. 지난 날짜를 재현하려면 `--ad-hoc`을 쓴다(`--now`만 과거로 주면
     그 날짜의 운영 기록을 덮어쓴다). 주간 신규 브랜치는 그 주 월요일 스냅샷이 없으면(월요일 실행 누락·공휴일) 그 이후
     가장 이른 스냅샷과 비교하므로 하루 남짓 넓게 잡힐 수 있다.
   - 한 주(월~금)가 통째로 쉬는 주에는 그 직전 주의 주간이 만들어지지 않는다(다음 주 월요일에 휴무 주 주간이 나간다).
   
   비정상 종료 시 로그 해설.

5. **요약 작성(레포별)**: stdout JSON의 `weekly.repos`와 그 레포의 `weekly.groups` seed를 읽고 **레포마다** 쓴다.
   요약은 **두 문단**이다 — ① 흐름 문단 ② 개선점 문단(쓰는 사람 관점에서 좋아진 점 = 개선 효과, 근거가 있을 때만, 5d).
   이 문서 예시의 이름(`샘플 …`·`sample-…`)·이슈 키·라이브러리명은 설명용 가상 값이다 — 실제 요약·제목·분석에는 쓰지 말고 collect 데이터에 있는 실제 어휘를 쓴다.
   - **문단 구분 = 빈 줄 1개(`\n\n`)**, 문단 안은 **문장마다 줄바꿈(`\n`)**(줄마다 불릿으로 렌더).
     이어붙인 산문 한 줄로 쓰면 문단으로만 표시되니 반드시 줄바꿈으로 나눈다.
     흐름 문단 안에는 빈 줄을 넣지 않는다 — 첫 빈 줄 뒤는 전부 개선점 문단으로 렌더된다.
     개선점 문단이 없으면 빈 줄도 쓰지 않는다(소제목 「개선점」은 렌더러가 붙인다 — 직접 쓰지 않는다).
   - 한국어, 서술형(~습니다), 한 줄 = 한 문장 90자 안쪽. 개인 이름·개인별 수치 금지.
     함수·파일·변수명·해시 금지, 이슈 키는 괄호 참조로만. 과한 기술 용어는 쉬운 말로 풀어 쓴다.
   - 다음 주 예정(있으면): 열려 있는 MR의 리뷰·병합 대기, 진행 중인 단계처럼 seed에서 읽히는 후속
     작업만 흐름 문단 끝에 쓴다. 근거 없는 계획은 지어내지 않는다.
   - 분량(활동 그룹 = 이 레포 그룹 중 `commit_count>0`이거나 `mrs`가 있는 그룹, 0커밋 신설 브랜치는 세지 않는다).
     **상한 흐름 8줄·개선점 4줄 — 채울 칸이 아니다.**

     | 규모 | 흐름 문단 | 개선점 문단 |
     |---|---|---|
     | 활동 없음 (레포 `commit_count`·`mr_count` 0) | "조회 기간 내 특이 활동이 없습니다." 1줄 | 없음 |
     | 활동 그룹 1~2 | 3~4줄 | 0~2줄 |
     | 활동 그룹 3~5 | 4~6줄 | 0~3줄 |
     | 활동 그룹 6+ | 6~8줄 | 0~4줄 |
     | **상한** | **8줄** | **4줄** |

   - 흐름 문단에 담을 것(비중 큰 것부터):

     | 순서 | 담을 것 | 근거 seed | 쓰는 법 | 하지 말 것 |
     |---|---|---|---|---|
     | 1 | (주간 첫 줄) 규모·갈래 | 레포 `commit_count`·`mr_count`, 활동 그룹 수 | "커밋 31건·MR 4건, 세 갈래" | 개인별 수치 |
     | 2 | 기능 그룹 진행 단계 | `stage`, `branch_history.started_on`/`total_days`, `lifecycle.current_stage_days`, `mrs[].state`·`is_draft`·`review_comment_count` | "대기자 알림 기능은 시작 15일째 개발 중" | `branch_history` 없으면 "N일째 개발"로 단정하지 않고 "관측 N일째"로 |
     | 3 | 이번 기간 내용 | `commit_titles`, `mrs[].title`/`description`, `changed_files_summary`, `issue_keys` | 쉬운 말, 이슈 키는 괄호 참조 | 함수·파일·변수명, 해시 |
     | 4 | 라인·승격 위치 | 레포 `release_train`, 라인 그룹 `commit_titles` | "develop→devqa 03-10, sqa·master 03-04" 날짜 단위 | 비율, 기능의 사다리 위치 추론 |
     | 5 | 신규 작업 | 레포 `new_work_count`, `lifecycle.first_seen` | "신규 작업 2건" | |
     | 6 | 정체·리스크 (`⚠ ` 줄) | `warning_titles`, `branch_history.behind_count`·`silent_gap_days`·`fix_surge`, revert 커밋 | 핵심 1~2건만 ⚠ 줄로 | 방치 브랜치 30건 나열 |
     | 7 | 제품 변경 없음 | (변경이 전부 내부 정비여서 생략할 때만) | "모두 내부 정비로, 쓰는 사람이 체감하는 기능 변화는 없습니다." | 개선점을 지어내기, 뺀 항목이 있는데 이 문장 쓰기 |

   - 활동이 없는 레포는 "조회 기간 내 특이 활동이 없습니다." 한 줄(개선점 문단 없음).

5b. **그룹(프로젝트/기능) 제목·분석 작성**: stdout JSON의 `weekly.groups`를 읽고
   **cached=false인 그룹만** 제목과 분석을 작성한다. 각 그룹 seed 스키마:
   - `name`, `stage` — 기본
   - `commit_titles` — 최대 50건 (기존 3 → 확대)
   - `mrs` — MR 정보 배열 (신규): 각 항목 `{title, state, target_branch, is_draft, description, review_comment_count}`, 최대 20건. **merged 포함**
   - `branch_names`, `changed_files_count`, `changed_files_summary` — 기존
   - `issue_keys` — 추출된 이슈 키들 (신규, 예: `["DOCS-123", "B20C-45"]`)
   - `scope_distribution` — 영역별 커밋 분포 (신규, 예: `{"auth": 5, "api": 3}`)
   - `group_kind` — "feature" 또는 "line" (신규, 기본 "feature")
   - `commit_count` — 그룹 커밋 수. `commit_count>0`이거나 `mrs`가 있으면 5단계 분량의 "활동 그룹"이다
   - `branch_history`, `lifecycle` — 브랜치 생애·현재 단계 체류 정보(있는 그룹만)
   - `cached`, `cached_title`, `cached_analysis` — 캐시 메타
   
   - `cached: true` 그룹 → 이미 캐시된 분석이 있음. summary.json에서 **생략 가능** (inject가 자동 주입).
     캐시 내용이 부적절하면 다시 작성하면 덮어써짐.
   - `cached: false` 그룹 → 새로 작성 필요.
   
   **title**: 브랜치명 대신 무슨 프로젝트/기능인지 한눈에 아는 한국어 제목(예: "AI 어시스턴트 통합").
   제목을 채우면 카드에서 브랜치명은 숨겨지고 이 제목이 표시된다.
   - **`group_kind == "line"`인 그룹은 부제를 붙이지 않는다** — 라인 이름만 쓴다
     (예: "샘플 develop 라인" ○ / "샘플 develop 라인 — 워드 서식·샘플 스튜디오·AI 템플릿" ✕).
     라인 표의 제목 칸은 폭이 고정(최대 14rem)이라 긴 제목은 한 줄로 잘려 뒷부분이 보이지 않는다.
     그 주의 내용은 부제가 아니라 analysis에 쓴다.
   
   **analysis**: 무슨 작업인지·이번 주에 한 일·현재 단계·주의점을 **줄바꿈으로 구분한 불릿**으로 쓴다
   (줄바꿈이 자동 `<ul><li>`로 렌더된다 — 한 덩어리 산문으로 이어 쓰지 않는다).
   한국어, 서술형(~습니다), 한 줄 = 한 가지 사실 90자 안쪽. 개인 이름 금지.
   기능 그룹과 라인 그룹(`group_kind=="line"`, 릴리즈·검증 라인) 모두 같은 규칙이다.
   **상한 10줄 — 채울 칸이 아니다.** 분량은 그룹 규모(`commit_count`·`mrs` 개수)에 맞춘다:

   <!-- 분량 표·담을 것 표·가드는 daily 스킬 4b와 같은 구조로 유지한다 (수치·예시만 기간별) -->

   | 그룹 규모 | 줄 수 |
   |---|---|
   | 활동 없음 (`commit_count` 0 · `mrs` 없음) | 1~2줄 |
   | 소규모 (커밋 1~5 · MR 0~1) | 3~5줄 |
   | 중규모 (커밋 6~20 또는 MR 2~4) | 5~7줄 |
   | 대규모 (커밋 21+ 또는 MR 5+) | 7~10줄 |
   | **상한** | **10줄** |

   커밋 수와 MR 수가 서로 다른 구간에 걸리면 **큰 쪽 구간**을 기준으로 한다(커밋 0에 MR만 있는 그룹은 MR 수로 판단).

   담을 것(비중 큰 것부터, 근거가 있는 것만):

   | 순서 | 담을 것 | 근거 seed | 하지 말 것 |
   |---|---|---|---|
   | 1 | 무슨 작업인지 | 그룹 이름, `commit_titles`, `mrs[].title`/`description` | 그룹 이름 그대로 복창 |
   | 2 | 이번 주에 한 일 — **영역별로 묶어** 줄마다 하나씩 | `scope_distribution`, `changed_files_summary`, `commit_titles`, `issue_keys`(괄호 참조) | 커밋 제목을 그대로 나열, 함수·파일·변수명 |
   | 3 | MR 상태 | `mrs[].state`·`is_draft`·`target_branch`·`review_comment_count` | MR 제목 나열 |
   | 4 | 현재 단계·진행 기간 | `stage`, `branch_history`, `lifecycle` | `branch_history` 없이 "N일째"로 단정(없으면 "관측 N일째") |
   | 5 | (라인 그룹) 반영 위치·시점 | 라인 그룹 `commit_titles`, 레포 `release_train` | 기능의 사다리 위치 추론, 이 라인 그룹이 출발·도착인 칸 밖의 사다리 전체 반복(레포 요약이 맡는다) |
   | 6 | 주의점 (`⚠ ` 줄, **최대 2줄**) | `branch_history.behind_count`·`silent_gap_days`·`fix_surge`, revert 커밋 제목 | 레포 단위 `warning_titles`를 그룹 줄로 끌어오기, 방치 항목 나열 |
   | 7 | 다음 주 예정(대기 상태) | seed로 확인되는 것만(열린 MR의 리뷰·병합 대기, `target_branch` 등) | 근거 없는 계획 |

   - seed에 없는 진행률·일정·수치·의도는 쓰지 않는다. 줄을 채우려고 같은 내용을 되풀이하거나 커밋 제목을
     옮겨 적지 않는다 — 근거가 모자라면 표의 하한(또는 그 아래)에서 멈춘다.
   - 카드에 이미 표시되는 정보는 숫자를 되풀이하지 말고 그 의미(무엇이 어디까지 됐는지)를 쓴다 — 기능 카드는 규모 수치·MR 이력·
     이슈 키·생애 타임라인이, 라인 행은 규모 수치·MR 이력이 표시된다. 표시되지 않는 것(라인 행의 이슈 키·생애)은 분석에 쓴다.
   - 커밋 제목과 함께 **changed_files_summary를 근거로 참조**: 변경 파일·영역·규모를 보고
     "무슨 작업인지"를 더 구체적으로 서술 (예: 변경 파일이 editor/table 계열에 집중 → "표 편집 코어 중심 작업")
   - `changed_files_summary: null`이면 기존처럼 커밋 제목만으로 작성 (우아한 저하)
   - `cached: true` 그룹의 분석은 그대로 유지된다 — 새 분량 기준은 새로 쓰는(`cached: false`) 그룹부터 적용된다.
   - 예(기능 그룹, 커밋 14건·MR 2건 → 중규모 6줄):
     ```
     문서 안에서 AI와 대화하는 기능을 만드는 작업으로, 시작 15일째 개발 중입니다.
     대화 입력창과 응답 표시 영역의 표시 오류를 정리했습니다(DOCS-123).
     대화 기록을 저장하는 화면 구조를 새로 나눴습니다.
     설정 화면에 모델 선택 항목을 추가했습니다.
     MR 2건 중 1건은 병합됐고 1건은 리뷰를 기다리고 있습니다.
     ⚠ 통합 브랜치보다 5커밋 뒤처져 있습니다.
     ```
   - 예(라인 그룹, 커밋 4건 → 소규모 3줄):
     ```
     붙여넣기·도형 서식 관련 수정이 중심입니다(B20C-45).
     AI 템플릿 화면 구조 정리 1건이 함께 반영됐습니다.
     설정 화면 문구 수정 1건이 포함돼 있습니다.
     ```
   
   - 그룹 키는 seed의 키(`org/repo::group_name`)를 그대로 사용한다.
   - 일부 그룹만 채워도 안전하다(미작성 그룹은 카드에 브랜치명만 표시되는 우아한 저하).

5c. **강조 마커(선택, 레포 요약·그룹 분석 공통)**: 확인·결정·대응이 필요한 내용만 강조한다.
   - 구/단어 강조: `**정체된 MR 재검토 필요**` → 대시보드 형광펜으로 렌더
   - 줄 전체 주의: 불릿 줄을 `⚠ `로 시작 → 대시보드에서 주의 콜아웃 스타일로 렌더
   - **한도: 그룹 분석당 인라인 강조 최대 1곳, 레포 요약당 최대 2곳.** 단순 진행
     상황은 강조하지 않는다 — 모두 강조하면 아무것도 강조되지 않는다.
   - 위 한도(레포 요약당 최대 2곳)는 `**` 인라인 강조만 센다(`⚠ ` 줄 접두는 세지 않는다).
     그룹 분석의 ⚠ 줄은 5b 기준 최대 2줄이며 인라인 강조 1곳 한도와 별개다.
     **개선점 문단에는 마커(`**`·`⚠`)를 쓰지 않는다** — 마커는 확인·대응이 필요하다는
     표식인데 개선점은 대응 대상이 아니다.
   - title에는 마커를 쓰지 않는다(들어와도 렌더러가 제거). 메신저 스니펫 등 평문
     출력에서는 마커가 자동 제거되므로 별도 처리 불필요.

5d. **개선점 문단 작성(레포 요약의 둘째 문단)**: 쓰는 사람 관점에서 **좋아진 점(개선 효과)**만 쓴다.
   「개선점」은 "고쳐야 할 점"이 아니다 — 제품을 쓰는 사람에게 무엇이 좋아지는지를 적는 문단이다.
   이슈·결정 요청은 섞지 않는다(그것은 흐름 문단의 `⚠ ` 줄·강조가 맡는다).
   <!-- 이 절은 daily 스킬 4d와 같게 유지한다 (규칙 블록 동일, 예시만 기간별) -->

   **규칙** (daily 스킬 4d와 weekly 스킬 5d 공통)
   - 읽는 사람은 코드를 모르는 판단자다. 줄의 주어는 시스템이 아니라 **제품을 쓰는 사람**이다 —
     그 사람이 겪던 일이 어떻게 달라졌는지를 쓴다: 기다림·다시 만들기·수작업 보정·쓸 수 없는 결과·
     못 하던 일·막힌 업무.
   - 판정 질문: "이 줄을 쓰는 사람에게 읽어 주면 「그래서 나한테 뭐가 좋아지는데」가 남는가" —
     남으면 다시 쓴다.
   - 방향은 쓰되 **크기(수치)는 seed에 적힌 것만** 쓴다.
   - 증상에서 가치를 도출하는 것은 날조가 아니다("~실패하던 문제 수정" → "실패해 다시 하던 일이
     사라짐"). 제목만으로 증상이 불분명하면 개선점 문단에서 빼고 흐름 문단에 사실로만 남긴다.
   - 시스템 내부 사정(요청 횟수·처리 단계·동작 조건·버전·라이브러리 교체·리팩토링·테스트·빌드)은
     가치가 아니다.
   - 식별자(함수·파일·변수·브랜치명·해시·이슈 키)와 기술 용어 금지. 내용 없는 표현("편의성 향상",
     "사용성 개선", "~작업 진행") 금지.
   - 같은 가치는 몇 건이든 한 줄로 쓴다.
   - **재료는 seed(와 연결된 Jira 제목)뿐이다**: `commit_titles`, `mrs[].title`·`description`(설명 속
     `[보고]`/`## 요약` 절은 사실 출처로만 쓰고 `[개발]` 절은 재료가 아니다), `changed_files_summary`
     (어느 화면·기능인지), Jira MCP 연결 시 이슈 제목(증상 파악용, 개인 필드 금지). 커밋 본문은
     수집하지 않으므로 없는 내용을 지어내지 않는다.
   - **줄 끝에 반영 위치를 표기한다**: 기능 그룹(`group_kind=="feature"`)의 내용이 아직 병합되지
     않았으면(`stage`가 developing·reviewing, `mrs[].state`가 merged 아님) `(개발 중)`. 라인
     그룹(`group_kind=="line"`)의 커밋에서 관측했거나 기능 MR이 라인(`target_branch`가 develop·test·
     devqa 등)으로 병합됐으면 `(통합 반영)`. 어느 쪽인지 판정이 안 되면 개선점에서 뺀다.
     "배포됨·고객 적용"이라고 단정하지 않는다.
   - 커밋 제목이 스스로 **회귀·철회·원복**을 말하면(방금 만든 문제를 되돌린 것) 개선점으로 쓰지
     않는다 — 쓰는 사람이 겪은 적 없는 문제일 수 있다.
   - **가치를 정직하게 못 쓰면 쓰지 않는다.** 줄마다 위 판정 질문을 통과해야 한다. 통과한 줄이
     0개면 **개선점 문단과 앞의 빈 줄을 통째로 생략**한다(소제목도 나오지 않는다). 그 기간 변경이
     **전부 내부 정비**일 때만 흐름 문단 끝에 "모두 내부 정비로, 쓰는 사람이 체감하는 기능 변화는
     없습니다."를 덧붙인다. 증상 불분명·회귀 제외 등으로 뺀 항목이 있으면 그 문장을 쓰지 않고
     조용히 생략한다. 제품 변경 없는 날이 흔하다 — 개선점을 채우려고 지어내지 않는다.
   - 개수: 일간 3줄·주간 4줄 이내, 0줄 허용(기간별 상한은 daily 스킬 4단계·weekly 스킬 5단계의 분량 표).
   - 문체: 흐름 문단과 같은 서술형(~습니다). 명사형 단답을 섞지 않는다(한 카드에서 두 문체가
     섞이면 읽기가 끊긴다).
   - 개선점 문단에는 강조 마커(`**`·`⚠`)를 쓰지 않는다(마커 절: daily 스킬은 4c, weekly 스킬은 5c).
   - 개인 이름·개인별 수치 금지, LLM API 호출 금지.

   **예시 1 — 주간, 샘플 예약 서비스**(활동 그룹 9개 → 흐름 6~8줄, 개선점 2줄)
   - 전(옛 방식 — 따라 쓰지 않는다): `주간 31건의 커밋과 MR 4건이 처리됐습니다.\nPROJ-412 보안 점검 대응으로 예약자 입력 문자열 검증 보강 작업이 진행됐고, 대기자 알림 기능 개발과 예약 변경 이슈(SAMP-318) 버그 수정이 함께 이뤄졌습니다.\ndevelop→devqa→sqa→master 승격 라인은 03-04 기준으로 최신 상태입니다.`
   - 후:
     ```
     이번 주는 커밋 31건·MR 4건으로, 보안 점검 대응·대기자 알림 기능·예약 변경 오류 대응이 주요 갈래였습니다.
     보안 점검(PROJ-412) 대응으로 예약자 입력을 받는 곳 전반의 검증 보강 작업이 전용 브랜치에서 6일째 진행 중입니다.
     ⚠ 같은 검증 보강이 devqa에 점검용으로 임시 반영됐다가 **원복**돼, 정식 반영 경로와 시점 확인이 필요합니다.
     예약 달력 날짜 선택 품질 개선 MR이 develop에 병합됐고, 대기자 알림 기능은 화면 구조를 잡는 단계입니다.
     예약 변경 오류(SAMP-318)와 좌석 안내 문구 조건 정리가 develop·test 라인에 반영됐습니다.
     승격 라인은 03-04 정기 배포로 sqa와 master(3.6.0)까지 반영됐고, 이후 추가 승격은 없습니다.
     예약 내역 조회는 수정 커밋 비중이 늘어난 주였습니다.
     신규 작업 4건이 새로 관측됐습니다.

     예약 달력에서 마감된 날짜가 선택 가능해 보여 잘못 눌렀다 되돌아오던 일이 줄어, 다시 고르는 수고가 줄어듭니다 (통합 반영).
     메모란·연락처·검색어 입력에서 잘못된 값이 그대로 저장될 위험이 막히게 됩니다 (개발 중).
     ```
   - 왜: 첫 개선점은 병합 MR 설명의 `## 요약` 절에서 사실을 가져와 다시 고르는 수고 제거로 닫았다(재료 규칙). 예약 변경
     오류는 제목("변경 시 회차 갱신")만으로 증상이 분명하지 않아 흐름에만 남겼다. 원복 사실은 ⚠.
   - 반영 위치 판정: 첫 개선점은 기능 MR이 라인(`target_branch` develop)으로 병합됐다 → `(통합 반영)`.
     둘째는 검증 보강 전용 기능 그룹(`group_kind=="feature"`, `stage` developing, 병합 없음) → `(개발 중)`.
     devqa 임시 반영은 원복됐으므로 `(통합 반영)`의 근거가 아니다.
   - 이렇게 쓰지 않는다(개선점 문단):
     - `PROJ-412 대응으로 validateGuestInput·sanitizeNote를 적용해 입력값 검증 누락을 막았습니다.` — 식별자·기술 용어, 전용 브랜치·원복 상태인데 완료 단정
     - `예약 충돌 isConflict 비교를 O(1) 선행 검사로 바꿔 성능이 약 30% 좋아졌습니다.` — 함수명·복잡도 표기, seed에 없는 수치
     - `대기자 알림 문구 설정 기능 제거로 사용성이 향상됐습니다.` — 제거 이유가 seed에 없어 가치 불명, 내용 없는 표현
     - `예약 변경 시 회차 갱신 문제가 해결돼 편의성이 좋아졌습니다.` — 증상 불분명한 제목을 개선점으로 포장

   **예시 2 — 주간, 샘플 결제 모듈**(성능·계산 버그에서 가치 도출)
   - 전(옛 방식 — 따라 쓰지 않는다): `주간 4건의 커밋이 있었습니다.\nTASK-540 이슈 대응으로 요금 합산 시 sameRate 단위 비교 오타를 수정하고 대용량 결제 내역 조회 성능을 개선했습니다.\n버전 1.4.2로 업데이트됐습니다.`
   - 후:
     ```
     이번 주 develop 라인에 커밋 4건이 반영됐고, 모두 결제 요금 합산 처리(TASK-540)의 정확도·속도 개선입니다.
     모듈 버전은 1.4.2로 올라갔습니다.

     결제가 많은 날의 결제 내역을 열 때 기다리는 시간이 줄어듭니다 (통합 반영).
     이용자 구분(성인·어린이)이 다른 요금이 같은 항목으로 잘못 합산돼 금액이 달라지던 일이 막힙니다 (통합 반영).
     ```
   - 왜: "조회 시 검사 비용 최적화" → 기다림 단축(방향만, 크기 없음). "구분을 비교하지 않던 오타" →
     요금이 잘못 합산되던 증상 → 잘못된 결과 차단. 버전 올림은 가치가 아니다(시스템 내부 사정).
   - 반영 위치 판정: 두 줄 모두 develop 라인 그룹(`group_kind=="line"`)의 커밋에서 관측 → `(통합 반영)`.

6. **summary.json 작성**: 아래 형식으로 파일 저장. 레포 요약 키는 `repo_full_path`,
   그룹 키는 `org/repo::group_name`(seed의 키). `groups`는 선택 — 없으면 레포 요약만 주입된다.
   ```json
   {
     "weekly": {
       "org/auth": "이번 주는 커밋 5건·MR 1건으로, 간편 로그인 연동과 화면 이동 오류 수정이 주요 갈래였습니다.\n간편 로그인 연동은 시작 15일째 개발 중입니다.\n로그인 후 처음 화면으로 되돌아가는 오류 수정이 develop 라인에 반영됐습니다.\n간편 로그인 연동 MR 1건이 열려 있어 다음 주 리뷰가 이어질 예정입니다.\n\n로그인 후 처음 화면으로 되돌아가 다시 로그인하던 일이 사라집니다 (통합 반영).",
       "org/gateway": "조회 기간 내 특이 활동이 없습니다."
     },
     "groups": {
       "weekly": {
         "org/auth::feature/oauth": {
           "title": "OAuth 로그인 통합",
           "analysis": "무슨 작업인지.\n이번 주에 한 일(영역별 1~4줄).\nMR 상태(있을 때만).\n⚠ 주의점(신호 있을 때만).\n다음 주 예정(대기 상태가 있을 때만)."
         }
       }
     }
   }
   ```
   레포 요약은 흐름 문단 → 빈 줄(`\n\n`) → 개선점 문단 순서다. 개선점 문단이 없는 레포(위의
   `org/gateway`)는 `\n\n` 없이 흐름 문단만 쓴다. 그룹 분석(`analysis`)에는 이 문단 규약을 적용하지 않는다.

7. **주입 실행**: `python -m pulse.publish inject --config config.yaml --summary-file summary.json --period weekly` 실행.

### 단발성 조회(--ad-hoc)

특정 시점의 데이터를 조회하되 운영 대시보드를 변경하지 않으려면:

```bash
python -m pulse.publish collect --config config.yaml --period weekly \
  --now "2026-07-20T00:00:00+09:00" --ad-hoc
```

- `--ad-hoc` 플래그 추가 (기존 `--period`, `--now`, `--config` 동일)
- **결과**: 오직 `pulse-weekly-2026-07-20.html`만 생성. `latest-weekly.html`·`data/snapshots/`·`data/weekly_publish/latest.json`·캐시는 불변
- **조회 기간**: 발행과 같이 지난주 월~일(요청일이 속한 주의 월요일 00:00 기준 7일 전부터), 파일 이름의 날짜는 요청일
- **주입도 동일 형식**: `python -m pulse.publish inject --summary-file summary.json --period weekly --ad-hoc --date 2026-07-20`
  - `--ad-hoc --date` 필수
  - 해당 dated 파일만 주입, latest 미접촉

8. **결과 안내**: reports/latest-weekly.html 등 경로 + 작성한 요약 + 공유용 스니펫.
   
   **참여 섹션 (팀 참여):**
   - 기본 상태: **숨김** (보안-obscurity 기반)
   - 활성화 방법: URL에 `#team` 해시 추가 (예: `reports/latest-weekly.html#team`)
   - 링크 공유 시 참여 섹션을 함께 표시하고 싶으면 위 URL로 공유

## Repo Config Management

- **추가/삭제/닉네임 변경**: config.yaml을 로드→dict 수정→임시 파일로 저장→load_config로 검증
  →성공 시에만 원본 교체(원자적). 실패 시 원본 유지하고 오류 안내.
- dict 형식 `{url, nickname}` 사용.
- 편집만 수행하고 자동 발행하지 않는다("이어서 발행할까요?"로 확인).

## Example Output

**수집 완료 후 stdout JSON**(주간 기준, 예시는 일부 필드만 표기):
```json
{
  "weekly": {
    "team_name": "Platform",
    "report_date": "2024-01-15",
    "period": "weekly",
    "repos": {
      "org/auth": {
        "group_names": ["feature/oauth", "develop"],
        "group_count": 2,
        "new_work_count": 2,
        "warning_count": 1,
        "warning_titles": ["feature/legacy-sso 브랜치 방치"],
        "commit_count": 5,
        "mr_count": 1
      },
      "org/gateway": {
        "group_names": [],
        "group_count": 0,
        "new_work_count": 0,
        "warning_count": 0,
        "warning_titles": [],
        "commit_count": 0,
        "mr_count": 0
      }
    },
    "groups": {
      "weekly": {
        "org/auth::feature/oauth": {
          "name": "feature/oauth",
          "stage": "developing",
          "commit_titles": ["feat: 토큰 교환", "fix: 리다이렉트", "docs: OAuth 플로우"],
          "branch_names": ["feature/oauth"],
          "mr_titles": ["OAuth 구현 #123"],
          "mrs": [{"title": "OAuth 구현", "state": "open", "target_branch": "develop", "is_draft": false}],
          "group_kind": "feature",
          "commit_count": 3,
          "branch_history": {"started_on": "2024-01-01", "total_days": 15},
          "cached": true,
          "cached_title": "OAuth 로그인 통합",
          "cached_analysis": "지난주 분석..."
        },
        "org/auth::develop": {
          "name": "develop",
          "stage": "developing",
          "commit_titles": ["fix: 로그인 후 처음 화면으로 되돌아가는 오류", "docs: 배포 절차 갱신"],
          "branch_names": [],
          "mr_titles": [],
          "group_kind": "line",
          "commit_count": 2,
          "cached": false,
          "cached_title": null,
          "cached_analysis": null
        }
      }
    }
  },
  "published_weekly": true
}
```
레포의 `commit_count`·`mr_count`가 모두 0이면 활동 없는 레포(위 `org/gateway`), 그룹은 `commit_count>0`이거나
`mrs`가 있으면 활동 그룹이다(위 `org/auth`는 2개) — 5단계 분량 표의 기준이다.
`published_weekly: true`면 새 주간 HTML이 발행됨. `false`면 기존 대시보드 유지.
`weekly.groups`에서 각 그룹의 `cached` 필드를 확인하고, false인 것만 title/analysis를 작성한다.

**주입 완료 후 stdout 스니펫**(주간 기준 레포별):
```markdown
## Daily Pulse 요약

### org/auth
이번 주는 커밋 5건·MR 1건으로, 간편 로그인 연동과 화면 이동 오류 수정이 주요 갈래였습니다.
간편 로그인 연동은 시작 15일째 개발 중입니다.
로그인 후 처음 화면으로 되돌아가는 오류 수정이 develop 라인에 반영됐습니다.
간편 로그인 연동 MR 1건이 열려 있어 다음 주 리뷰가 이어질 예정입니다.

[개선점]
로그인 후 처음 화면으로 되돌아가 다시 로그인하던 일이 사라집니다 (통합 반영).

### org/gateway
조회 기간 내 특이 활동이 없습니다.
```
`[개선점]` 줄을 자동으로 붙이는 것은 일간 스니펫(`build_share_snippet`, `daily` 키만 읽음)뿐이다.
위 주간 예시는 같은 모양(흐름 → 빈 줄 → `[개선점]` → 개선점 문단)을 보이는 것이다.

## 대시보드 변화 (v5 이상)

- **기능 그룹 표현**: 기존 카드 그리드 → **확장형 리스트 행** (`<details>` 구조)
  - Summary: AI 제목 + 진행 단계 스테퍼(●─●─○) + 7일 스파크라인(꺾은선) + 규모(커밋·파일 수) + 마지막 활동 상대시각
  - 확장 내용: AI 분석 + 커밋/MR/브랜치 목록 + **이슈 키 링크** (설정 시) + 참여자
- **릴리스/검증 라인 표** (신규, `group_kind=="line"`):
  - 콤팩트 표: 라인명 + 최근 반영(최신 비머지 커밋) + 최근성 + AI 분석 상세
- **정렬**: 커밋 수 내림차순 → 동률 시 마지막 활동 최신순 → merged는 뒤로

## Jira 통합 (선택, 우아한 저하)

seed에 `issue_keys`가 있고 **Jira MCP 연결돼 있으면**:
- 각 이슈 키의 제목·상태를 조회해 AI 분석 입력 시 참고 가능 (예: "DOCS-123은 In Progress")
- 미연결 또는 조회 실패 시 이슈 키만 표시 (우아한 저하)
- **제약: Jira 담당자·예상일·스토리포인트 등 개인·실적 필드는 분석에 사용 금지**
- 코어(`pulse/`)는 Jira를 모른다 — 분석 작성자(Claude)가 선택적으로 활용

## 6차 신규 seed 필드 (수명주기 · 릴리스 열차)

### 그룹 seed에 추가: `lifecycle`
누적 수명주기 등록부(`data/lifecycle/registry.json`)와 조인된 결과. 등록부에 없는 그룹은 키가 없거나 null이다 (우아한 저하).
```json
"lifecycle": {
  "first_seen": "2026-07-15",      // 시작일 — 첫 관측일이 기본이나, branch_history가 더 이른 작업 시작을 알면 그 날짜로 보정됨
  "total_days": 13,                 // first_seen을 1일차로 센 총 경과일
  "current_stage": "developing",
  "current_stage_days": 2,          // 현재 단계 진입 후 경과일
  "active_days": 12,                // 커밋이 있었던 날짜 수 (관측 이후만 — 생애 전체는 branch_history.active_days)
  "cumulative_commits": 61          // 날짜별 카운트 합계 (168h 창 중첩 이중계산 없음)
}
```
- **요약 작성 시 활용**: "13일째 진행 중, 최근 2일은 개발 단계" 같은 서사를 쓸 수 있다.
- **주의**: merged 후 14일이 지난 그룹은 등록부에 남아 있어도 `lifecycle`이 제공되지 않는다 (졸업 정책).

### 그룹 seed에 추가: `branch_history` (브랜치 생애 이력)
base 브랜치 대비 고유 커밋 전체(authored 기준)로 계산한 생애 요약. 기능 그룹만 제공되며, 없으면 null (우아한 저하).
```json
"branch_history": {
  "base_branch": "develop",
  "started_on": "2026-07-07",      // 첫 작업일 (authored 기준 — 리베이스에 불변)
  "total_days": 24,                 // started_on을 1일차로 센 경과일
  "active_days": 5,                 // 생애 전체에서 커밋이 있었던 날짜 수
  "total_commits": 19,
  "truncated": false,               // true면 "N건 이상"으로 서술
  "silent_gap_days": 10,            // 최장 연속 무활동 일수
  "behind_count": 6,                // base 대비 뒤처진 커밋 수 (null 가능)
  "fix_surge": false                // 최근 주의 fix 비중이 이전 주 평균보다 유의미하게 높으면 true (대시보드의 "수정·검증 작업 집중")
}
```
- **경과일·시작일·활동일 서사는 이 필드를 우선 사용한다** — "N일째 개발"은
  `branch_history.total_days` 기준. `lifecycle.total_days`는 보정되긴 하지만
  branch_history가 없는 그룹에선 여전히 관측 경과일이므로, 그 경우 "관측 N일째"로
  단정을 피한다.

### 레포 seed에 추가: `release_train` (승격 사다리)
MR의 `source_branch → target_branch` 쌍에서 유도한 팀의 실제 승격 경로. 라인 간 MR이 없는 레포는 빈 목록이거나 null이다.
```json
"release_train": [
  {"source": "develop", "target": "devqa", "last_merged_at": "2026-07-24", "merged_count": 24, "open_count": 0},
  {"source": "devqa",   "target": "sqa",   "last_merged_at": "2026-07-24", "merged_count": 15, "open_count": 0},
  {"source": "sqa",     "target": "master","last_merged_at": "2026-07-22", "merged_count": 3,  "open_count": 0}
]
```
- **요약 작성 시 활용**: "코드가 sqa까지 올라갔고 master 반영은 07-22" 처럼 **코드 라인의 위치**를 서술할 수 있다.
- **하지 말 것**: 개별 기능이 사다리의 어느 칸에 있는지 단정하지 말 것. 커밋 계보를 추적하지 않으므로 "develop이 devqa로 승격됐으니 기능 X도 devqa에 있다"는 추론은 오판이다. 기능의 단계(`stage`·`lifecycle`)와 라인의 사다리 위치는 **별개 정보**로 서술한다.
- **비율 금지**: "3/4단 통과", "75% 진행" 같은 환산 표기 금지 (근거 없는 정밀도).
- `last_merged_at`은 구버전 GitLab에서 `updated_at` 근사이므로 **날짜 단위로만** 인용한다.

### 등록부 초기화 (1회) — backfill
기존 `data/raw/` 날짜 폴더로 등록부를 소급 복원한다. 멱등(재실행 안전).
```bash
python -m pulse.publish backfill-lifecycle --config config.yaml
```
- 등록부가 없으면 첫 실행일이 모든 그룹의 첫 관측일이 되어 "진행 1일차"만 보인다. backfill로 보유 raw 범위만큼 앞당길 수 있다.
- **백필 이력의 초기 단계는 근사값**이다: 과거 raw 파일은 소급 생성본이라 `collected_at`이 내부 데이터보다 이를 수 있어, 이른 날짜의 stage가 "other"로 판정될 수 있다. 정기 실행분에서는 발생하지 않는다.
- `--ad-hoc` 수집은 등록부를 **읽기만** 하고 쓰지 않는다 (운영 상태 격리).

### 개인 정보 금지 (재확인)
`release_train`·`lifecycle` 어디에도 작성자·리뷰어 정보는 포함되지 않는다. 요약에도 개인 이름·개인별 수치를 쓰지 말 것.

---

## Technical Notes

- `--now` 옵션: cowork 등 외부 스킬에서 특정 시각으로 발행할 때 필수. 
  전달된 타임스탐프를 타임존 포함(aware) datetime으로 파싱해 
  `get_effective_now(config)` 대신 사용. 영업일·이번 주 발행 여부 판정, 주간 창 끝(그 주 월요일 00:00),
  lookback 계산에 쓰이고, 파일명(date)·report_date는 이 시각의 날짜(실행일)를 따른다.
- 주간 스냅샷: `published_weekly: true`일 때(영업일·이번 주 미발행의 정기 발행 또는 `--period weekly --force-weekly`) 주간 섹션을 
  `data/weekly_publish/latest.json`에 저장(`published_at`·`report_date`는 실행일, `window_end`는 그 주 월요일 00:00).
  비발행 실행(같은 주 재실행, 휴무일·주말 등)에서는 이 스냅샷으로 주간 섹션을 교체해 주간 대시보드 데이터 일관성 보증.
  - `--force-weekly` 옵션 사용 시 스냅샷 자동 갱신됨.
- collect: 파이프라인 1회 실행 → 주간 HTML 저장 시도(게이트 통과 시만) → JSON stdout (weekly만, published_weekly 메타)
  - 게이트를 통과하지 못하면 HTML 저장 안 함, `published_weekly: false` 보고
  - `--force-weekly`로 강제 발행 가능 (조회 기간은 그 주 월요일 기준, 이름표는 실행일, `--period weekly`와 함께 사용)
  - `--ad-hoc` 조회도 조회 기간은 같은 규칙(지난주 월~일), 이름표는 요청일
- inject: 저장된 HTML의 **레포별 요약 슬롯 + 그룹별 제목·분석 슬롯** 치환 → 스니펫 stdout
- 요약 데이터는 `extract_summary_input_by_repo(model, cache)`로 추출(개인명 제외,
  레포별 그룹/경고/신규작업 제목 + 그룹 seed + 캐시 메타 + changed_files 메타)
- seed 필드에 `changed_files_count`(그룹 변경 파일 수)와 `changed_files_summary`
  (파일 경로 + 라인 증감 + 함수 컨텍스트의 기계적 발췌)가 추가됨
- 슬롯: 레포 `<!--PULSE_AI_SUMMARY_SLOT:{repo}-->`, 그룹 제목
  `<!--PULSE_GROUP_AI_TITLE_SLOT:{repo}::{group_name}-->`, 그룹 분석
  `<!--PULSE_GROUP_ANALYSIS_SLOT:{repo}::{group_name}-->` (모두 주석·graceful degradation)
- summary.json에서 특정 레포/그룹 키를 빼면 해당 슬롯은 주석으로 남아 화면에 안 보임(안전).
  그룹 제목을 채우면 카드에서 브랜치명은 CSS로 숨겨지고 그 제목이 표시된다.
- 캐시 메커니즘: collect 실행 시 각 그룹의 지문(commit_titles 등)을 계산하고 캐시와 비교.
  지문이 일치하면 `cached=true` + 캐시된 title/analysis 반환. inject 때 새로 작성한 항목만 캐시에 저장.
- 주의 신호는 kind별로 묶여 요약 뱃지 + 접기(`<details>`)로 렌더된다(요약은 자동, AI 입력 불필요).
