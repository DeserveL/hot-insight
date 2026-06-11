from __future__ import annotations

import argparse
import logging

from backend.app.core.config import AppConfig
from backend.app.core.logging import configure_logging
from backend.app.services.ingestion.service import run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="热点洞察站后端工具")
    parser.add_argument("command", choices=("run-once",), help="执行的命令")
    parser.add_argument("--env-file", default=".env", help="环境变量文件路径")
    args = parser.parse_args()

    config = AppConfig.from_env(args.env_file)
    configure_logging(
        config.log_level,
        file_enabled=config.log_file_enabled,
        file_path=config.log_file_path,
        file_max_bytes=config.log_file_max_bytes,
        file_backup_count=config.log_file_backup_count,
    )

    if args.command == "run-once":
        result = run_once(config)
        logging.info(
            (
                "单轮采集完成: source=%s source_fetched=%s tracked=%s ai_success=%s "
                "ai_failed=%s alert_eligible=%s pending_notifications=%s sent=%s health_alert=%s"
            ),
            result.fetched_source,
            result.source_fetched_count,
            result.tracked_count,
            result.ai_success_count,
            result.ai_failed_count,
            result.alert_eligible_count,
            result.pending_notification_count,
            result.sent_count,
            result.health_alert_sent,
        )


if __name__ == "__main__":
    main()
