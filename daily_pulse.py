"""Daily Pulse 진입점: 수집 → 그룹핑 → 대시보드 생성 파이프라인."""

import argparse
import logging
import sys
from pathlib import Path

from pulse.collector import CollectionError, missing_tokens
from pulse.config import Config, ConfigError, load_config
from pulse.pipeline import AllReposFailedError, run_pipeline
from pulse.renderer import render_html, write_report, write_weekly_report
from pulse.secrets import missing_token_hint

EXIT_CONFIG_ERROR = 2
EXIT_PIPELINE_ERROR = 1


def _run_and_report(config: Config) -> int:
    """파이프라인을 실행하고 리포트를 저장한다. 예외별 exit code 분기."""
    try:
        daily_dashboard, weekly_dashboard = run_pipeline(config)

        # 일간 리포트
        daily_html = render_html(daily_dashboard)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        daily_dated, daily_latest = write_report(
            daily_html, config.output_dir, daily_dashboard.report_date
        )
        logging.info("일간 리포트 저장: %s, %s", daily_dated, daily_latest)

        # 주간 리포트
        weekly_html = render_html(weekly_dashboard)
        weekly_dated, weekly_latest = write_weekly_report(
            weekly_html, config.output_dir, weekly_dashboard.report_date
        )
        logging.info("주간 리포트 저장: %s, %s", weekly_dated, weekly_latest)

        print(f"요약: {daily_dashboard.summary_line}")
        return 0
    except (CollectionError, AllReposFailedError) as error:
        logging.error("수집 오류: %s", error)
        return EXIT_PIPELINE_ERROR
    except Exception:
        logging.exception("파이프라인 오류:")
        return EXIT_PIPELINE_ERROR


def main() -> int:
    """CLI 인자를 파싱하고 파이프라인을 실행한다."""
    parser = argparse.ArgumentParser(description="Daily Pulse — 팀 활동 일일 브리핑")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        config = load_config(args.config)
    except ConfigError as error:
        logging.error("설정 오류: %s", error)
        return EXIT_CONFIG_ERROR

    missing = missing_tokens(config)
    if missing:
        logging.error("%s", missing_token_hint(missing))
        return EXIT_PIPELINE_ERROR

    return _run_and_report(config)


if __name__ == "__main__":
    sys.exit(main())
