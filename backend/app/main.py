from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import channels, health, topics
from backend.app.core.config import AppConfig
from backend.app.core.logging import configure_logging
from backend.app.core.scheduler import scheduler_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = AppConfig.from_env(os.getenv("ENV_FILE", ".env"))
    configure_logging(
        config.log_level,
        file_enabled=config.log_file_enabled,
        file_path=config.log_file_path,
        file_max_bytes=config.log_file_max_bytes,
        file_backup_count=config.log_file_backup_count,
        time_zone=config.app_time_zone,
    )
    app.state.config = config
    scheduler_task = None
    scheduler_enabled = _bool_env("API_SCHEDULER_ENABLED", True)
    logger.info("FastAPI 启动配置: %s", runtime_config_summary(config, scheduler_enabled))
    if scheduler_enabled:
        scheduler_task = asyncio.create_task(scheduler_loop(config))
        logger.info("FastAPI 后台采集调度已启动，周期 %s 分钟", config.schedule_minutes)
    else:
        logger.info("FastAPI 后台采集调度未启用")
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                logger.info("FastAPI 后台采集调度已停止")


app = FastAPI(
    title="热点洞察站 API",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = [origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.include_router(health.router)
app.include_router(channels.router)
app.include_router(topics.router)


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "API 请求异常: method=%s path=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "API 请求完成: method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def runtime_config_summary(config: AppConfig, scheduler_enabled: bool) -> dict[str, object]:
    return {
        "database_path": str(config.database_path),
        "scheduler_enabled": scheduler_enabled,
        "schedule_minutes": config.schedule_minutes,
        "app_time_zone": config.app_time_zone,
        "source_order": list(config.weibo_source_order),
        "weibo_official_timeout_seconds": config.weibo_official_timeout_seconds,
        "weibo_official_visitor_timeout_seconds": config.weibo_official_visitor_timeout_seconds,
        "weibo_official_realtime_timeout_seconds": config.weibo_official_realtime_timeout_seconds,
        "weibo_official_max_retries": config.weibo_official_max_retries,
        "track_tags": list(config.track_tags),
        "alert_tags": list(config.alert_tags),
        "notify_channels": list(config.notify_channels),
        "wecom_enabled": config.wecom.enabled,
        "telegram_enabled": config.telegram.enabled,
        "ai_detail_enabled": config.ai_detail.enabled,
        "ai_detail_available": config.ai_detail.available,
        "ai_detail_api_mode": config.ai_detail.api_mode,
        "ai_detail_model_configured": bool(config.ai_detail.model),
        "log_file_enabled": config.log_file_enabled,
        "log_file_path": str(config.log_file_path),
    }
