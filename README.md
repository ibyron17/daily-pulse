# Daily Pulse — 팀 깃 활동 일일 브리핑 대시보드

팀의 깃 레포 활동(커밋, 브랜치, MR)을 매일 수집·분석해 **프로젝트/기능 단위로 그룹핑**한 HTML 대시보드를 생성합니다.

**목적은 프로젝트 흐름 파악**입니다. 개인 실적 평가가 아니므로, 개인별 커밋 수 랭킹, 코드 라인 수 비교, 시간대별 활동 패턴 등 실적 지표는 의도적으로 포함하지 않습니다. 팀 리드/테크 리드가 아침 업무 시작 시점에 "어제 무슨 일이 있었지?", "어떤 기능이 정체됐나?"를 빠르게 파악하기 위한 도구입니다.

## 아키텍처

레이어를 다음과 같이 분리하고, 레이어 간에는 명시적 데이터 모델로만 통신합니다:

- **collector**: Git 호스팅 API(GitLab/GitHub)에서 원본 활동 데이터 수집 (외부 I/O 전담). 내부에 `GitProvider` 추상화를 두고 구현체(GitLab REST v4, GitHub)가 정규화된 데이터 모델로 반환.
- **grouper**: 활동을 프로젝트/기능 단위로 클러스터링하고, 진행 단계(개발 중/리뷰 중/머지됨)를 추정. 그룹을 **기능(feature)과 릴리스/검증 라인(line)으로 구분**하고, 이슈 키(`DOCS-123` 형태)·최근 활동 시각·일별 커밋 추이를 파생 (순수 로직).
- **renderer**: 그룹핑 결과를 단일 파일 HTML 대시보드로 렌더링 (순수 로직 + 파일 출력).
- **config**: 설정 파일(`config.yaml`) 로딩과 검증.
- **publish** (`pulse.publish`): 대화형 발행 CLI — 수집(`collect`)·AI 요약 주입(`inject`)·토큰 관리(`token`). 그룹 분석 캐시(`data/analysis/`)로 변화 없는 그룹의 AI 분석을 재사용.

### 대시보드 구성

- **일간/주간 브리핑**: AI가 작성한 흐름 요약 (Skill 발행 시).
- **프로젝트 현황**: 기능 그룹을 활동량 순 확장형 리스트로 표시 — 단계 스테퍼(진행→리뷰→완료), 최근 7일 커밋 스파크라인, 규모(커밋·파일 수), 마지막 활동 시각. 행을 펼치면 AI 분석·커밋/MR/브랜치·이슈 키가 표시됩니다.
- **릴리스/검증 라인**: master/develop/test/sqa 등 통합 브랜치의 최근 반영 내용을 별도 표로 표시.
- **신규 작업 / 주의 신호**: 새로 시작된 브랜치·MR, 정체된 MR·방치 브랜치 경고.
- **팀 참여**: 기본 숨김 — URL 해시 `#team`을 붙였을 때만 표시됩니다.

---

## 1. 설치

### 요구사항
- Python 3.10 이상
- pip

### 단계별 설치

```bash
# 1. 프로젝트 클론
git clone <repository-url> daily-pulse
cd daily-pulse

# 2. 가상 환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

# 3. 패키지 설치 (개발용 도구 포함)
pip install -e ".[dev]"

# 4. 설치 검증
pytest -q
```

**설치 검증 결과**: 모든 테스트가 통과하면 설치가 완료된 것입니다.

---

## 2. 토큰 설정

### GitLab PAT(개인 액세스 토큰) 발급

1. 사용하는 GitLab(`https://gitlab.example.com/`)에 로그인합니다.
2. 우측 상단 프로필 메뉴 → **Preferences** (또는 **Settings**)로 이동합니다.
3. 좌측 **Access Tokens** 클릭합니다.
4. **Create personal access token** 버튼을 클릭합니다.
5. 다음을 입력합니다:
   - **Token name**: `daily-pulse` (예시)
   - **Scopes**: `read_api` ✓ (필수, 이것만 체크)
   - **Expiration date**: 필요에 따라 설정 (선택사항)
6. **Create personal access token** 클릭하고, 표시된 토큰을 복사합니다.

### GitHub PAT 발급 (GitHub 레포를 수집할 때만)

config의 `repos`에 `https://github.com/...` 레포가 하나라도 있으면 `GITHUB_TOKEN`이 필요합니다.

**Fine-grained token (권장)**:
1. github.com 로그인 → 우측 상단 프로필 → **Settings** → **Developer settings** → **Fine-grained tokens** → **Generate new token**
2. 다음을 설정합니다:
   - **Token name**: `daily-pulse` (예시)
   - **Repository access**: 수집 대상 레포만 선택 (Only select repositories)
   - **Permissions** → Repository permissions: **Contents: Read-only**, **Pull requests: Read-only** (이 둘이면 충분)
3. 생성된 토큰(`github_pat_...`)을 복사합니다.

**Classic token을 쓸 경우**: 공개 레포만 수집하면 `public_repo`, 비공개 레포가 있으면 `repo` 스코프를 체크합니다.

참고: `gh` CLI에 로그인되어 있다면 별도 발급 없이 `export GITHUB_TOKEN="$(gh auth token)"`으로 대체할 수 있습니다 (수동 실행에 편리; 스케줄 실행에는 발급 토큰 권장).

### 토큰 주입 (계층 폴백: env → keyring → gh)

**중요 보안 경고**:  
자체 호스팅 GitLab이 **HTTP(평문)**로 운영된다면 **GitLab 토큰을 그 망 밖에서 사용하지 마십시오**. 토큰이 네트워크 상에서 평문으로 전달되어 탈취될 수 있습니다. 해당 망 안에서만 사용하십시오. (GitHub은 HTTPS라 해당 없음)

토큰은 다음 순서로 자동 탐색됩니다 — **config에 있는 provider의 토큰만 있으면 됩니다**:

1. **환경 변수** (`GITLAB_TOKEN` / `GITHUB_TOKEN`) — 최우선
2. **OS 비밀 저장소(keyring)** — `python -m pulse.publish token set --provider gitlab`으로 저장하면 다음부터 자동 로드 (macOS Keychain 등)
3. **gh CLI** — GitHub 한정, `gh auth token` 자동 사용

현재 상태 확인:

```bash
python -m pulse.publish token status
# Provider | Source  | Available
# gitlab   | keyring | ✓
# github   | gh      | ✓
```

환경 변수 방식을 쓰려면:

```bash
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxx"       # GitLab 레포가 있을 때
export GITHUB_TOKEN="github_pat_xxxxxxxxxxxxxxxx"  # GitHub 레포가 있을 때
```

지속적으로 사용하려면 셸 설정 파일에 추가합니다:

```bash
# ~/.bashrc, ~/.zshrc 등에 추가
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxx"
export GITHUB_TOKEN="github_pat_xxxxxxxxxxxxxxxx"

# 그 후 셸 재시작 또는
source ~/.zshrc
```

검증:
```bash
echo $GITLAB_TOKEN    # 토큰이 출력되면 설정 완료
echo $GITHUB_TOKEN
```

세 경로 모두에서 토큰을 찾지 못하면 실행 초기에 누락된 provider와 저장 방법(환경변수·keyring)을 안내하고 종료(exit 1)합니다.

---

## 3. 주간 데이터 소스

Daily Pulse는 주간 대시보드가 같은 주 안에서 일관된 데이터를 보여주도록, 발행 시점의 주간 섹션을 스냅샷으로 저장하고 비발행 실행에서 재사용합니다.

### 스냅샷 저장 시점

**주간을 발행할 때** — 영업일이면서 이번 주 주간이 아직 없는 정기 발행(월요일이 공휴일이면 그 주 다음 영업일), 또는 `--period weekly --force-weekly`로 하는 강제 재발행:
- 주간 대시보드 HTML 생성 후, 수집 정보(수집된 레포, 그룹, 지표)를 `data/weekly_publish/latest.json`에 저장합니다.
- 스냅샷에는 발행 시점의 수집 메타(`report_date`, `window_start`, `window_end`, `published_at`)와 그룹 정보가 포함됩니다.
  `report_date`·`published_at`은 실제 발행일(실행일)이고, `window_end`는 조회 기간의 끝(그 주 월요일 00:00)입니다.

### 주간 발행일과 조회 기간 (영업일 · 이번 주 미발행)

주간 대시보드는 **영업일(월~금, 공휴일·`extra_holidays` 제외)에, 그 주(월~일)에 아직 발행되지 않았을 때** 발행합니다.
보통은 월요일이고, 월요일이 공휴일이면 그날은 주간을 내지 않고 그 주의 다음 영업일(예: 화요일)에 냅니다.
월요일 정기 실행이 실패해 주간이 빠진 주도 그 주의 다음 영업일 실행이 채웁니다. 수집은 매일 한 번이면 되고
판단은 코드가 합니다 — 실행 로그에 「주간 발행 판단: 발행 / 발행 안 함 (기준일·이번 주 월요일·마지막 발행 창 끝)」 한 줄이 남습니다.

- **이번 주 발행됨**: `data/weekly_publish/latest.json`의 `window_end`가 이번 주 월요일 00:00 이상이면 발행된 것으로 봅니다.
  같은 주에 다시 실행하거나 같은 날 재실행해도 주간은 다시 나가지 않습니다. 기록 파일이 없거나 읽을 수 없으면
  미발행으로 보아 그 주 주간을 한 번 더 냅니다(같은 내용을 덮어쓰므로 해는 없습니다).
- **조회 기간**: 발행일이 속한 주의 월요일 00:00을 A라 할 때 A의 7일 전 월요일 00:00 ~ A(지난주 월~일, 주말 커밋 포함)입니다.
  **이름표**(`report_date`·`published_at`·파일 이름 `pulse-weekly-<발행일>.html`)는 실제 발행일(`--now`가 있으면 그 날짜)입니다.
  예: 2026-10-06(화, 월요일이 대체공휴일)에 발행하면 기간은 2026-09-28 (월) ~ 2026-10-04 (일),
  파일은 `pulse-weekly-2026-10-06.html`입니다.
- `--period weekly`와 `--period both`는 같은 게이트를 씁니다. `weekend_catchup: false`여도 주간 발행일 판단은
  공휴일을 반영합니다(`weekend_catchup`은 일간 조회 기간 설정입니다).
- **`--force-weekly`**: 게이트(영업일·이번 주 미발행)를 우회해 이번 주 주간을 다시 발행합니다.
  `--period weekly` 전용이며, `--period both` 또는 `--period daily`와 함께 주면 시각과 무관하게 거부되고(exit 2)
  `--period weekly`로 따로 실행하라는 안내가 나옵니다. 조회 기간은 위 규칙 그대로(지난주 월~일), 이름표는 실행일입니다.
- 강제 재발행(`--force-weekly`)과 `--ad-hoc` 조회는 운영 기록(일별 수집 원본·브랜치 스냅샷·진행 일수 등록부·
  브랜치 이력·보존 정리)을 쓰지 않습니다. 지난 날짜를 다시 만들어 보려면 `--ad-hoc`을 쓰세요
  (`--now`만 과거로 주고 `--ad-hoc` 없이 돌리면 그 날짜의 운영 기록을 덮어씁니다).
- `--ad-hoc` 조회도 주간 조회 기간은 같은 규칙(지난주 월~일)이고 이름표는 요청일입니다(5장).
- **한 주(월~금)가 통째로 쉬는 주**(예: `extra_holidays`로 그 주 평일을 모두 넣은 경우)에는 근무일이 없어
  그 직전 주의 주간이 만들어지지 않습니다. 다음 주 월요일에 휴무 주의 주간이 나갑니다. 내장 공휴일 표에는 이런 주가 없고,
  경고도 따로 나오지 않습니다.
- 알려진 한계: 월요일 실행이 빠졌거나 월요일이 공휴일인 주의 신규 브랜치는 그 주 월요일 스냅샷이 없어
  그 이후 가장 이른 스냅샷과 비교하므로 하루 남짓 넓게 잡힐 수 있습니다.

### 비발행 실행 시 동작

**주간을 발행하지 않는 실행**(이번 주 주간이 이미 나간 뒤의 실행, 휴무일·주말 실행 등)을 하면:
1. 파이프라인이 실행되어 일간 대시보드는 정상 생성됩니다.
2. 주간 섹션은 최근 발행 스냅샷으로 **교체**되어, 주간 대시보드와 collect 출력이 마지막 발행분을 계속 표시합니다.
3. 스냅샷의 그룹별 `cached` 플래그를 재평가하여, 분석 캐시에 존재하는 그룹은 `cached=true`로 설정합니다.
   - 이를 통해 발행 스킬이 불필요한 AI 재작성을 건너뜁니다.

### 스냅샷 부재 시 우아한 저하

**처음 발행 전** (주간 발행이 아직 없을 때):
- 스냅샷이 없으므로 비발행 실행의 `payload`에서 `weekly` 섹션이 생략됩니다.
- 발행 스킬과 주간 대시보드가 해당 섹션을 찾지 못하면, 일간 대시보드만 표시됩니다.
- 이는 예상된 동작이며, 첫 주간 발행 후부터 정상화됩니다.

---

## 4. 조회 기간 의미론

Daily Pulse는 **조회 기간(조회창)**을 `[now - lookback_hours, now]`로 정의합니다.
즉, 기준 시각(now)로부터 과거 N시간의 폐곡간(양끝 포함)입니다.
일간의 폭 N은 설정값 `lookback_hours`를 최소로 하되, `weekend_catchup`이 켜져 있으면 직전 영업일까지
넓어집니다(아래 「직전 영업일까지 확장」 절). 주간은 168시간 고정입니다.

### --now 오버라이드 (달력 정렬)

스케줄 실행 시 `--now` 옵션으로 기준 시각을 명시하면, 조회 기간이 달력에 정렬됩니다:

**예: 일간**
```bash
python -m pulse.publish collect --now "2026-07-23T00:00:00+09:00"
```
- 조회 기간: [2026-07-22 00:00, 2026-07-23 00:00] (정확히 전날 24시간)
- 대시보드 기간 표시: "2026-07-22 (수)" (양끝 00:00 규칙 → 날짜만)

**예: 월요일 weekend_catchup (72시간)**
```bash
python -m pulse.publish collect --now "2026-07-27T00:00:00+09:00"  # 월요일
```
- 조회 기간: [2026-07-24 00:00, 2026-07-27 00:00] (72시간)
- 대시보드 기간 표시: "2026-07-24 (금) ~ 2026-07-26 (일)"

**예: 공휴일 다음 날 (직전 영업일까지 확장)**
```bash
python -m pulse.publish collect --now "2026-10-06T00:00:00+09:00"  # 화요일, 전날 10/5가 대체공휴일
```
- 조회 기간: [2026-10-02 00:00, 2026-10-06 00:00] (96시간)
- 대시보드 기간 표시: "2026-10-02 (금) ~ 2026-10-05 (월)"

**예: 주간**
```bash
python -m pulse.publish collect --now "2026-07-27T00:00:00+09:00"  # 월요일
```
(월요일이 영업일이고 이번 주 주간이 아직 없으면 같은 명령이 주간도 발행합니다 — 주간 조회창은 168시간 고정)
- 조회 기간: [2026-07-20 00:00, 2026-07-27 00:00] (168시간)
- 대시보드 기간 표시: "2026-07-20 (월) ~ 2026-07-26 (일)" (종료 날짜에서 하루 뺌)
- 파일: `pulse-weekly-2026-07-27.html` (이름표는 실행일)

**예: 월요일 실행이 빠진 주의 보완 발행**
```bash
python -m pulse.publish collect --now "2026-07-29T00:00:00+09:00"  # 수요일, 이번 주 주간이 아직 없음
```
- 별도 옵션 없이 같은 명령이 주간을 보완합니다(수집 한 번). 조회 기간은 월요일 발행과 같은
  2026-07-20 (월) ~ 2026-07-26 (일)이고, 파일 이름의 날짜만 실행일입니다(`pulse-weekly-2026-07-29.html`).
  수집 폭은 168시간에 월요일 00:00부터 실행 시각까지의 시간(48시간)을 더해 216시간입니다.
  자세한 규칙은 3장 「주간 발행일과 조회 기간」을 봅니다.

### 수동 실행 (--now 미지정)

`--now` 옵션 없이 수동 실행하면 현재 시각을 기준으로 합니다:
```bash
python -m pulse.publish collect  # 15:30에 실행
```
- 조회 기간: [2026-07-22 15:30, 2026-07-23 15:30]
- 대시보드 기간 표시: "2026-07-22 (수) 15:30 ~ 2026-07-23 (목) 15:30" (시각 포함 규칙)

달력 정렬 없이 실행되지만, **기간 의미론은 동일**합니다.

### 기간 표시 규칙 (HTML 대시보드)

조회 기간은 대시보드 헤더의 커스텀 툴팁(.tooltip-host/.tooltip-bubble)으로 표시됩니다:

- **양끝이 00:00:00**: 종료 시각 제외, 창의 길이에 따라 표시
  - 하루짜리 창: "2026-07-22 (수)" (날짜 하나)
  - 여러 날 창: "2026-07-20 (월) ~ 2026-07-26 (일)" (시작 ~ 종료-1일 범위)
- **그 외** (시각이 있으면): 양끝 시각 포함
  - "2026-07-22 (수) 15:30 ~ 2026-07-23 (목) 15:30"

### 직전 영업일까지 확장 (weekend_catchup)

config.yaml의 `weekend_catchup: true`(기본값)일 때, 일간 조회 기간은 **직전 영업일 00:00부터 오늘 00:00까지**로
넓어집니다. 영업일은 월~금이면서 공휴일이 아닌 날입니다. 월요일의 72시간(금~일)은 이 규칙의 특수 사례입니다.

- `lookback_hours`는 최소 폭으로 쓰입니다. 설정값보다 좁아지지 않습니다(기본 24시간에서는 영업일 규칙과 같은 결과).
- 00:00 기준 실행에서는 조회 기간이 정확히 `직전 영업일 00:00 ~ 오늘 00:00`이 됩니다.
  시각이 있는 수동 실행(예: 화 14:00)은 직전 영업일의 같은 시각부터입니다.
- `weekend_catchup: false`이면 주말·공휴일과 관계없이 `lookback_hours` 그대로입니다.

| 발행일 (00:00 기준) | 조회 기간 | 폭 |
|---|---|---|
| 2026-10-14 (수, 전날이 영업일) | 10-13 (화) | 24시간 |
| 2026-10-03 (토) | 10-02 (금) | 24시간 |
| 2026-10-04 (일) | 10-02 (금) ~ 10-03 (토) | 48시간 |
| 2026-07-13 (월) | 07-10 (금) ~ 07-12 (일) | 72시간 |
| 2026-10-06 (화, 10-05 대체공휴일 다음 날) | 10-02 (금) ~ 10-05 (월) | 96시간 |
| 2026-09-28 (월, 추석 연휴 뒤) | 09-23 (수) ~ 09-27 (일) | 120시간 |

일요일 발행분은 금·토 이틀을 보여 줍니다.

공휴일은 런타임에 외부를 호출하지 않고 저장소 안의 데이터로 판정합니다.

- **`holiday_calendar`**: 어느 달력의 공휴일 표를 쓸지 고릅니다. `kr`(기본값)은 내장 한국 표, `none`은 표를 쓰지 않는
  설정입니다(쉬는 날은 주말과 `extra_holidays`뿐). `weekend_catchup`은 일간 조회 폭을 넓힐지,
  `holiday_calendar`는 어느 날이 쉬는 날인지를 정하므로 둘은 서로 독립입니다.
  `none`은 문자열이어야 하며, 값을 비우거나 `null`·`no`·`off`로 적으면 설정 오류입니다.
- **내장 표**: `pulse/kr_holidays.py`의 한국 법정공휴일 표(대체공휴일 포함). `holiday_calendar: kr`일 때만 씁니다.
- **`extra_holidays`**: 내장 표에 없는 휴무일(임시공휴일·회사 휴무)을 config.yaml에 `YYYY-MM-DD` 목록으로 추가합니다.
  달력 설정과 관계없이 항상 쉬는 날로 셉니다. 내장 표에서 날짜를 빼는 설정은 없습니다(필요하면 `pulse/kr_holidays.py`를 고칩니다).
- 일간 조회 폭·주간 발행일 판단(영업일 ∧ 이번 주 미발행)·달력 경고는 모두 같은 휴무일 집합
  (설정 달력 ∪ `extra_holidays`)을 씁니다(3장).

#### 공휴일 표 갱신 (연 1회)

내장 표는 해마다 한 번 갱신해야 합니다.

1. 우주항공청 한국천문연구원의 「월력요항」(매년 6월경 다음 해분 발표)을 보고 `pulse/kr_holidays.py`에
   다음 해 공휴일(날짜·이름, 대체공휴일 포함)을 추가합니다. 공공데이터포털 「특일 정보」로 대조해도 됩니다.
   사람이 대조하는 자료일 뿐이며 실행 중에는 호출하지 않습니다.
2. 갱신을 잊어도 조용히 틀리지 않도록 경고가 나옵니다.
   - 표에 없는 해가 되면 실행 로그와 수집 결과(collect.json)의 `calendar_warnings`에 경고가 남고,
     그 해는 주말만 휴무로 봅니다. 12월부터는 다음 해 표가 없을 때 미리 경고합니다.
     (같은 `calendar_warnings`에는 휴무일이 14일 이상 연속될 때의 경고도 실립니다 — 이때는 내장 표와
     `extra_holidays` 항목을 함께 확인합니다.)
   - `tests/test_kr_holidays.py`의 canary 테스트가 같은 조건에서 실패하므로 커밋 전 `pytest`에서도 걸립니다.
     (의도적으로 시계에 의존하는 정비 알림 테스트입니다.)
     `holiday_calendar: none`을 쓰는 사용자도 이 저장소에서 `pytest`를 돌리면 이 canary를 만날 수 있습니다.
     canary는 이 저장소의 내장 표 유지보수 알림이라 설정에 따라 끄지 않습니다.
   - `holiday_calendar: none`이면 내장 표를 쓰지 않으므로 표에 없는 해 경고는 나오지 않습니다(14일 연속 휴무 경고는 그대로).
3. 임시공휴일이 발표되면 표를 고치지 않고 config.yaml의 `extra_holidays`에 한 줄 추가합니다.

---

## 5. 단발성 조회 모드

특정 시점의 데이터를 조회하되 운영 대시보드를 변경하지 않으려면 `--ad-hoc` 플래그를 사용합니다.

### Collect (수집)

```bash
python -m pulse.publish collect --config config.yaml --period daily \
  --now "2026-07-20T00:00:00+09:00" --ad-hoc
```

- **dated 파일만 생성**: `pulse-2026-07-20.html` (latest.html 미생성)
- 주간(`--period weekly|both`) ad-hoc은 요청일이 속한 주의 지난주 월~일을 담고, 파일은 `pulse-weekly-<요청일>.html`만 생성합니다.
- **운영 상태 불변**:
  - `data/raw/` 미저장 (조회 시 원본 활동 기록 안 함)
  - `data/snapshots/` 미저장 (브랜치 변화 추적 안 함)
  - `data/weekly_publish/latest.json` 미갱신
  - `pending.json` 미저장 (지문 기록 안 함)
  - `data/analysis/cache.json` 미병합 (AI 분석 캐시 격리)

### Inject (주입)

```bash
python -m pulse.publish inject --config config.yaml --summary-file summary.json \
  --period daily --ad-hoc --date 2026-07-20
```

- `--ad-hoc --date YYYY-MM-DD` 필수
- 같은 날짜의 dated 파일만 주입 (`latest.html` 미접촉)

### 알려진 한계

ad-hoc 조회는 조회 전용 모드이므로 다음이 제한됩니다:

- **브랜치 생성/삭제 신호**: snapshot이 저장되지 않으므로, 해당 시점의 신규 브랜치 감지 없음
- **주간 신규작업 baseline**: snapshot 부재로 주간 신규 작업 신호 비활성화
- **조회 이력 관리**: 단발성 조회만 지원, 과거 조회 간 비교 기능 없음

---

## 6. config 작성법

### 기본 설정

`config.yaml` 파일을 작성합니다. 예시를 복사해서 시작할 수 있습니다:

```bash
cp config.yaml.example config.yaml
```

### 설정 항목 설명

```yaml
team_name: "샘플 팀"
# 팀의 이름. 대시보드 헤더에 표시됩니다.

gitlab_url: "https://gitlab.example.com/"
# GitLab 서버 URL. 약식 레포 표기의 기준이 됩니다.

repos:
  - "https://gitlab.example.com/sample-group/sample-repo"          # GitLab 레포
  - "https://github.com/my-org/some-repo"                          # GitHub 레포
  # 수집 대상 레포. 전체 URL 권장 — URL의 호스트로 provider를 자동 판별합니다
  # (host가 github.com이면 GitHub, 그 외에는 GitLab).
  # GitLab과 GitHub 레포를 섞어도 되고, 하나의 대시보드로 합쳐집니다.
  # 약식(예: "namespace/repo")을 쓰면 위 gitlab_url 기준의 GitLab 레포로 해석됩니다.

lookback_hours: 24
# 일간 조회 기간의 폭(시간). 기본값 24시간.
# weekend_catchup이 true이면 이 값을 최소 폭으로 삼아 직전 영업일까지 넓어집니다.

weekend_catchup: true
# 직전 영업일(월~금, 공휴일 제외) 00:00부터 조회합니다. 월요일에 실행하면 금토일 72시간이 되는 것이
# 이 규칙의 특수 사례입니다. 주말·공휴일 활동을 놓치지 않기 위한 옵션.
# false이면 공휴일·주말과 관계없이 lookback_hours 그대로입니다.

# extra_holidays: ["2026-12-24"]
# 선택. 내장 한국 공휴일 표(pulse/kr_holidays.py)에 없는 휴무일(임시공휴일·회사 휴무)을
# YYYY-MM-DD 목록으로 추가합니다. 이 날은 영업일로 세지 않습니다. 생략하면 빈 목록입니다.

# holiday_calendar: kr
# 선택. 쓸 공휴일 표: kr(기본값, 내장 한국 공휴일 표) 또는 none(표를 쓰지 않음 — 쉬는 날은
# 주말과 extra_holidays뿐). 따옴표 없는 none은 문자열로 읽힙니다. 비우거나 null·no·off로 적으면 오류입니다.

timezone: "Asia/Seoul"
# 로컬 타임존. weekend_catchup, 스케줄 시간 판정에 사용.

output_dir: "./reports"
data_dir: "./data"
# 수집 데이터와 대시보드 출력 경로.

stagnation_thresholds:
  review_waiting_days: 3
  # 이 일수 이상 리뷰 대기 중인 MR을 경고로 표시합니다.
  
  no_push_days: 7
  # 이 일수 이상 push가 없는 오픈 브랜치를 경고로 표시합니다.

exclude_bot_authors: []
# 커밋에서 제외할 봇 계정 목록 (선택사항).
# 예: ["dependabot[bot]", "renovate"]

retention_days: 90
# 수집 데이터(data/raw, data/snapshots)와 날짜별 대시보드(reports/pulse-YYYY-MM-DD.html)를
# 며칠간 보관할 것인가. 실행 시 자동으로 오래된 파일을 정리합니다.
# reports/latest.html은 날짜 파일이 아니므로 절대 삭제되지 않습니다.

grouping_hints:
  # 자동 분류를 오버라이드하는 수동 힌트 (선택사항).
  # 대시보드를 사용하면서 미분류 항목이 많으면 여기에 추가합니다.
  
  branch_prefixes:
    "feature/login": "로그인 개편"
    # 브랜치 이름이 "feature/login"으로 시작하면 "로그인 개편" 그룹에 배치
  
  directories:
    "src/components/editor": "에디터"
    # 변경된 파일이 이 경로에 있으면 "에디터" 그룹에 배치
  
  labels:
    "payment": "결제"
    # MR에 이 라벨이 있으면 "결제" 그룹에 배치

  release_line_patterns: ["main", "master", "develop", "dev", "test", "sqa", "devqa", "release", "hotfix"]
  # release/integration 라인 판별 패턴 (선택 — 생략 시 위 기본값).
  # 그룹의 브랜치명이 대소문자 무시 완전 일치하면 "릴리스/검증 라인"으로 분류돼
  # 기능 목록과 분리된 표에 표시됩니다.

issue_tracking:
  url_template: "https://jira.example.com/browse/{key}"
  # 선택. 설정하면 커밋/브랜치/MR 제목에서 추출된 이슈 키(예: DOCS-123)가
  # 대시보드에서 링크로 표시됩니다. 트래커 API는 호출하지 않습니다.
```

### 설정 검증

수정 후 설정 파일을 검증합니다:

```bash
python daily_pulse.py --config config.yaml
# 설정 오류가 있으면 exit code 2로 실패
```

---

## 7. 로컬 실행

### 기본 실행

```bash
python daily_pulse.py
```

- 기본 설정 파일 `config.yaml`를 읽습니다.
- `data/raw/YYYY-MM-DD/` 디렉토리에 수집 데이터를 저장합니다.
- 일간 대시보드 `reports/pulse-YYYY-MM-DD.html`과 `reports/latest.html`(복사본)을 생성합니다.
- **주간 대시보드**(`reports/pulse-weekly-YYYY-MM-DD.html`, `latest-weekly.html`): `python daily_pulse.py`는 실행할 때마다 롤링 168시간 기준으로 함께 만듭니다(발행 게이트·창 정렬 없음, 파일 이름의 날짜는 실행일). 운영 경로인 `pulse.publish collect`는 **영업일에 그 주 주간이 아직 없을 때만** 자동 발행합니다(보통 월요일, 월요일이 공휴일이면 다음 영업일. 이미 발행됐으면 기존 파일 유지, `--period weekly --force-weekly`로 강제 가능 — 조회 기간은 항상 지난주 월~일이고 파일 이름의 날짜는 실행일입니다). 일간↔주간은 대시보드 헤더 링크로 서로 이동합니다.

### Exit Code 해석

| Code | 의미 | 액션 |
|------|------|------|
| **0** | 성공 | 대시보드 생성 완료. `reports/latest.html`을 브라우저로 열어보십시오. |
| **1** | 파이프라인 오류 | 모든 레포 수집에 실패했거나, 수집 중 오류 발생. 로그를 확인하십시오. |
| **2** | 설정 오류 | `config.yaml` 형식 오류 또는 필수 필드 누락. 설정을 확인하십시오. |

### 산출물

```
reports/
├── pulse-2026-07-16.html          # 해당 일자 일간 대시보드
├── pulse-weekly-2026-07-13.html   # 주간 대시보드 (pulse.publish collect 경로: 파일 이름의 날짜는 발행일)
├── latest.html                    # 최신 일간 (복사본)
└── latest-weekly.html             # 최신 주간 (복사본)

data/
├── raw/                           # 일자별 수집 원본 (레포별 JSON)
│   └── 2026-07-16/
│       ├── sample-group__sample-repo.json
│       └── my-org__some-repo.json # GitHub 레포도 동일 구조로 저장
├── snapshots/                     # 브랜치 스냅샷 (신규/삭제 브랜치 비교용)
└── analysis/                      # 그룹 분석 캐시 (AI 제목·분석 재사용)
    └── cache.json
```

**첫 실행 시 주의사항**:  
대시보드의 "변화(Diff)" 섹션은 전일 데이터가 있을 때만 표시됩니다. 첫 실행 후 이틀째부터 변화가 표시됩니다.

#### 변화(Diff) 해석

**비교 기준일**: 변화 라벨의 날짜는 이전 수집 시간에 따라 정해집니다.
- 이전 수집이 **자정(00:00:00)** 이면, 비교 기준일 = 수집일 - 1일
- 이전 수집이 **비자정**(예: 14:30) 이면, 비교 기준일 = 수집일 (그대로)

예시 (calendar-aligned 운용 기준):
- **7/24 발행** (7/23 데이터 기반)에서 이전 raw가 7/23 자정 수집 → 라벨 "**2026-07-22 대비**" (표시: 어제 7/22의 2일 전)
- **7/24 09:00 수동 실행** (7/23 14:30 수집) → 라벨 "**2026-07-23 대비**" (표시: 어제 7/23과 비교)

이렇게 함으로써 자정 기준 정렬 운영(--now T00:00)에서도 정확한 비교 기준을 표시합니다.

**노이즈 제거**: "기타(other)" 단계로의/로부터의 전이는 표시하지 않습니다.
- "기타"는 분류 실패 상태로, 정보가치가 낮기 때문입니다.
- **의미 있는 전이만 표시**:
  - 개발 ↔ 리뷰 ↔ 머지 (모든 방향)
  - 예: 개발 → 리뷰 (검토 시작), 머지 → 개발 (재작업)

### 대시보드 확인

```bash
# 브라우저에서 직접 열기
open reports/latest.html         # macOS
xdg-open reports/latest.html     # Linux
start reports/latest.html        # Windows

# 또는 Python 간단한 웹 서버로 보기 (권장)
python -m http.server 8000 -d reports
# 브라우저에서 http://localhost:8000/latest.html 방문
```

### 대시보드 공유

`reports/latest.html`과 `reports/latest-weekly.html`은 외부 자원을 쓰지 않는 단일 HTML 파일입니다.
일간 화면의 주간 전환 링크가 같은 폴더의 `latest-weekly.html`을 가리키므로, **두 파일을 같은 경로에 함께**
올리면 팀이 쓰는 정적 웹 서버·객체 스토리지·공유 폴더 등 어디서든 그대로 열립니다.

- 대시보드에는 커밋·MR 제목, 브랜치 이름, AI 요약 등 팀 활동 정보가 들어 있습니다. 비공개 레포를 수집했다면
  접근이 팀으로 제한된 곳에만 올리고, 누구나 볼 수 있는 공개 호스팅에는 올리지 마십시오.
- 업로드 방식은 환경마다 달라 이 저장소에 포함하지 않습니다. 정기 발행(8장) 뒤에 복사 작업을 cron·launchd로 따로 걸면 됩니다.

---

## 8. 스케줄 배포

일일 자동 실행을 위해 아래 중 하나를 선택합니다.

### 8-1. AI 요약 포함 자동 발행 — launchd + Claude Code 헤드리스 (권장, macOS)

> **작성자 운영 예시입니다.** 이 절의 자동 발행 장치(`scripts/`의 러너·프롬프트·plist)는
> 작성자 환경 — macOS launchd, Claude 계정(`claude -p`) — 을 전제로 한 운영 예시입니다.
> 범용 본체는 `pulse/`와 발행 스킬 2종(`daily-pulse-publish-daily`·`daily-pulse-publish-weekly`)이며,
> 다른 환경에서는 이 장치를 참고용으로 보고 8-2~8-4의 CLI 방식으로 시작할 수 있습니다.

`scripts/`에 동봉된 러너가 매일 09:00에 Claude Code(`claude -p`)를 헤드리스로 실행해
발행 전 과정(수집 → AI 요약 작성 → 주입)을 수행합니다:

| 파일 | 역할 |
|---|---|
| `scripts/scheduled-publish.sh` | 러너 — 날짜 치환, 종료 마커(`PULSE_PUBLISH_OK/PARTIAL/FAIL`) 판정, 실패 시 macOS 알림 |
| `scripts/scheduled-publish-prompt.md` | 헤드리스 실행 지시문 (스킬 문서 2개가 절차의 단일 기준) |
| `scripts/com.daily-pulse.publish.plist.example` | launchd 스케줄 정의 템플릿 (매일 09:00, 경로는 자리표시자) |

설치 — 저장소 루트에서 실행합니다. 템플릿의 자리표시자(`/path/to/daily-pulse`, `/Users/USERNAME`)를
내 경로로 채워 설치 위치에 씁니다. 그대로 `cp` 하면 존재하지 않는 경로를 가리킵니다:

```bash
sed -e "s|/path/to/daily-pulse|$(pwd)|g" -e "s|/Users/USERNAME|$HOME|g" \
  scripts/com.daily-pulse.publish.plist.example > ~/Library/LaunchAgents/com.daily-pulse.publish.plist
launchctl bootout gui/$(id -u)/com.daily-pulse.publish 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.daily-pulse.publish.plist
```

운영 특성:

- 잠자기 중 시각을 놓치면 깨어날 때 실행되고, 맥이 꺼져 있던 날은 건너뜁니다.
  월요일 주간 발행이 누락되면 그 주의 다음 영업일 실행이 같은 수집 한 번으로 보완합니다
  (조회 기간은 정기 발행과 같고 파일 이름의 날짜만 보완한 날입니다).
- 로그: `~/Library/Logs/daily-pulse/publish-YYYY-MM-DD.log` (30일 보관)
- 수동 실행: `scripts/scheduled-publish.sh` /
  즉시 1회 기동: `launchctl kickstart gui/$(id -u)/com.daily-pulse.publish` /
  해제: `launchctl bootout gui/$(id -u)/com.daily-pulse.publish`
- 요구사항: GitLab/GitHub 토큰이 환경변수 또는 keyring에 저장돼 있어야 합니다(2장 참조).
- 러너는 대시보드를 만들기만 하고 어디에도 올리지 않습니다. 공유는 7장 「대시보드 공유」를 참고합니다.

> **Claude cowork · claude.ai 예약 작업은 부적합** (2026-07-24 실측):
> cowork는 격리 Linux 샌드박스에서 실행되어 macOS venv 실행 불가,
> 네트워크 allowlist가 사설망의 자체 호스팅 GitLab을 차단, macOS 키체인(keyring) 접근 불가.
> claude.ai 예약 작업은 Anthropic 클라우드 실행이라 사설망의 GitLab에 접근할 수 없습니다.
> GitLab에 접근 가능한 네트워크 안의 맥에서 실행해야 하므로 launchd 방식을 씁니다.

### 8-2. macOS launchd — CLI 전용 (AI 요약 없음)

`docs/schedule/launchd.example.plist`를 참고해서 설정합니다:

```bash
# 1. 설정 파일 복사 (경로 및 토큰 방식 수정 필수)
cp docs/schedule/launchd.example.plist ~/Library/LaunchAgents/com.daily-pulse.automation.plist

# 2. 로드
launchctl load ~/Library/LaunchAgents/com.daily-pulse.automation.plist

# 3. 작동 확인
launchctl list | grep daily-pulse
```

**주의**: 환경 변수(`GITLAB_TOKEN`, `GITHUB_TOKEN`)는 plist에 포함하지 마세요. 로컬 셸 설정(`~/.zshrc`)에서 로드하십시오.

### 8-3. Linux/Unix crontab

`docs/schedule/crontab.example`을 참고합니다:

```bash
# 편집
crontab -e

# 아래를 추가 (KST 08:00 평일 실행)
0 8 * * 1-5 /path/to/daily-pulse/.venv/bin/python /path/to/daily-pulse/daily_pulse.py --config /path/to/daily-pulse/config.yaml >> /path/to/daily-pulse/cron.log 2>&1

# 확인
crontab -l
```

**절대 경로 사용 필수** (크론은 특정 디렉토리 컨텍스트를 가정하지 않음).

### 8-4. 자체 호스팅 GitLab CI/CD

프로젝트 루트의 `.gitlab-ci.yml.example`을 참고합니다:

```bash
# 1. 프로젝트의 .gitlab-ci.yml에 병합 (또는 신규 생성)
# 2. CI/CD 변수(masked)로 GITLAB_TOKEN 설정
#    (config에 GitHub 레포가 있으면 GITHUB_TOKEN도 같은 방식으로 추가)
#    GitLab 웹 UI → Settings → CI/CD → Variables
# 3. Schedules에서 KST 08:00 평일 스케줄 생성
#    Settings → CI/CD → Schedules

# 주의: 러너가 GitLab 서버에 네트워크로 접근할 수 있어야 합니다.
```

---

## 9. Skill을 이용한 대화형 발행 (권장)

Claude Code Skill을 이용하면 대화형으로 대시보드를 발행하고 **AI 흐름 요약·그룹별 제목/분석**을 자동 작성할 수 있습니다. 프로젝트에 2개 Skill이 포함돼 있습니다:

| Skill | 용도 | 호출 예 |
|---|---|---|
| `daily-pulse-publish-daily` | 일간 대시보드 발행 | "일간 발행해줘" |
| `daily-pulse-publish-weekly` | 주간 대시보드 발행 (영업일 게이트, `--force-weekly`로 우회) | "주간 발행해줘" |

발행 Skill이 수행하는 흐름:

1. **토큰 검증** — `python -m pulse.publish token status` (env → keyring → gh 폴백)
2. **수집** — `python -m pulse.publish collect --config config.yaml --period daily|weekly` (특정 시각 기준은 `--now "2026-07-23T00:00:00+09:00"` — 00:00이면 조회창이 달력에 정렬됨)
3. **요약·분석 작성** — Claude가 레포별 요약과 그룹별 제목/분석 작성. **캐시 히트 그룹(`cached: true`)은 생략 가능** — 이전 분석이 자동 재사용됩니다.
4. **주입** — `python -m pulse.publish inject --config config.yaml --summary-file summary.json --period daily|weekly`
5. **결과 안내** — 대시보드 경로 + 요약 + 공유용 스니펫

부가 기능: 요약 없는 CLI 폴백(자동 실행용, AI 슬롯은 비표시로 우아한 저하), config.yaml 레포 추가/삭제/닉네임 편집.

### 이슈 트래커 연동 (선택)

커밋/브랜치/MR에서 추출된 이슈 키는 `issue_tracking.url_template` 설정 시 대시보드에서 링크가 됩니다. Jira MCP가 연결된 환경에서는 발행 Skill이 이슈 제목·상태를 조회해 분석에 참고할 수 있습니다(미연결 시 자동 생략 — 코어는 트래커 API를 호출하지 않습니다).

---

## 10. 자동 실행 이중화

**1급 (요약 O): launchd + Claude Code 헤드리스 (8-1 참조)**
- 매일 09:00 `claude -p`가 발행 스킬 절차를 그대로 수행 (수집 → AI 요약 → 주입)
- AI 흐름 요약 포함 → 가장 좋은 품질
- **제약**: 맥이 켜져 있고 GitLab 서버에 접근 가능한 네트워크에 있어야 함
  (cowork·claude.ai 예약 작업은 샌드박스/클라우드 실행이라 부적합 — 8-1의 실측 노트 참조)

**폴백 (요약 X): 순수 CLI + cron/launchd/GitHub Actions/GitLab CI**
- 배포 서버/자체 호스팅 러너에서 자동 실행 (8-2 ~ 8-4 참조)
- AI 요약 없음 (graceful degradation — HTML 슬롯이 비표시)
- **장점**: Claude Code 없이 어디서나 작동
- 토큰은 예시처럼 명령행·plist에 평문으로 넣지 말고, 셸 설정 로드 또는 keyring을 사용하십시오 (2장 참조)

### GitHub Actions 예시

`.github/workflows/daily-pulse-cli.yml.example`을 참고하세요.
공개 GitHub 레포 수집: 이 워크플로우를 그대로 사용 가능.
사설망의 자체 호스팅 GitLab 수집: self-hosted 러너 필요.

### GitLab CI 예시

`.gitlab-ci.yml.example`을 참고하세요.
러너가 GitLab 서버에 접근할 수 있는 네트워크에 있으면 그대로 사용 가능.

---

## 11. 실서버 첫 실행 체크리스트

```
[ ] 1. GitLab PAT 발급 (read_api 스코프)
    GitHub 레포도 수집한다면: GitHub PAT 발급 (Contents/Pull requests read)
[ ] 2. 환경 변수 설정: export GITLAB_TOKEN="..." (+ 필요 시 GITHUB_TOKEN)
[ ] 3. config.yaml 작성 (config.yaml.example 복사)
[ ] 4. 수동 1회 실행: python daily_pulse.py
[ ] 5. 출력 로그에서 API 요청 수와 429 오류 확인
    - "요청 수: N개"라는 로그가 있어야 함
    - 429 오류가 있으면 rate limit에 걸린 것 — 대기 후 재시도
[ ] 6. reports/latest.html 생성 확인
[ ] 7. 브라우저에서 대시보드 열어서 데이터 정상 표시 확인
[ ] 8. 스케줄 등록 (AI 요약 포함 8-1 권장 / CLI 전용 crontab·launchd·GitLab CI)
[ ] 9. 스케줄 첫 자동 실행 확인 (로그 또는 대시보드 날짜)
```

---

## 12. 추가 문서

- **[정기 발행 러너](scripts/)** — AI 요약 포함 launchd 헤드리스 발행 (scheduled-publish.sh · prompt · plist)
- **[스케줄 예시](docs/schedule/)** — crontab, launchd 설정 파일 (GitLab CI는 루트 `.gitlab-ci.yml.example`, GitHub Actions는 `.github/workflows/daily-pulse-cli.yml.example`)
- **[개발 가이드](CLAUDE.md)** — 프로젝트 개발 지침
- **Skill 정의** — [일간 발행](.claude/skills/daily-pulse-publish-daily/SKILL.md) · [주간 발행](.claude/skills/daily-pulse-publish-weekly/SKILL.md)

---

## 라이선스

[MIT License](LICENSE)
