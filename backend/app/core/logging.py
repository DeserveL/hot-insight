from __future__ import annotations

import contextvars
import logging
import re
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator

from backend.app.core.timezone import DEFAULT_TIME_ZONE, get_app_zoneinfo


DEFAULT_LOG_FILE_PATH = Path("data/logs/hot-insight.log")
DEFAULT_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_FILE_BACKUP_COUNT = 7

_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = get_run_id()
        return True


class TimeZoneFormatter(logging.Formatter):
    def __init__(self, fmt: str, *, time_zone: str = DEFAULT_TIME_ZONE) -> None:
        super().__init__(fmt)
        self.time_zone = get_app_zoneinfo(time_zone)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        created = datetime.fromtimestamp(record.created, self.time_zone)
        if datefmt:
            return created.strftime(datefmt)
        return f"{created:%Y-%m-%d %H:%M:%S},{int(record.msecs):03d}{created:%z}"


def configure_logging(
    level: str,
    *,
    file_enabled: bool = True,
    file_path: Path = DEFAULT_LOG_FILE_PATH,
    file_max_bytes: int = DEFAULT_LOG_FILE_MAX_BYTES,
    file_backup_count: int = DEFAULT_LOG_FILE_BACKUP_COUNT,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = TimeZoneFormatter(
        "%(asctime)s %(levelname)s [%(name)s] [run_id=%(run_id)s] %(message)s",
        time_zone=time_zone,
    )
    run_filter = RunIdFilter()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if file_enabled:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                file_path,
                maxBytes=max(file_max_bytes, 1),
                backupCount=max(file_backup_count, 0),
                encoding="utf-8",
            )
        )

    for handler in handlers:
        handler.setLevel(log_level)
        handler.setFormatter(formatter)
        handler.addFilter(run_filter)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(log_level)
    for handler in handlers:
        root_logger.addHandler(handler)


def get_run_id() -> str:
    return _run_id.get()


@contextmanager
def logging_run(run_id: str) -> Iterator[None]:
    token = _run_id.set(run_id or "-")
    try:
        yield
    finally:
        _run_id.reset(token)


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    replacements = [
        (r"(?i)(access_token=)[^&\s]+", r"\1***"),
        (r"(?i)(corpsecret=)[^&\s]+", r"\1***"),
        (r"(?i)([?&]key=)[^&\s]+", r"\1***"),
        (r"(?i)([?&](?:s|sp|sub|subp)=)[^&\s]+", r"\1***"),
        (r"(?i)(api[_-]?key[\"'\s:=]+)[^,\"'\s]+", r"\1***"),
        (r"(?i)(authorization[\"'\s:=]+bearer\s+)[^,\"'\s]+", r"\1***"),
        (r"/bot[^/\s]+/", "/bot***/"),
        (r"(?i)(cookie[\"'\s:=]+)[^,\"']+", r"\1***"),
        (r"(?i)(token[\"'\s:=]+)[^,\"'\s]+", r"\1***"),
        (r"(?i)(secret[\"'\s:=]+)[^,\"'\s]+", r"\1***"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def mask_external_target(provider: str, target: str) -> str:
    target = str(target or "")
    if not target:
        return "-"
    if target == "@all":
        return target
    if provider == "wecom" and target.startswith("@"):
        return target[:4] + "***" if len(target) > 4 else target
    if len(target) <= 8:
        return f"{target[:2]}***"
    return f"{target[:4]}***{target[-4:]}"
