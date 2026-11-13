# Daily Pulse — 프로젝트 지침

이 저장소에서 작업하는 코딩 에이전트(Claude Code 등)를 위한 프로젝트 지침이다.

## 프로젝트 개요

팀의 깃 레포 활동(커밋, 브랜치, MR)을 매일 수집·분석해 프로젝트/기능 단위로
그룹핑하고, HTML 대시보드로 브리핑하는 도구.
v1 대상 저장소는 **자체 호스팅 GitLab**(주소는 저장소에 적지 않고 로컬 `config.yaml` 에만 둔다)이며,
collector의 provider 추상화를 통해 GitHub 레포도 지원하는 범용 솔루션을 지향한다.
목적은 **프로젝트 흐름 파악**이며 개인 실적 평가가 아니다.
개인별 커밋 수 랭킹, 코드 라인 수 비교 등 실적 지표는 만들지 않는다.

## 아키텍처

레이어를 다음과 같이 분리하고, 레이어 간에는 명시적 데이터 모델로만 통신한다:
- **collector**: Git 호스팅 API에서 원본 활동 데이터 수집 (외부 I/O 전담).
  내부에 `GitProvider` 추상화를 두고 구현체(GitLab REST v4, GitHub)가
  정규화된 데이터 모델로 반환 — 다른 레이어는 provider를 모른다.
- **grouper**: 활동을 프로젝트/기능 단위로 클러스터링 (순수 로직)
- **renderer**: 그룹핑 결과를 HTML 대시보드로 렌더링 (순수 로직 + 파일 출력)
- **config**: 설정 파일(config.yaml) 로딩과 검증

## 성능

이 프로젝트의 병목은 **Git 호스팅 API 호출**이다. 최적화 우선순위:
1. API 호출 횟수 최소화 (브랜치 목록으로 활동 브랜치를 먼저 선별한 뒤
   해당 브랜치만 커밋 조회, 필요한 필드만 요청)
2. 레포 단위 병렬 요청 (동시성 제한 5)
3. 변경 없는 데이터 재다운로드 방지 (조건부 요청/스냅샷 재사용)

API 요청 수와 429 응답을 매 실행 로깅하고, 제한에 걸리면 대기 후 재시도한다.

## 빌드 / 검증 명령
- 실행: `python daily_pulse.py` (예시)
- 테스트: `pytest`
- lint/format: `ruff check . && ruff format --check .`
- type check: `mypy .`

## 고유 컨벤션

- 액세스 토큰은 환경변수(GitLab `GITLAB_TOKEN`(`read_api` 스코프), GitHub `GITHUB_TOKEN`)를
  우선하고, 없으면 OS 키링(`python -m pulse.publish token set`), GitHub은 그다음
  `gh auth token` 순으로 읽는다. 코드/설정 파일에 저장 금지.
- 추적 파일(문서·예시·테스트)에 실제 서버 주소·IP·개인 절대경로를 적지 않는다.
  예시 값은 `https://gitlab.example.com`, `sample-group/sample-repo`, `/path/to/daily-pulse`.
- 수집 원본 데이터는 레포별 분리 저장 `data/raw/YYYY-MM-DD/{repo}.json`, 대시보드는
  `reports/pulse-YYYY-MM-DD.html` + `reports/latest.html`(복사본).
- 특정 레포 수집 실패 시 전체를 중단하지 않고 해당 레포만 스킵,
  대시보드에 "수집 실패" 표시.
