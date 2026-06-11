from __future__ import annotations

import contextvars
import logging
import re
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator


DEFAULT_LOG_FILE_PATH = Path("data/logs/hot-insight.log")
DEFAULT_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_FILE_BACKUP_COUNT = 7

_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = get_run_id()
        return True


def configure_logging(
    level: str,
    *,
    file_enabled: bool = True,
    file_path: Path = DEFAULT_LOG_FILE_PATH,
    file_max_bytes: int = DEFAULT_LOG_FILE_MAX_BYTES,
    file_backup_count: int = DEFAULT_LOG_FILE_BACKUP_COUNT,
) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [run_id=%(run_id)s] %(message)s"
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
