"""인라인 CSS — 라운드 10 벤치마크 전면 채택.

CSS 문자열은 HTML 시맨틱상 라인 길이 제한이 적용되지 않음 (일반 텍스트 레이아웃과 달리).
"""

# ruff: noqa: E501

CSS = """:root {
  --bg: #f2f3f5;
  --panel: #ffffff;
  --ink: #1a1d21;
  --secondary: #4b5563;
  --muted: #8b919a;
  --line: #e8eaed;
  --track: #eef0f3;
  --accent: #3b82f6;
  --accent-soft: #eaf1fe;
  --shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 2px 8px rgba(16, 24, 40, .04);
  --hi: #e5484d;
  --hi-bg: #fdebec;
  --high: #b45309;
  --high-bg: #fef3c7;
  --done: #3d9a50;
  --done-bg: #e9f6ec;
  --prog: #3b82f6;
  --prog-bg: #eaf1fe;
  --todo: #6b7280;
  --todo-bg: #eef0f3;
  --qa: #0e7490;
  --qa-bg: #e2f5fa;
  --color-info: #3b82f6;
  --color-warning: #b45309;
  --duration-fast: 120ms;
  --easing-out: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --space-xs: 4px;
  --space-sm: 6px;
  --space-lg: 12px;
  --text-sm: 12.5px;
}

* { box-sizing: border-box; }

/* overflow-x: clip — 닫힌 툴팁 말풍선(visibility:hidden이라 자리는 차지한다)이
   좁은 화면에서 가로 스크롤을 만드는 것을 막는다. hidden이 아니라 clip을 쓰는 이유는
   clip이 스크롤 컨테이너를 만들지 않아 열린 말풍선의 배치·가장자리 보정에 영향이 없다.
   (sticky/fixed 자손이 없어 clip의 알려진 부작용도 해당하지 않는다.) */
/* 스크롤바 숨김(스크롤 동작은 유지) — 공간 차지형(클래식) 스크롤바 환경에서
   세로 스크롤바가 생기고 사라질 때(details 펼침 등) 본문 가로 폭이 바뀌며 화면이
   튀는 것을 막는다. scrollbar-width는 Firefox·Chrome 121+,
   ::-webkit-scrollbar는 Safari·구형 Chromium을 커버한다. */
html {
  background: var(--bg);
  overflow-x: clip;
  scrollbar-width: none;
}

html::-webkit-scrollbar { display: none; }

body {
  margin: 0 auto;
  max-width: 1180px;
  overflow-x: clip;
  padding: 28px 20px 60px;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ━━━ 헤더 ━━━ */
.page-header { margin-bottom: 18px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.2px; font-weight: 700; }
.page-meta { color: var(--muted); font-size: 13px; }
.period-switch { font-weight: 600; }

/* ━━━ 탭 — 밑줄 방식 ━━━ */
.tab-radio { display: none; }
.tab-navigation {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 18px;
  border-bottom: 1px solid var(--line);
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  max-width: 220px;
}
/* 말줄임은 이름에만 걸어 확인 필요 점이 잘려나가지 않게 한다
   (min-width:0이 없으면 flex 아이템이 콘텐츠 폭 아래로 줄지 않아 말줄임이 동작하지 않는다) */
.tab-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
/* 확인 필요 점 — 조회 기간 내 커밋·MR이 있는 탭에만 붙는다 */
.tab-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}
.tab-label:hover { color: var(--ink); }
.tab-content { display: none; }

/* ━━━ 레포 헤더 (카드 아님 — 컴팩트 텍스트 블록) ━━━ */
section.repo-header {
  background: none;
  border: none;
  box-shadow: none;
  padding: 0;
  margin: 0 2px 12px;
}
.repo-path { font-size: var(--text-sm); }
.repo-path a { color: var(--muted); word-break: break-all; }
.repo-path a:hover { color: var(--accent); }
.summary-line { font-size: 13px; color: var(--secondary); margin-top: 2px; }

/* ━━━ KPI 스트립 ━━━ */
.kpi-row { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 14px; }
.kpi {
  flex: 1;
  min-width: 150px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 16px 20px;
  box-shadow: var(--shadow);
}
.kpi .l { color: #5f6570; font-size: 13px; margin-bottom: 6px; }
.kpi .n {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -.6px;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.kpi.kpi-warn .n { color: var(--hi); }
.kpi .n .unit { font-size: 13px; font-weight: 600; color: var(--muted); letter-spacing: 0; margin-left: 2px; }

/* ━━━ 존 카드 (섹션 공통) ━━━ */
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 20px 24px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
}
section h2 {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 700;
  border: none;
  padding: 0;
  letter-spacing: -.2px;
}
.section-description { font-size: 12.5px; color: var(--muted); margin: 0 0 14px; }

/* ━━━ AI 브리핑 — 불투명 accent-soft 면 ━━━ */
section.ai-summary {
  background: #eaf1fe;
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 14px;
  box-shadow: none;
}
.ai-summary h2 { color: var(--accent); font-size: 14px; font-weight: 700; margin: 0 0 8px; border: none; padding: 0; }
.ai-summary-content { margin: 0; font-size: 13.5px; line-height: 1.65; color: var(--ink); }
.ai-summary ul { margin: 0; padding-left: 18px; }
.ai-summary li { margin: 4px 0; font-size: 13.5px; line-height: 1.65; color: var(--ink); }
/* 개선점 문단 — 브리핑 카드 안의 둘째 문단. 면을 깔면 카드 안 카드가 되므로
   점선 구분선과 소제목으로만 나눈다(.mr-mini-history 와 같은 원칙). */
.ai-summary-impact {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed color-mix(in srgb, var(--accent) 30%, transparent);
}
.ai-summary-impact-label { margin: 0 0 4px; font-size: 12.5px; font-weight: 700; color: var(--accent); }

/* ━━━ AI 텍스트 강조 마커 (textmark.py 변환 결과) ━━━
   **…** → mark.ai-mark 형광펜, ⚠ 접두 불릿 줄 → li.attention 주의 콜아웃.
   ai-summary와 group-analysis(기능/라인 행 펼침)가 공유한다. */
mark.ai-mark {
  background: var(--high-bg);
  color: inherit;
  font-weight: 600;
  padding: 0 3px;
  border-radius: 3px;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
}
.ai-summary li.attention,
.group-analysis li.attention {
  /* 불릿 대신 좌측 보더가 주의 표식 — 리스트 들여쓰기(18px)를 되돌려 전폭을 쓴다 */
  list-style: none;
  margin-left: -18px;
  padding: 3px 10px;
  border-left: 3px solid var(--color-warning);
  background: var(--high-bg);
  border-radius: 0 6px 6px 0;
}

/* ━━━ 상태 배지 (스테퍼 대체) ━━━ */
.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.b-done { background: var(--done-bg); color: var(--done); }
.b-prog { background: var(--prog-bg); color: var(--prog); }
.b-qa { background: var(--qa-bg); color: var(--qa); }
.b-todo { background: var(--todo-bg); color: var(--todo); }

/* ━━━ 기능 행 (확장형) ━━━ */
.feature-list { display: flex; flex-direction: column; gap: 8px; }
.feature-row {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.feature-row > summary {
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  list-style: none;
}
.feature-row > summary::-webkit-details-marker { display: none; }
.feature-row > summary:hover { background: #f8f9fb; border-radius: 10px; }
.feature-row[open] > summary { border-bottom: 1px solid var(--line); border-radius: 10px 10px 0 0; }
/* 닫힌 행 높이는 고정한다 — 최근 활동(상대시각)이 없는 행은 meta 열이 두 줄에서 한 줄로
   줄어들어 행 높이가 배지(21px)에 지배되고, 목록이 61px과 43px로 갈려 눈높이가 어긋난다.
   두 줄짜리 meta(규모 12.5px + 최근활동 12px + 사이 gap 2px ≈ 39px)를 기준으로 예약한다.
   height가 아니라 min-height인 이유: 좁은 화면에서 한 열로 접히면 자연 높이대로 늘어나야
   내용이 잘리지 않는다. */
.feature-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 80px 150px;
  gap: 14px;
  align-items: center;
  width: 100%;
  min-height: 39px;
}

/* 각 칸을 열에 고정한다 — 자동 배치에 맡기면 배지가 없는 행(단계 판정 불가)에서
   자식이 하나 줄어 스파크라인·규모가 한 열씩 당겨오고, 행마다 눈높이가 어긋난다.
   배지·스파크라인 래퍼가 tooltip-host를 공유하므로 전용 클래스로 구별한다. */
.feature-summary > .group-ai-title,
.feature-summary > .group-name {
  grid-column: 1;
}

.feature-summary > .stage-badge-wrap {
  grid-column: 2;
}

.feature-summary > .sparkline-wrap,
.feature-summary > .sparkline-empty {
  grid-column: 3;
}

.feature-summary > .feature-meta {
  grid-column: 4;
}
.group-name { font-weight: 600; font-size: 13.5px; color: var(--ink); }
.group-ai-title { font-weight: 600; font-size: 13.5px; color: var(--ink); }
.group-ai-title + .group-name { display: none; }
.group-ai-title + .line-name { display: none; }
.feature-summary .group-name,
.feature-summary .group-ai-title {
  margin-bottom: 0;
}
.feature-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
  font-size: 12.5px;
  color: var(--secondary);
  font-variant-numeric: tabular-nums;
}
.scale { font-weight: 600; }
.relative-time { color: var(--muted); font-size: 12px; }
.sparkline { height: 20px; width: 80px; }
.sparkline rect { fill: #9aa3af; }
.sparkline-empty { display: inline-block; width: 80px; height: 20px; }

/* ━━━ 확장 영역 ━━━ */
.feature-expand {
  padding: 14px 16px;
  background: #fafbfc;
  border-radius: 0 0 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}
.feature-expand > *:not(.group-analysis) {
  margin-left: var(--space-lg);
  margin-right: var(--space-lg);
}
.group-analysis { color: var(--ink); font-size: 13px; line-height: 1.65; }
.group-analysis ul { margin: 0; padding-left: 18px; }
.group-analysis li { margin: 3px 0; }
.task-summary { display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.task-label {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 8px 0 4px;
  white-space: nowrap;
  font-size: 12.5px;
}
.task-label:first-child { margin-top: 0; }
.task-label strong { display: inline; margin: 0; color: var(--secondary); }
.task-summary ul { margin: 0 0 0 8px; padding: 0; list-style: none; }
.task-summary li {
  margin: var(--space-xs) 0;
  padding-left: 14px;
  font-size: 12.5px;
  color: var(--secondary);
  position: relative;
}
.task-summary li:before { content: '·'; position: absolute; left: 2px; color: var(--muted); font-weight: 700; }
/* 잘린 나머지 건수 — 불릿을 주면 "외 N건"이라는 제목의 커밋으로 읽힌다.
   들여쓰기는 남겨 실제 제목들과 왼쪽 끝을 맞춘다. */
.task-summary li.task-more { color: var(--muted); }
.task-summary li.task-more:before { content: none; }
.feature-participants { font-size: 12.5px; color: var(--secondary); }
.feature-participants strong { color: var(--ink); }
.issue-keys { font-size: 12.5px; color: var(--secondary); }
.issue-keys a { margin-right: 8px; word-break: break-all; }
.unclassified-hint {
  padding: 10px 12px;
  background: var(--track);
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--secondary);
}

/* ━━━ MR 미니 이력 ━━━ */
/* 테두리·면을 주지 않는다 — 부모(.line-row/.feature-row)가 이미 카드라서 상자를 겹치면
   카드 안 카드가 된다. 형제 소제목(📝 커밋 · 🌿 브랜치)처럼 라벨과 행 구분선으로만 묶는다. */
.mr-mini-history { margin: 0; padding: 0; }
/* 소제목은 확장 영역의 커밋·브랜치 소제목(.task-label)과 같은 크기·색·간격으로 맞춘다.
   클래스를 따로 두는 이유: .task-label은 task_summary 섹션 수를 세는 기준이다.
   gap이 필요한 이유: .tooltip-host가 inline-flex라 "🔀 " 뒤 공백이 지워진다. */
.mr-history-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 2px 10px;
  margin-bottom: 4px;
}
.mr-history-label {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  font-size: 12.5px;
  color: var(--secondary);
}
.mr-history-label strong { color: var(--secondary); }
.mr-history-count { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
/* 상태 칸에 최소 폭을 준다 — 항목마다 grid가 따로여서 auto로 두면 라벨 길이
   ("병합됨" 3자 vs "닫힘" 2자)에 따라 뒤 칸이 행마다 어긋난다.
   56px = 최장 라벨 3자(11.5px) + 배지 좌우 패딩 9px 기준. minmax로 두는 이유:
   더 긴 라벨이 생겨도 그 행만 넓어지고 뒤 칸을 침범하지 않는다. */
.mr-history-item {
  display: grid;
  grid-template-columns: minmax(56px, auto) minmax(0, 1fr);
  gap: 2px 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--line);
}
.mr-history-item:last-child { border-bottom: none; }
/* 상태 배지를 왼쪽 여백에 세로로 걸쳐 고정한다 — 제목이 두 줄이 돼도 행마다 눈높이가 맞는다 */
.mr-history-item > .badge { grid-row: 1 / span 2; align-self: start; }
.mr-history-title { font-size: 12.5px; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }
.mr-history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  font-size: 11.5px;
  color: var(--secondary);
  font-variant-numeric: tabular-nums;
}
/* 합치는 방향은 이 줄의 핵심 사실이라 본문 색을 준다 */
.mr-flow { color: var(--ink); }
.mr-arrow { color: var(--muted); }
.mr-number a { color: var(--secondary); }
.mr-number a:hover { color: var(--accent); }

/* ━━━ 생애 타임라인 (주간) ━━━ */
.history-timeline {
  margin-top: 12px;
  margin-bottom: 12px;
  padding: var(--space-sm) 0;
  border-top: 1px dashed var(--line);
  border-bottom: 1px dashed var(--line);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-timeline-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 18px;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}
.history-start { font-weight: 700; color: var(--ink); }
.history-scale { color: var(--secondary); }
.history-chart { display: flex; flex-direction: column; gap: 4px; }
.history-chart-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.history-chart-head em { font-style: normal; font-weight: 700; letter-spacing: .05em; }
.history-weeks {
  display: flex;
  align-items: flex-end;
  gap: 5px;
  height: 56px;
  padding-bottom: 1px;
  border-bottom: 1px solid var(--line);
}
.history-week { flex: 0 0 22px; width: 22px; height: 100%; display: flex; align-items: flex-end; }
.history-week-bar {
  width: 100%;
  height: var(--bar, 0%);
  min-height: 2px;
  background: var(--accent);
  border-radius: 2px 2px 0 0;
  opacity: .55;
  transition: opacity var(--duration-fast) ease;
}
.history-week:hover .history-week-bar { opacity: .95; }
.history-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  font-size: 12.5px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.history-fact em {
  font-style: normal;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .05em;
  color: var(--muted);
  margin-right: 4px;
}
.history-fact-alert { font-weight: 700; color: var(--high); }

/* ━━━ 릴리스 승격 사다리 ━━━ */
.release-train {
  margin: 0 0 14px;
  padding: 20px 24px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow);
}
.release-train-label { font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.release-train-visual {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--secondary);
}
.train-rung {
  white-space: nowrap;
  padding: 5px 11px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 999px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.train-rung--stale { background: var(--high-bg); border-color: color-mix(in srgb, var(--high) 30%, transparent); color: var(--high); }
.train-connector { flex-shrink: 0; color: var(--muted); font-weight: 600; }
.mr-wait {
  display: inline-block;
  padding: 1px 8px;
  background: var(--hi-bg);
  color: var(--hi);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

/* ━━━ 릴리스/검증 라인 ━━━ */
.line-rows { display: flex; flex-direction: column; gap: 8px; }
/* overflow를 자르지 않는다 — 자르면 안에서 위로 열리는 툴팁 말풍선이 이 상자의
   윗변에서 잘린다(MR 이력 툴팁 206px 중 159px이 잘렸다). 모서리를 둥글게 유지하는
   일은 형제인 .feature-row와 같은 방식으로 한다: 잘라내는 대신 자식이 각자
   자기 모서리를 둥글게 한다(summary는 아래 규칙, 확장 영역은 .feature-expand). */
.line-row {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.line-row > summary { cursor: pointer; padding: 10px 14px; list-style: none; }
.line-row > summary::-webkit-details-marker { display: none; }
.line-row > summary:hover { background: #f8f9fb; border-radius: 10px; }
/* [open]은 :hover와 명시도가 같아 뒤에 와야 이긴다 — 펼친 상태의 아래 모서리는 각져야
   확장 영역과 이어 붙는다 */
.line-row[open] > summary { border-bottom: 1px solid var(--line); border-radius: 10px 10px 0 0; }
.line-summary {
  display: grid;
  grid-template-columns: minmax(7rem, 14rem) 1fr auto;
  align-items: center;
  gap: 14px;
}
.line-head { display: flex; align-items: center; gap: 6px; min-width: 0; }
.line-name { font-weight: 600; font-size: 13.5px; }
/* 제목은 한 줄로 잘라 말줄임한다 — 제목 칸은 폭이 고정(minmax(7rem, 14rem))이라 긴 제목이
   두 줄로 접히면서 닫힌 행이 42px과 60px로 갈린다(주간 제목이 길어지면 실제로 발생).
   행마다 그리드가 따로라 칸 폭을 내용에 맞춰 늘리면 행끼리 표가 어긋나므로, 같은 행의
   가운데 칸(.line-latest)과 같은 방식으로 맞춘다. 잘린 뒷부분은 행을 펼치면 분석에서 읽힌다. */
.line-head > .group-ai-title,
.line-head > .line-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.line-latest {
  font-size: 12.5px;
  color: var(--secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.line-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ━━━ 신규 작업 ━━━ */
.new-work-item {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 10px 14px;
  margin-bottom: 8px;
  border-radius: 10px;
  font-size: 13px;
}
.new-work-item:last-child { margin-bottom: 0; }
.new-work-title { font-weight: 600; margin-bottom: 2px; }
.new-work-repo { font-size: 12px; color: var(--muted); }

/* ━━━ 주의 신호 ━━━ */
.warning-summary { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.warning-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--hi-bg);
  color: var(--hi);
  white-space: nowrap;
}
.warning-badge-collection-failure { background: var(--hi); color: #fff; }
.warning-group { margin: 8px 0 0; border: 1px solid var(--line); border-radius: 10px; }
.warning-group > summary {
  padding: 10px 14px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
  color: var(--secondary);
  list-style: none;
}
.warning-group > summary::-webkit-details-marker { display: none; }
.warning-group > summary:hover { background: #f8f9fb; border-radius: 10px; }
.warning-group[open] > summary { border-bottom: 1px solid var(--line); }
.warning-items { padding: 10px 12px; }

/* 경고 행 — 한 줄 조밀 배치 */
.warning-item {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 14px;
  margin-bottom: 6px;
  font-size: 13px;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
}
.warning-item:last-child { margin-bottom: 0; }
.warning-description { font-size: 13px; color: var(--ink); font-weight: 600; }
.warning-detail { font-size: 12.5px; color: var(--secondary); }
/* 상세 링크는 행 오른쪽 끝으로 — 어느 행이든 같은 위치에서 눈에 걸리게.
   :last-child로 밀면 링크가 없는 행에서는 설명이 오른쪽으로 밀려간다. */
.warning-link { margin-left: auto; }
.warning-item a { font-size: 12.5px; }

/* 심각도 상위 두 단계만 면으로 강조 */
.warning-item--notable { background: var(--high-bg); border-color: color-mix(in srgb, var(--high) 30%, transparent); }
.warning-item--severe { background: var(--hi-bg); border-color: color-mix(in srgb, var(--hi) 30%, transparent); }
.warning-item--severe .warning-description { color: var(--hi); }

/* ━━━ 변화 / 참여 / 기타 ━━━ */
.diff-items { font-size: 13px; }
.diff-item { padding: 6px 0; border-bottom: 1px solid var(--line); }
.diff-item:last-child { border-bottom: none; }
.participation-section { display: none; }
body.show-participation .participation-section { display: block; }
.participation-map { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.participation-entry {
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 12.5px;
}
.participation-name { font-weight: 700; margin-bottom: 6px; }
.participation-groups { color: var(--muted); }
.empty-state { text-align: center; color: var(--muted); padding: 14px; font-size: 13px; }
footer.meta {
  margin-top: 20px;
  font-size: 12px;
  color: var(--muted);
  text-align: center;
}
footer.meta p { margin: 0; }

/* ━━━ 커스텀 툴팁 (기존 시스템 유지) ━━━ */
.tooltip-host { position: relative; display: inline-flex; cursor: help; }
.tooltip-bubble {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%) translateY(4px);
  width: max-content;
  max-width: min(280px, calc(100vw - 2rem));
  margin-left: var(--tip-shift, 0px);
  padding: .5rem .75rem;
  background: #1e293b;
  color: #f1f5f9;
  font-size: 12.5px;
  font-weight: 400;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, .25);
  opacity: 0;
  visibility: hidden;
  transition: opacity var(--duration-fast) var(--easing-out), transform var(--duration-fast) var(--easing-out);
  pointer-events: none;
  z-index: 40;
}
.tooltip-lead { display: block; font-weight: 600; }
.tooltip-bubble ul { margin: .35rem 0 0; padding-left: 1.05rem; list-style: disc; }
.tooltip-bubble li { margin: .15rem 0; }
.tooltip-bubble > ul:first-child { margin-top: 0; }
.tooltip-bubble::after {
  content: "";
  position: absolute;
  top: 100%;
  left: clamp(12px, calc(var(--tip-arrow-base, 50%) - var(--tip-shift, 0px)), calc(100% - 12px));
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1e293b;
}
.tooltip-host:hover .tooltip-bubble,
.tooltip-host:focus-visible .tooltip-bubble { opacity: 1; visibility: visible; transform: translateX(-50%) translateY(0); }
.tooltip-bubble--below { bottom: auto; top: calc(100% + 10px); }
.tooltip-bubble--below::after { top: auto; bottom: 100%; border-top-color: transparent; border-bottom-color: #1e293b; }
.tooltip-bubble--align-start { --tip-arrow-base: 14px; left: 0; transform: translateY(4px); }
.tooltip-host:hover .tooltip-bubble--align-start,
.tooltip-host:focus-visible .tooltip-bubble--align-start { transform: translateY(0); }

/* ━━━ 반응형 ━━━ */
@media (max-width: 1024px) {
  .participation-map {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  body { padding: 16px 12px 40px; }
  section, .release-train { padding: 14px 16px; border-radius: 14px; }
  .kpi { min-width: 120px; padding: 12px 14px; border-radius: 14px; }
  .kpi .n { font-size: 22px; }
  .feature-summary { grid-template-columns: 1fr; gap: 6px; }
  /* 한 열로 접히면 열 고정을 풀어야 한다 — 없는 열(2~4)을 참조하면
     암묵적 열이 생겨 4열 구조가 그대로 남는다.
     셀렉터를 위 고정 규칙과 같은 형태로 반복하는 이유: 미디어쿼리는 특이도를
     올려주지 않아서, `> *` 한 줄로는 클래스 두 개짜리 고정 규칙에 진다. */
  .feature-summary > .group-ai-title,
  .feature-summary > .group-name,
  .feature-summary > .stage-badge-wrap,
  .feature-summary > .sparkline-wrap,
  .feature-summary > .sparkline-empty,
  .feature-summary > .feature-meta {
    grid-column: auto;
  }
  .sparkline-empty { display: none; }
  .feature-meta { text-align: left; flex-direction: row; gap: 10px; }
  .line-summary { grid-template-columns: 1fr; gap: 4px; }
  .line-latest { white-space: normal; }
  /* 한 열로 접히면 제목이 화면 폭을 다 쓰므로 자르지 않고 줄바꿈한다 — 이때는 행이
     이미 여러 줄이라 높이를 맞출 필요가 없고, 자르면 짧은 화면에서 제목만 손실된다. */
  .line-head > .group-ai-title,
  .line-head > .line-name {
    overflow: visible;
    white-space: normal;
  }
  .participation-map {
    grid-template-columns: 1fr;
  }
}
"""
