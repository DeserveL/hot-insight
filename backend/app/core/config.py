from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from backend.app.core.timezone import DEFAULT_TIME_ZONE, get_app_zoneinfo


DEFAULT_TRACK_TAGS = ("爆", "沸", "热")
DEFAULT_ALERT_TAGS = ("爆", "沸")
DEFAULT_TAG_RECURRENCE_HOURS = {"爆": 12, "沸": 12, "热": 24}
DEFAULT_WEIBO_SOURCE_ORDER = ("weibo_official", "xk", "xunjinlu", "xxapi", "nsuuu")
DEFAULT_NOTIFICATION_COVER = Path("backend/app/assets/notification-covers/default-cover.png")


@dataclass(frozen=True)
class WeComConfig:
    corp_id: str = ""
    corp_secret: str = ""
    agent_id: str = ""
    to_user: str = "@all"
    origin: str = "https://qyapi.weixin.qq.com"
    health_alerts: bool = True
    health_webhook_url: str = ""
    health_webhook_timeout_seconds: int = 10
    message_type: str = "mpnews"
    mpnews_author: str = "热点洞察"
    default_cover: Path = DEFAULT_NOTIFICATION_COVER
    default_cover_media_id: str = ""
    default_cover_name: str = "hot.jpeg"

    @property
    def enabled(self) -> bool:
        return bool(self.corp_id and self.corp_secret and self.agent_id)


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    api_base_url: str = "https://api.telegram.org"
    parse_mode: str = "HTML"
    timeout_seconds: int = 15
    max_retries: int = 3

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass(frozen=True)
class AIDetailConfig:
    enabled: bool = True
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    api_mode: str = "responses"
    max_retries: int = 3
    timeout_seconds: int = 60
    temperature: float = 0.2
    web_search_options: dict[str, Any] | None = field(default_factory=dict)
    extra_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.model)


@dataclass(frozen=True)
class AppConfig:
    track_tags: tuple[str, ...] = DEFAULT_TRACK_TAGS
    alert_tags: tuple[str, ...] = DEFAULT_ALERT_TAGS
    tag_recurrence_hours: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TAG_RECURRENCE_HOURS))
    notify_channels: tuple[str, ...] = ("wecom", "telegram")
    public_site_url: str = ""
    max_topics_per_run: int = 10
    schedule_minutes: int = 30
    app_time_zone: str = DEFAULT_TIME_ZONE
    fetch_timeout_seconds: int = 15
    weibo_official_timeout_seconds: int = 15
    weibo_official_visitor_timeout_seconds: int = 15
    weibo_official_realtime_timeout_seconds: int = 15
    weibo_official_max_retries: int = 2
    weibo_source_order: tuple[str, ...] = DEFAULT_WEIBO_SOURCE_ORDER
    database_path: Path = Path("data/hot_insight.sqlite3")
    log_level: str = "INFO"
    log_file_enabled: bool = True
    log_file_path: Path = Path("data/logs/hot-insight.log")
    log_file_max_bytes: int = 10 * 1024 * 1024
    log_file_backup_count: int = 7
    health_alert_cooldown_minutes: int = 180
    wecom: WeComConfig = field(default_factory=WeComConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    ai_detail: AIDetailConfig = field(default_factory=AIDetailConfig)

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env") -> "AppConfig":
        if env_file:
            load_dotenv(env_file, override=False)

        return cls(
            track_tags=_split_csv(os.getenv("TRACK_TAGS"), DEFAULT_TRACK_TAGS),
            alert_tags=_split_csv(os.getenv("ALERT_TAGS"), DEFAULT_ALERT_TAGS),
            tag_recurrence_hours=_tag_recurrence_env(
                os.getenv("TAG_RECURRENCE_HOURS"),
                DEFAULT_TAG_RECURRENCE_HOURS,
            ),
            notify_channels=_split_csv(os.getenv("NOTIFY_CHANNELS"), ("wecom", "telegram")),
            public_site_url=os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/"),
            max_topics_per_run=_int_env("MAX_TOPICS_PER_RUN", 10),
            schedule_minutes=_int_env("SCHEDULE_MINUTES", 30),
            app_time_zone=_time_zone_env("APP_TIME_ZONE", DEFAULT_TIME_ZONE),
            fetch_timeout_seconds=_int_env("FETCH_TIMEOUT_SECONDS", 15),
            weibo_official_timeout_seconds=max(
                _int_env("WEIBO_OFFICIAL_TIMEOUT_SECONDS", _int_env("FETCH_TIMEOUT_SECONDS", 15)),
                1,
            ),
            weibo_official_visitor_timeout_seconds=max(
                _int_env(
                    "WEIBO_OFFICIAL_VISITOR_TIMEOUT_SECONDS",
                    _int_env("WEIBO_OFFICIAL_TIMEOUT_SECONDS", _int_env("FETCH_TIMEOUT_SECONDS", 15)),
                ),
                1,
            ),
            weibo_official_realtime_timeout_seconds=max(
                _int_env(
                    "WEIBO_OFFICIAL_REALTIME_TIMEOUT_SECONDS",
                    _int_env("WEIBO_OFFICIAL_TIMEOUT_SECONDS", _int_env("FETCH_TIMEOUT_SECONDS", 15)),
                ),
                1,
            ),
            weibo_official_max_retries=max(_int_env("WEIBO_OFFICIAL_MAX_RETRIES", 2), 1),
            weibo_source_order=_split_csv(os.getenv("WEIBO_SOURCE_ORDER"), DEFAULT_WEIBO_SOURCE_ORDER),
            database_path=Path(os.getenv("DATABASE_PATH", "data/hot_insight.sqlite3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_file_enabled=_bool_env("LOG_FILE_ENABLED", True),
            log_file_path=Path(os.getenv("LOG_FILE_PATH", "data/logs/hot-insight.log")),
            log_file_max_bytes=max(_int_env("LOG_FILE_MAX_BYTES", 10 * 1024 * 1024), 1),
            log_file_backup_count=max(_int_env("LOG_FILE_BACKUP_COUNT", 7), 0),
            health_alert_cooldown_minutes=_int_env("HEALTH_ALERT_COOLDOWN_MINUTES", 180),
            wecom=_load_wecom_config(),
            telegram=_load_telegram_config(),
            ai_detail=_load_ai_detail_config(),
        )


def _load_wecom_config() -> WeComConfig:
    return WeComConfig(
        corp_id=os.getenv("WECOM_CORP_ID", ""),
        corp_secret=os.getenv("WECOM_CORP_SECRET", ""),
        agent_id=os.getenv("WECOM_AGENT_ID", ""),
        to_user=os.getenv("WECOM_TO_USER", "@all"),
        origin=os.getenv("WECOM_ORIGIN", "https://qyapi.weixin.qq.com").rstrip("/"),
        health_alerts=_bool_env("WECOM_HEALTH_ALERTS", True),
        health_webhook_url=os.getenv("WECOM_HEALTH_WEBHOOK_URL", "").strip(),
        health_webhook_timeout_seconds=max(_int_env("WECOM_HEALTH_WEBHOOK_TIMEOUT_SECONDS", 10), 1),
        message_type=(os.getenv("WECOM_MESSAGE_TYPE") or "mpnews").strip().lower(),
        mpnews_author=os.getenv("WECOM_MPNEWS_AUTHOR", "热点洞察"),
        default_cover=Path(os.getenv("NOTIFICATION_DEFAULT_COVER", str(DEFAULT_NOTIFICATION_COVER))),
        default_cover_media_id=os.getenv("WECOM_DEFAULT_COVER_MEDIA_ID", "").strip(),
        default_cover_name=os.getenv("WECOM_DEFAULT_COVER_NAME", "hot.jpeg").strip(),
    )


def _load_telegram_config() -> TelegramConfig:
    return TelegramConfig(
        bot_token=os.getenv("TG_BOT_TOKEN", ""),
        chat_id=os.getenv("TG_CHAT_ID", ""),
        api_base_url=os.getenv("TG_API_BASE_URL", "https://api.telegram.org").rstrip("/"),
        parse_mode=os.getenv("TG_PARSE_MODE", "HTML").strip() or "HTML",
        timeout_seconds=max(_int_env("TG_TIMEOUT_SECONDS", 15), 1),
        max_retries=max(_int_env("TG_MAX_RETRIES", 3), 1),
    )


def _load_ai_detail_config() -> AIDetailConfig:
    return AIDetailConfig(
        enabled=_bool_env("AI_DETAIL_ENABLED", True),
        base_url=os.getenv("AI_DETAIL_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        api_key=os.getenv("AI_DETAIL_API_KEY", ""),
        model=os.getenv("AI_DETAIL_MODEL", ""),
        api_mode=os.getenv("AI_DETAIL_API_MODE", "responses").strip().lower(),
        max_retries=max(_int_env("AI_DETAIL_MAX_RETRIES", 3), 1),
        timeout_seconds=max(_int_env("AI_DETAIL_TIMEOUT_SECONDS", 60), 1),
        temperature=_float_env("AI_DETAIL_TEMPERATURE", 0.2),
        web_search_options=_json_env("AI_DETAIL_WEB_SEARCH_OPTIONS", {}),
        extra_payload=_json_env("AI_DETAIL_EXTRA_PAYLOAD_JSON", {}) or {},
    )


def _split_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _tag_recurrence_env(value: str | None, default: dict[str, int]) -> dict[str, int]:
    if value is None:
        return dict(default)
    value = value.strip()
    if not value:
        return {}
    result: dict[str, int] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"TAG_RECURRENCE_HOURS item must be TAG:HOURS, got {part!r}")
        tag, hours_text = part.split(":", 1)
        tag = tag.strip()
        hours_text = hours_text.strip()
        if not tag:
            raise ValueError(f"TAG_RECURRENCE_HOURS item must include tag, got {part!r}")
        try:
            hours = int(hours_text)
        except ValueError as exc:
            raise ValueError(f"TAG_RECURRENCE_HOURS hours must be an integer, got {part!r}") from exc
        if hours <= 0:
            raise ValueError(f"TAG_RECURRENCE_HOURS hours must be positive, got {part!r}")
        result[tag] = hours
    return result


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _time_zone_env(name: str, default: str) -> str:
    value = os.getenv(name) or os.getenv("TZ") or default
    value = value.strip() or default
    get_app_zoneinfo(value)
    return value


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float, got {value!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _json_env(name: str, default: dict[str, Any] | None) -> dict[str, Any] | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    if value == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON, got {value!r}") from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object or empty string")
    return parsed
