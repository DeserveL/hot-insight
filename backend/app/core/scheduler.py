from __future__ import annotations

import asyncio
import logging

from backend.app.core.config import AppConfig
from backend.app.services.ingestion.service import run_once

logger = logging.getLogger(__name__)


async def scheduler_loop(config: AppConfig) -> None:
    while True:
        try:
            await asyncio.to_thread(run_once, config)
        except Exception:
            logger.exception("后台采集调度执行失败")
        await asyncio.sleep(max(config.schedule_minutes, 1) * 60)
