"""HTML 대시보드 생성 + 파일 저장."""

import re
from datetime import date
from pathlib import Path

from pulse.models import DashboardModel, FeatureGroup
from pulse.renderer.escape import escape_html, escape_url
from pulse.renderer.sections import (
    group_ai_title_slot,
    group_analysis_slot,
    render_diff,
    render_feature_cards,
    render_header,
    render_kpi_strip,
    render_new_work,
    render_participation,
    render_release_lines,
    render_release_train,
    render_warnings_grouped,
)
from pulse.renderer.styles import CSS

# 헤더의 일간↔주간 전환 링크용 플레이스홀더 (write_report/write_weekly_report에서 치환)
PULSE_SWITCH_HREF_PLACEHOLDER = "__PULSE_SWITCH_HREF__"

# 확인 필요 표시(점) — 빈 요소라 스크린리더가 그냥 지나치므로 role="img"+aria-label로 의미를 준다
TAB_ACTIVITY_DOT_HTML = (
    '<span class="tab-dot" role="img" aria-label="확인 필요" title="조회 기간 내 변경 있음"></span>'
)


def ai_summary_slot(repo_full_path: str) -> str:
    """레포별 AI 요약 슬롯을 생성한다.

    Args:
        repo_full_path: 레포 full_path (예: "org/repo")

    Returns:
        레포별 마커 주석
    """
    return f"<!--PULSE_AI_SUMMARY_SLOT:{repo_full_path}-->"


def _make_css_safe_slug(repo_full_path: str, all_repos: tuple[str, ...]) -> str:
    """레포 full_path를 CSS-safe slug로 변환한다.

    '/'는 '__'로, [a-zA-Z0-9_-] 외 문자는 '-'로 치환한다.
    충돌 방지: 같은 base_slug를 가진 레포가 여러 개면 인덱스를 접미사로 부여한다.

    Args:
        repo_full_path: 레포 full_path (예: "org/repo")
        all_repos: 모든 레포 목록 (충돌 감지용)

    Returns:
        CSS-safe slug (예: "org__repo")
    """
    base_slug = repo_full_path.replace("/", "__")
    base_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", base_slug)

    conflicting_repos = []
    for repo in all_repos:
        candidate_slug = repo.replace("/", "__")
        candidate_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", candidate_slug)
        if candidate_slug == base_slug:
            conflicting_repos.append(repo)

    if len(conflicting_repos) <= 1:
        return base_slug

    conflicting_repos.sort()
    try:
        index = conflicting_repos.index(repo_full_path)
        return f"{base_slug}_{index}"
    except ValueError:
        return base_slug


def _render_tab_radio_inputs(repos: tuple[str, ...]) -> str:
    """탭 라디오 인풋들을 렌더한다 (nav 밖, 같은 부모 레벨).

    전체 탭은 제거되었고 repo별 탭만 있다.
    첫 번째 repo 라디오에 HTML checked 속성을 붙인다.
    """
    if len(repos) <= 1:
        return ""

    inputs = []
    for i, repo in enumerate(repos):
        slug = _make_css_safe_slug(repo, repos)
        checked_attr = " checked" if i == 0 else ""
        html_input = (
            f'<input type="radio" id="tab-radio-{slug}" '
            f'name="tabs" class="tab-radio"{checked_attr}>'
        )
        inputs.append(html_input)

    return "\n".join(inputs)


def has_period_activity(groups: tuple[FeatureGroup, ...], repo_full_path: str) -> bool:
    """조회 기간 내 그 레포에 확인할 변경이 있었는지 판정한다 (순수 함수).

    기준은 커밋·MR 유무 — KPI 스트립의 '커밋'·'MR'과 같은 값을 보므로 탭의 표시와
    탭을 열어 보는 숫자가 어긋나지 않는다. 주의 신호(오래된 브랜치, 리뷰 대기 MR)는
    기간과 무관하게 매일 반복되는 상시 상태라 판정에서 제외한다 — 포함하면 며칠째
    변화 없는 레포에도 계속 표시가 붙어 표시 자체가 무의미해진다.

    Args:
        groups: 모든 기능 그룹들
        repo_full_path: 판정할 레포 경로

    Returns:
        커밋 또는 MR이 하나라도 있으면 True
    """
    return any(
        group.repo_full_path == repo_full_path and (group.commits or group.merge_requests)
        for group in groups
    )


def _render_tab_navigation(
    repos: tuple[str, ...],
    display_names: dict[str, str],
    active_repos: frozenset[str],
) -> str:
    """탭 네비게이션 라벨들 (nav 안에 위치).

    전체 탭은 제거되었고 repo별 탭 라벨만 렌더한다.
    display_name을 라벨로 사용하고, active_repos에 든 레포에는 확인 필요 점을 붙인다.

    라벨 텍스트를 span으로 감싸는 이유: 이름이 길어 말줄임될 때 점까지 잘려나가면
    안 되므로 말줄임 대상은 이름 span으로 한정한다.
    """
    if len(repos) <= 1:
        return ""

    labels = []
    for repo in repos:
        slug = _make_css_safe_slug(repo, repos)
        display_name = display_names.get(repo, repo)
        safe_label = escape_html(display_name)
        dot = TAB_ACTIVITY_DOT_HTML if repo in active_repos else ""
        labels.append(
            f'<label for="tab-radio-{slug}" class="tab-label">'
            f'<span class="tab-name">{safe_label}</span>{dot}</label>'
        )

    labels_html = "\n".join(labels)
    return f"""<nav class="tab-navigation">
{labels_html}
</nav>"""


def _make_tab_css_rules(slug: str) -> list[str]:
    """탭 CSS 규칙 생성 (display + active label style).

    활성 탭을 밑줄 방식으로 (color + border-bottom-color 변경).
    """
    rules = []
    rules.append(f"#tab-radio-{slug}:checked ~ #tab-content-{slug} {{ display: block; }}")
    label_rule = f'#tab-radio-{slug}:checked ~ .tab-navigation label[for="tab-radio-{slug}"]'
    rules.append(f"{label_rule} {{ color: var(--accent); border-bottom-color: var(--accent); }}")
    return rules


def _build_repo_tab_content(model: DashboardModel, repo: str) -> str:
    """레포 탭의 콘텐츠를 생성한다 (레포 헤더 + KPI 스트립 + AI 요약 슬롯 + 섹션들).

    wrapper div 없이 순수 콘텐츠만 반환한다.
    """
    # 레포 경로 링크에 쓸 web_url 찾기
    repo_summary_obj = next(
        (rs for rs in model.repo_summaries if rs.repo_full_path == repo),
        None,
    )

    # web_url이 있으면 항상 클릭 가능한 링크로 렌더
    repo_path_subtitle = ""
    if repo_summary_obj and repo_summary_obj.web_url:
        safe_url = escape_url(repo_summary_obj.web_url)
        safe_web_url_text = escape_html(repo_summary_obj.web_url)
        repo_path_subtitle = (
            f'\n  <div class="repo-path">'
            f'<a href="{safe_url}" target="_blank" rel="noopener">{safe_web_url_text}</a>'
            f"</div>"
        )

    # 레포 헤더 (부제만, summary-line 제거)
    repo_header = f"""<section class="repo-header">{repo_path_subtitle}
</section>"""

    # KPI 스트립
    kpi_strip = render_kpi_strip(model.groups, model.warnings, repo)

    # AI 요약 슬롯 (레포별)
    summary_slot = ai_summary_slot(repo)

    # 섹션들 (헤더 제외) — G4: period와 baseline_date 전달
    # 사다리 패널: repo별로 찾기 (있으면 라인 표 직전에 삽입)
    release_train = None
    for repo_path, train in model.repo_release_trains:
        if repo_path == repo:
            release_train = train
            break

    repo_sections = [
        render_feature_cards(
            model.groups,
            repo_filter=repo,
            generated_at=model.generated_at,
            issue_url_template=model.issue_url_template,
            period=model.period,
        ),
        render_release_train(release_train, model.generated_at),
        render_release_lines(
            model.groups,
            repo_filter=repo,
            generated_at=model.generated_at,
        ),
        render_new_work(
            model.new_work,
            repo_filter=repo,
            period=model.period,
            baseline_date=model.new_work_baseline_date,
        ),
        render_warnings_grouped(model.warnings, repo_filter=repo),
        render_participation(model.groups, repo_filter=repo),
        render_diff(model.diff, repo_filter=repo),
    ]

    sections_content = "\n\n".join(s for s in repo_sections if s)

    # 섹션들만 비면 empty-state 추가
    empty_state = '<p class="empty-state">조회 기간 내 활동이 없습니다.</p>'
    if not sections_content.strip():
        return repo_header + "\n\n" + kpi_strip + "\n\n" + summary_slot + "\n\n" + empty_state

    return repo_header + "\n\n" + kpi_strip + "\n\n" + summary_slot + "\n\n" + sections_content


def _build_repo_tab(model: DashboardModel, repo: str) -> tuple[str, list[str]]:
    """레포 탭 하나의 div + CSS 규칙을 생성한다 (다중 레포용).

    콘텐츠를 tab-content wrapper로 감싼다.
    """
    slug = _make_css_safe_slug(repo, model.repos)
    content = _build_repo_tab_content(model, repo)

    repo_div = f"""<div id="tab-content-{slug}" class="tab-content">
{content}
</div>"""
    css_rules = _make_tab_css_rules(slug)
    return repo_div, css_rules


def _assemble_sections_by_repo(model: DashboardModel) -> tuple[str, str]:
    """탭별 콘텐츠 조립 + 동적 CSS 생성.

    전체 탭은 제거되고 repo별 탭만 생성된다.
    """
    if len(model.repos) <= 1:
        # 단일 레포: 탭 없음, 콘텐츠만 직접 반환 (wrapper div 없음)
        single_repo = model.repos[0] if model.repos else "Unknown"
        content = _build_repo_tab_content(model, single_repo)
        return content, ""

    # 다중 레포: 레포별 탭만 생성 (wrapper div + CSS)
    tabs = []
    css_rules = []

    for repo in model.repos:
        repo_div, repo_css = _build_repo_tab(model, repo)
        tabs.append(repo_div)
        css_rules.extend(repo_css)

    tabs_html = "\n\n".join(tabs)
    dynamic_css = "\n".join(css_rules)
    return tabs_html, dynamic_css


def _assemble_sections(model: DashboardModel) -> tuple[str, str]:
    """모든 섹션을 조립한다 (헤더 포함)."""
    header_html = render_header(
        team_name=model.team_name,
        report_date=model.report_date.isoformat(),
        lookback_hours=model.lookback_hours,
        summary_line=model.summary_line,
        period=model.period,
        window_start=model.window_start,
        window_end=model.window_end,
    )

    sections_html, dynamic_css = _assemble_sections_by_repo(model)

    if len(model.repos) <= 1:
        return header_html + "\n\n" + sections_html, ""

    # display_name 매핑 생성
    display_names = {rs.repo_full_path: rs.display_name for rs in model.repo_summaries}

    active_repos = frozenset(r for r in model.repos if has_period_activity(model.groups, r))

    radio_inputs = _render_tab_radio_inputs(model.repos)
    nav_html = _render_tab_navigation(model.repos, display_names, active_repos)
    body_parts = [header_html, radio_inputs, nav_html, sections_html]
    body_content = "\n\n".join(body_parts)
    return body_content, dynamic_css


def _assemble_meta(model: DashboardModel) -> str:
    """메타 정보 푸터를 생성한다."""
    return f"""<footer class="meta">
  <p>미분류율(정보 부족): {model.unclassified_ratio * 100:.1f}%
     | 포함 그룹: {len(model.groups)}개
     | 포함 경고: {len(model.warnings)}개</p>
</footer>"""


def _render_tab_state_script() -> str:
    """일간↔주간 전환 시 탭 상태를 유지하는 인라인 JavaScript를 반환한다 (순수 함수).

    URL 해시는 '#' 구분 다중 세그먼트를 허용한다 (예: #team#repo=slug) —
    repo= 세그먼트로 활성 탭을 복원하고, team 세그먼트는 참여 토글이 소비한다.
    """
    return """<script>
(function() {
  // 현재 선택된 탭(레포)의 slug를 반환한다.
  function currentTabSlug() {
    var radios = document.querySelectorAll("input.tab-radio");
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) return radios[i].id.replace("tab-radio-", "");
    }
    return null;
  }

  // 해시를 '#' 구분 세그먼트 배열로 파싱한다 (예: "#team#repo=x" -> ["team", "repo=x"])
  function hashSegments() {
    return window.location.hash.split("#").filter(Boolean);
  }

  // 로드 시: repo= 세그먼트로 활성 탭 복원 (위치 무관 — #team과 공존 가능)
  var segments = hashSegments();
  for (var s = 0; s < segments.length; s++) {
    if (segments[s].indexOf("repo=") === 0) {
      var slug = decodeURIComponent(segments[s].substring(5));
      var radio = document.getElementById("tab-radio-" + slug);
      if (radio) radio.checked = true;
    }
  }

  // 일간↔주간 전환 링크 클릭 시 현재 활성 탭 slug를 대상 href에 부착한다.
  // 참여 섹션(team)이 켜져 있으면 그 상태도 함께 넘긴다.
  var switches = document.querySelectorAll("a.period-switch");
  for (var j = 0; j < switches.length; j++) {
    switches[j].addEventListener("click", function() {
      var slug = currentTabSlug();
      if (!slug) return;
      var base = this.getAttribute("href").split("#")[0];
      var team = hashSegments().indexOf("team") !== -1 ? "#team" : "";
      this.setAttribute("href", base + team + "#repo=" + encodeURIComponent(slug));
    });
  }
})();
</script>"""


def _render_participation_toggle_script() -> str:
    """팀 참여 섹션의 #team 해시 토글 JavaScript를 반환한다 (순수 함수).

    해시의 '#' 구분 세그먼트 중 team이 있으면 body.show-participation 클래스를
    추가해 참여 섹션을 표시한다 — #team 단독은 물론 #team#repo=slug처럼
    탭 상태 해시와 조합돼도 동작한다. hashchange 이벤트로 URL 변경 시 즉시 반영.
    """
    return """<script>
(function () {
  function syncParticipation() {
    var segments = window.location.hash.split('#').filter(Boolean);
    document.body.classList.toggle('show-participation', segments.indexOf('team') !== -1);
  }
  window.addEventListener('hashchange', syncParticipation);
  syncParticipation();
})();
</script>"""


def _render_tooltip_edge_script() -> str:
    """말풍선이 뷰포트 좌우로 잘리지 않게 밀어 넣는 인라인 JavaScript를 반환한다 (순수 함수).

    말풍선은 트리거 기준 가운데 정렬이라 페이지 가장자리의 트리거에서는 절반이 화면
    밖으로 나간다. 어느 요소가 가장자리에 놓일지는 화면 폭·번역된 문안 길이에 따라
    달라져 CSS만으로는 정할 수 없으므로, 열리는 순간 실측해 --tip-shift로 보정한다.
    스크립트가 실행되지 않아도 --tip-shift는 0으로 취급돼 기존 배치가 유지된다.
    """
    return """<script>
(function () {
  var EDGE_MARGIN = 8;

  function place(host) {
    var bubble = host.querySelector(".tooltip-bubble");
    if (!bubble) return;
    // 이전 보정을 지운 뒤 재측정해야 창 크기가 바뀌어도 누적되지 않는다
    bubble.style.setProperty("--tip-shift", "0px");
    var rect = bubble.getBoundingClientRect();
    var shift = 0;
    if (rect.left < EDGE_MARGIN) {
      shift = EDGE_MARGIN - rect.left;
    } else if (rect.right > window.innerWidth - EDGE_MARGIN) {
      shift = window.innerWidth - EDGE_MARGIN - rect.right;
    }
    if (shift) bubble.style.setProperty("--tip-shift", Math.round(shift) + "px");
  }

  function onEnter(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var host = target.closest(".tooltip-host");
    if (host) place(host);
  }

  document.addEventListener("mouseover", onEnter);
  document.addEventListener("focusin", onEnter);
})();
</script>"""


def _render_expand_animation_script() -> str:
    """확장 영역(.feature-expand)을 접고 펼칠 때 높이를 슬라이드하는 인라인 JavaScript.

    <details>는 open 속성이 바뀌는 순간 내용이 붙거나 떨어져 CSS만으로는 접기 쪽을
    애니메이션할 수 없다. 그래서 기본 토글을 막고 직접 높이를 재서 애니메이션한 뒤,
    닫는 애니메이션이 끝난 다음에 open을 내린다.

    두 가지를 함께 다룬다:
    - 세로 패딩도 같은 키프레임에서 0으로 — 높이만 줄이면 패딩(위아래 14px)이 남아
      0에서 시작하지 못하고 28px에서 툭 끊긴다.
    - overflow는 애니메이션 중에만 자른다 — 상시로 자르면 확장 영역 안에서 위로
      열리는 툴팁 말풍선이 이 상자의 윗변에서 잘린다(.line-row에서 겪은 문제).

    Element.animate가 없거나 사용자가 동작 최소화를 켰으면 아무것도 하지 않고
    브라우저 기본 즉시 토글에 맡긴다.
    """
    return """<script>
(function () {
  var DURATION_MS = 200;
  var EASING = 'cubic-bezier(0.25, 0.46, 0.45, 0.94)';

  var expands = document.querySelectorAll('details > .feature-expand');
  if (!expands.length || typeof Element.prototype.animate !== 'function') return;

  function prefersReducedMotion() {
    return !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function bind(expand) {
    var details = expand.parentElement;
    var summary = details.querySelector('summary');
    if (!summary) return;
    var running = null;
    var isClosing = false;

    // 인라인 값을 남기면 안 된다 — 특히 overflow를 남기면 안쪽 툴팁이 다시 잘린다.
    function clearInline() {
      expand.style.removeProperty('overflow');
      expand.style.removeProperty('height');
      expand.style.removeProperty('padding-top');
      expand.style.removeProperty('padding-bottom');
      expand.style.removeProperty('opacity');
    }

    function stop() {
      if (running) {
        running.cancel();
        running = null;
      }
      isClosing = false;
      clearInline();
    }

    function slide(opening) {
      var style = window.getComputedStyle(expand);
      var shown = {
        height: expand.scrollHeight + 'px',
        paddingTop: style.paddingTop,
        paddingBottom: style.paddingBottom,
        opacity: 1
      };
      var hidden = { height: '0px', paddingTop: '0px', paddingBottom: '0px', opacity: 0 };

      // 첫 프레임을 애니메이션이 잡기 전에 전체 높이가 한 번 그려지는 것을 막는다
      expand.style.overflow = 'hidden';
      if (opening) {
        expand.style.height = '0px';
        expand.style.paddingTop = '0px';
        expand.style.paddingBottom = '0px';
      }

      running = expand.animate(opening ? [hidden, shown] : [shown, hidden], {
        duration: DURATION_MS,
        easing: EASING
      });
      running.onfinish = function () {
        running = null;
        isClosing = false;
        if (!opening) details.open = false;
        clearInline();
      };
    }

    summary.addEventListener('click', function (event) {
      if (prefersReducedMotion()) return;
      // 요약 행에 링크가 생기면 기본 동작을 막아 이동이 죽는 것을 피한다
      if (event.target.closest && event.target.closest('a')) return;
      event.preventDefault();
      // 접히는 중에도 open은 아직 true라서 details.open만으로는 방향을 알 수 없다
      var opening = isClosing || !details.open;
      stop();
      isClosing = !opening;
      if (opening) details.open = true;
      slide(opening);
    });
  }

  for (var i = 0; i < expands.length; i++) bind(expands[i]);
})();
</script>"""


def render_html(model: DashboardModel) -> str:
    """DashboardModel을 단일 HTML 파일로 렌더링한다 (탭 지원, AI 요약 슬롯 레포별)."""
    sections_html, dynamic_css = _assemble_sections(model)
    meta_html = _assemble_meta(model)
    body_content = sections_html + "\n\n" + meta_html

    combined_css = CSS
    if dynamic_css:
        combined_css += "\n" + dynamic_css

    safe_title_team = escape_html(model.team_name)
    tab_state_script = _render_tab_state_script()
    participation_toggle_script = _render_participation_toggle_script()
    tooltip_edge_script = _render_tooltip_edge_script()
    expand_animation_script = _render_expand_animation_script()
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Pulse — {safe_title_team}</title>
  <style>
{combined_css}
  </style>
</head>
<body>
{body_content}
{tab_state_script}
{participation_toggle_script}
{tooltip_edge_script}
{expand_animation_script}
</body>
</html>"""

    return html


def write_report(
    html: str,
    output_dir: Path,
    report_date: date,
    write_latest: bool = True,
) -> tuple[Path, Path | None]:
    """일간 HTML을 파일로 저장 (pulse-YYYY-MM-DD.html + latest.html 복사본).

    헤더의 주간 전환 링크 플레이스홀더를 항상 latest-weekly.html로 통일한다.
    (비월요일 시에도 기존 주간 대시보드를 링크)

    Args:
        html: HTML 문자열
        output_dir: 출력 디렉토리
        report_date: 리포트 날짜
        write_latest: False면 pulse-{report_date}.html만 생성, latest.html 미생성

    Returns:
        (dated_path, latest_path) — write_latest=False면 latest_path는 None
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 주간 링크를 항상 latest-weekly.html로 통일
    html_with_link = html.replace(PULSE_SWITCH_HREF_PLACEHOLDER, "latest-weekly.html")

    dated_path = output_dir / f"pulse-{report_date.isoformat()}.html"
    dated_path.write_text(html_with_link, encoding="utf-8")

    latest_path: Path | None = None
    if write_latest:
        latest_path = output_dir / "latest.html"
        latest_path.write_text(html_with_link, encoding="utf-8")

    return dated_path, latest_path


def write_weekly_report(
    html: str,
    output_dir: Path,
    report_date: date,
    write_latest: bool = True,
) -> tuple[Path, Path | None]:
    """주간 HTML을 파일로 저장 (pulse-weekly-YYYY-MM-DD.html + latest-weekly.html).

    헤더의 일간 전환 링크 플레이스홀더를 실제 파일명으로 치환한다.
    - dated 파일: pulse-YYYY-MM-DD.html 링크
    - latest 파일: latest.html 링크

    Args:
        html: HTML 문자열
        output_dir: 출력 디렉토리
        report_date: 리포트 날짜
        write_latest: False면 pulse-weekly-{report_date}.html만 생성, latest-weekly.html 미생성

    Returns:
        (dated_path, latest_path) — write_latest=False면 latest_path는 None
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dated_filename = f"pulse-{report_date.isoformat()}.html"
    dated_html = html.replace(PULSE_SWITCH_HREF_PLACEHOLDER, dated_filename)
    dated_path = output_dir / f"pulse-weekly-{report_date.isoformat()}.html"
    dated_path.write_text(dated_html, encoding="utf-8")

    latest_path: Path | None = None
    if write_latest:
        latest_html = html.replace(PULSE_SWITCH_HREF_PLACEHOLDER, "latest.html")
        latest_path = output_dir / "latest-weekly.html"
        latest_path.write_text(latest_html, encoding="utf-8")

    return dated_path, latest_path


def inject_ai_summary(html: str, repo_full_path: str, summary: str, period: str = "daily") -> str:
    """저장된 HTML의 특정 레포 요약 슬롯을 요약 섹션으로 치환한다 (순수 함수).

    Args:
        html: 슬롯을 포함한 HTML 문자열
        repo_full_path: 요약을 주입할 레포 full_path (예: "org/repo")
        summary: 요약 텍스트 (비면 슬롯을 빈 문자열로 제거)
        period: "daily" (기본) 또는 "weekly" — 요약 제목 동적화

    Returns:
        요약이 주입된 HTML 문자열
    """
    from pulse.renderer.sections import render_ai_summary

    slot = ai_summary_slot(repo_full_path)
    section = render_ai_summary(summary, period=period)
    return html.replace(slot, section)


def inject_group_ai_title(html: str, repo_full_path: str, group_name: str, title: str) -> str:
    """그룹 AI 제목 slot을 치환한다.

    Args:
        html: 슬롯을 포함한 HTML 문자열
        repo_full_path: 레포 full_path
        group_name: 그룹명
        title: AI 제목 (비면 슬롯을 빈 문자열로 제거)

    Returns:
        제목이 주입된 HTML 문자열
    """
    from pulse.renderer.sections import render_group_ai_title

    slot = group_ai_title_slot(repo_full_path, group_name)
    section = render_group_ai_title(title)
    return html.replace(slot, section)


def inject_group_analysis(html: str, repo_full_path: str, group_name: str, analysis: str) -> str:
    """그룹 분석 slot을 치환한다.

    Args:
        html: 슬롯을 포함한 HTML 문자열
        repo_full_path: 레포 full_path
        group_name: 그룹명
        analysis: AI 분석 텍스트 (비면 슬롯을 빈 문자열로 제거)

    Returns:
        분석이 주입된 HTML 문자열
    """
    from pulse.renderer.sections import render_group_analysis

    slot = group_analysis_slot(repo_full_path, group_name)
    section = render_group_analysis(analysis)
    return html.replace(slot, section)
