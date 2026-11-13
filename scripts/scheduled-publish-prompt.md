# Daily Pulse 자동 발행 (대시보드)

오늘 날짜: {{TODAY}} (Asia/Seoul). 이 실행은 launchd가 기동한 **비대화형(헤드리스) 실행**이다.
사용자에게 질문할 수 없으므로, 진행 불가 상황이면 즉시 종료 마커(하단 참조)를 출력하고 종료한다.

이 폴더의 스킬 문서 2개가 절차의 단일 기준이다. 매 실행 시 최신 내용을 읽고 따를 것:

- `.claude/skills/daily-pulse-publish-daily/SKILL.md` — 일간 발행 규칙
- `.claude/skills/daily-pulse-publish-weekly/SKILL.md` — 주간 발행 (영업일 게이트)

## 실행 순서

1. **사전 점검**: `.venv/bin/python -m pulse.publish token status` 실행 —
   gitlab이 ✓가 아니면 이후 단계를 진행하지 말고 실패 마커 출력.
2. **수집**: `.venv/bin/python -m pulse.publish collect --config config.yaml
   --now "{{TODAY}}T00:00:00+09:00" > collect.json`
   — 시각은 **00:00 고정**이다(발행 시각인 09:00이 아니다). 조회창이 달력에 정렬돼
   일간은 직전 영업일부터 완결된 전날까지(평일 다음 날은 하루, 월요일·공휴일 다음 날은
   직전 영업일부터), 주간은 완결된 전주(월~일)가 담긴다. 09:00을 쓰면 오늘 오전
   9시간이 섞여 하루가 잘린다. 기간 표시도 양끝이 00:00일 때만 날짜만 나온다.
   — daily·weekly 섹션이 모두 출력되고, 영업일이면서 이번 주 주간이 아직 없으면
   주간 HTML도 함께 발행된다(월요일이 공휴일이면 그 주 다음 영업일, 월요일 실행이 빠졌으면
   그 주의 다음 영업일 실행이 채운다) — stdout의 `published_weekly`로 확인한다.
   판단은 코드가 한다(실행 로그의 「주간 발행 판단」 한 줄) — 수집을 한 번 더 돌리지 않는다.
3. **요약 작성**: collect.json을 읽고 summary.json 작성 —
   레포별 요약은 흐름 문단 + (근거가 있을 때만) 빈 줄 1개 + 개선점 문단이다
   (개선점 문단 = 쓰는 사람 관점에서 좋아진 점, 고쳐야 할 점이 아니다).
   분량·담을 것·개선점 문단 작성 규칙은 daily 스킬 4단계·4d, weekly 스킬 5단계·5d를 따른다
   (문단 안은 문장마다 줄바꿈, 흐름 문단 안에는 빈 줄 금지 — summary.json 문자열에서 문단 경계는 `\n\n`,
   가치를 정직하게 못 쓰면 개선점 문단 생략).
   groups 중 `cached=false`인 그룹의 title/analysis도 작성(analysis 분량·담을 것은 daily 스킬 4b, weekly 스킬 5b를 따른다 — 상한 일간 8줄·주간 10줄, 채울 칸이 아니다).
   규칙: 개인 이름 금지, 평문만, LLM API 호출 금지(네가 직접 작성).
   확인·대응이 필요한 내용만 강조 마커(`**구절**` 또는 불릿 줄 `⚠ ` 접두) 사용 가능 —
   한도·용법은 스킬 문서의 강조 마커 절을 따른다(title에는 금지, 남용 금지,
   개선점 문단에는 마커를 쓰지 않는다).
4. **주입**: `.venv/bin/python -m pulse.publish inject --config config.yaml
   --summary-file summary.json --period daily` 실행.
   `published_weekly`가 true이거나 `reports/latest-weekly.html`에 빈 슬롯
   (`PULSE_AI_SUMMARY_SLOT`·`PULSE_GROUP`)이 남아 있으면 `--period weekly`로 한 번 더 실행.
   (같은 날 재실행은 주간을 다시 만들지 않으므로, 첫 실행이 주입 전에 끊겼다면 빈 슬롯으로 알아낸다.)
   빈 슬롯 확인 명령:
   `grep -c "PULSE_AI_SUMMARY_SLOT\|PULSE_GROUP" reports/latest.html reports/latest-weekly.html`
   — 파일마다 0건이 정상(주입 완료)이다. `grep -c`는 0건일 때 exit 1을 내지만 오류가 아니므로
   FAIL로 판정하지 않는다. 주간 파일이 0이 아니면 위 `--period weekly` 주입이 필요하다.
5. **결과 보고(stdout)**: 대시보드 경로(일간·주간) + 레포별 요약 스니펫.
   일부 레포 수집 실패 시 해당 레포만 스킵하고 실패 목록을 명시.
   - 일간 기간은 collect.json `daily.window_start`~`window_end`의 날짜로 적는다(끝이 00:00이면
     종료일 전날까지 — 예: 2026-10-02 ~ 2026-10-05). 창이 하루보다 길면 「어제」·「하루」로 쓰지 않는다.
   - 주간을 발행했으면 주간 기간은 `weekly.window_start`~`window_end` 날짜(끝이 00:00이면 전날까지)로,
     이름표는 `weekly.report_date`(발행일)로 적는다. 발행하지 않았으면 「주간: <report_date> 발행분 유지」.
   - 수집 결과 최상위 `calendar_warnings`가 비어 있지 않으면 그 문장을 그대로 보고에 포함한다
     (공휴일 표 갱신 필요, 또는 휴무일이 14일 이상 연속된다는 알림).

## 금지 사항

- 개인 실적 지표·개인 이름 노출 금지
- 토큰·비밀번호를 파일·로그·명령행 인자에 남기지 않는다
- `config.yaml`, `reports/`, `data/` 는 커밋 금지
- git commit/push 하지 않는다 (이 작업은 발행만 한다)
- 정기 실행에서 `--force-weekly`를 쓰지 않는다 (주간 발행 여부는 코드의 게이트가 판단한다)
- `--ad-hoc` 옵션을 쓰지 않는다 (정기 발행은 운영 상태를 갱신해야 한다)
- `security` CLI(`find-generic-password` 등)로 키체인을 직접 읽지 않는다 — 헤드리스에서는 GUI 승인
  창이 떠서 응답 없이 멈추고, 사람이 없으면 계속 대기한다(2026-10-03 실측: 실행이 3일간 끝나지 않아
  10/4~10/6 정기 실행이 건너뛰어졌다).
- 응답이 멈출 수 있는 명령을 백그라운드(run_in_background)로 걸어 두고 끝내지 않는다 —
  끝나지 않은 백그라운드 작업이 남은 채 `claude -p`가 종료되지 않은 사례가 있다(2026-10-03)

## 종료 마커 (필수 — 러너가 이 마커로 성공/실패를 판정한다)

응답의 마지막 줄에 반드시 아래 중 하나를 출력한다:

- `PULSE_PUBLISH_OK` — 5단계까지 전부 성공
- `PULSE_PUBLISH_PARTIAL: <실패 단계와 사유>` — 일간 주입(4단계)까지는 성공했으나
  주간 주입(4단계의 `--period weekly`) 또는 결과 보고(5단계)가 실패
- `PULSE_PUBLISH_FAIL: <사유>` — 4단계 이전에 실패 (대시보드 미발행)
