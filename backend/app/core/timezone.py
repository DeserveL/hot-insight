from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIME_ZONE = "Asia/Shanghai"


def get_app_time_zone_name(value: str | None = None) -> str:
    return (value or os.getenv("APP_TIME_ZONE") or os.getenv("TZ") or DEFAULT_TIME_ZONE).strip() or DEFAULT_TIME_ZONE


def get_app_zoneinfo(value: str | None = None) -> ZoneInfo:
    name = get_app_time_zone_name(value)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"APP_TIME_ZONE must be a valid IANA time zone, got {name!r}") from exc


def now_in_app_timezone(value: str | None = None) -> datetime:
    return datetime.now(get_app_zoneinfo(value))


def now_iso(value: str | None = None) -> str:
    return now_in_app_timezone(value).isoformat(timespec="seconds")
