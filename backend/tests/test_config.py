import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import AppConfig, DEFAULT_NOTIFICATION_COVER


class ConfigTests(unittest.TestCase):
    def test_default_alert_tags_and_database_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.track_tags, ("爆", "沸", "热"))
        self.assertEqual(config.alert_tags, ("爆", "沸"))
        self.assertEqual(config.tag_recurrence_hours, {"爆": 12, "沸": 12, "热": 24})
        self.assertEqual(config.database_path, Path("data/hot_insight.sqlite3"))
        self.assertEqual(config.weibo_source_order[0], "weibo_official")
        self.assertTrue(config.log_file_enabled)
        self.assertEqual(config.log_file_path, Path("data/logs/hot-insight.log"))
        self.assertEqual(config.log_file_max_bytes, 10 * 1024 * 1024)
        self.assertEqual(config.log_file_backup_count, 7)
        self.assertEqual(config.weibo_official_timeout_seconds, 15)
        self.assertEqual(config.weibo_official_visitor_timeout_seconds, 15)
        self.assertEqual(config.weibo_official_realtime_timeout_seconds, 15)
        self.assertEqual(config.weibo_official_max_retries, 2)

    def test_track_tags_are_configurable(self) -> None:
        with patch.dict(os.environ, {"TRACK_TAGS": "爆,热"}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.track_tags, ("爆", "热"))

    def test_alert_tags_are_configurable(self) -> None:
        with patch.dict(os.environ, {"ALERT_TAGS": "爆,沸"}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.alert_tags, ("爆", "沸"))

    def test_empty_alert_tags_disable_business_alerts(self) -> None:
        with patch.dict(os.environ, {"ALERT_TAGS": ""}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.alert_tags, ())

    def test_tag_recurrence_hours_are_configurable(self) -> None:
        with patch.dict(os.environ, {"TAG_RECURRENCE_HOURS": "爆:6,热:48"}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.tag_recurrence_hours, {"爆": 6, "热": 48})

    def test_invalid_tag_recurrence_hours_raise_clear_error(self) -> None:
        with patch.dict(os.environ, {"TAG_RECURRENCE_HOURS": "爆"}, clear=True):
            with self.assertRaisesRegex(ValueError, "TAG_RECURRENCE_HOURS"):
                AppConfig.from_env(env_file=None)

    def test_source_order_uses_weibo_specific_name(self) -> None:
        with patch.dict(os.environ, {"WEIBO_SOURCE_ORDER": "xunjinlu,xk"}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.weibo_source_order, ("xunjinlu", "xk"))

    def test_weibo_official_options_are_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FETCH_TIMEOUT_SECONDS": "12",
                "WEIBO_OFFICIAL_TIMEOUT_SECONDS": "5",
                "WEIBO_OFFICIAL_VISITOR_TIMEOUT_SECONDS": "4",
                "WEIBO_OFFICIAL_REALTIME_TIMEOUT_SECONDS": "3",
                "WEIBO_OFFICIAL_MAX_RETRIES": "4",
            },
            clear=True,
        ):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.fetch_timeout_seconds, 12)
        self.assertEqual(config.weibo_official_timeout_seconds, 5)
        self.assertEqual(config.weibo_official_visitor_timeout_seconds, 4)
        self.assertEqual(config.weibo_official_realtime_timeout_seconds, 3)
        self.assertEqual(config.weibo_official_max_retries, 4)

    def test_log_file_options_are_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOG_FILE_ENABLED": "false",
                "LOG_FILE_PATH": "data/logs/custom.log",
                "LOG_FILE_MAX_BYTES": "2048",
                "LOG_FILE_BACKUP_COUNT": "3",
            },
            clear=True,
        ):
            config = AppConfig.from_env(env_file=None)

        self.assertFalse(config.log_file_enabled)
        self.assertEqual(config.log_file_path, Path("data/logs/custom.log"))
        self.assertEqual(config.log_file_max_bytes, 2048)
        self.assertEqual(config.log_file_backup_count, 3)

    def test_wecom_mpnews_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.wecom.message_type, "mpnews")
        self.assertEqual(config.wecom.default_cover, DEFAULT_NOTIFICATION_COVER)
        self.assertEqual(config.wecom.default_cover_name, "hot.jpeg")

    def test_ai_detail_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertTrue(config.ai_detail.enabled)
        self.assertEqual(config.ai_detail.api_mode, "chat_completions")
        self.assertEqual(config.ai_detail.max_retries, 3)
        self.assertEqual(config.ai_detail.timeout_seconds, 60)
        self.assertEqual(config.ai_detail.temperature, 0.2)
        self.assertEqual(config.ai_detail.web_search_options, {})
        self.assertEqual(config.ai_detail.extra_payload, {})

    def test_ai_detail_extra_payload_is_configurable(self) -> None:
        with patch.dict(os.environ, {"AI_DETAIL_EXTRA_PAYLOAD_JSON": '{"metadata":{"search":true}}'}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.ai_detail.extra_payload, {"metadata": {"search": True}})

    def test_notification_and_telegram_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NOTIFY_CHANNELS": "telegram",
                "PUBLIC_SITE_URL": "https://example.com/",
                "TG_BOT_TOKEN": "token",
                "TG_CHAT_ID": "@channel",
            },
            clear=True,
        ):
            config = AppConfig.from_env(env_file=None)

        self.assertEqual(config.notify_channels, ("telegram",))
        self.assertEqual(config.public_site_url, "https://example.com")
        self.assertTrue(config.telegram.enabled)

    def test_ai_detail_web_search_options_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"AI_DETAIL_WEB_SEARCH_OPTIONS": ""}, clear=True):
            config = AppConfig.from_env(env_file=None)

        self.assertIsNone(config.ai_detail.web_search_options)


if __name__ == "__main__":
    unittest.main()
