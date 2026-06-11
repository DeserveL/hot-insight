from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from backend.app.core.timezone import now_in_app_timezone
from backend.app.core.config import AppConfig
from backend.app.services.ingestion.service import run_once

logger = logging.getLogger(__name__)


async def scheduler_loop(config: AppConfig) -> None:
    interval_seconds = max(config.schedule_minutes, 1) * 60
    next_run_at = time.monotonic()
    while True:
        now_monotonic = time.monotonic()
        delay_seconds = next_run_at - now_monotonic
        if delay_seconds > 0:
            next_time = now_in_app_timezone(config.app_time_zone) + timedelta(seconds=delay_seconds)
            logger.info("后台采集调度等待下一轮: next_run_at=%s", next_time.isoformat(timespec="seconds"))
            await asyncio.sleep(delay_seconds)
        elif delay_seconds < -1:
            logger.warning("后台采集调度已延迟: delay_seconds=%.1f", abs(delay_seconds))
            next_run_at = now_monotonic

        run_started_at = time.monotonic()
        try:
            await asyncio.to_thread(run_once, config)
        except Exception:
            logger.exception("后台采集调度执行失败")

        next_run_at += interval_seconds
        now_after_run = time.monotonic()
        next_delay_seconds = max(next_run_at - now_after_run, 0)
        next_time = now_in_app_timezone(config.app_time_zone) + timedelta(seconds=next_delay_seconds)
        logger.info(
            "后台采集调度本轮结束: run_duration_seconds=%.1f next_run_at=%s",
            now_after_run - run_started_at,
            next_time.isoformat(timespec="seconds"),
        )
