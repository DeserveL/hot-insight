import io
import logging
import tempfile
import unittest
from pathlib import Path

import requests

from backend.app.core.config import AIDetailConfig, AppConfig
from backend.app.core.logging import configure_logging, logging_run, mask_external_target, redact_sensitive_text
from backend.app.core.timezone import now_iso
from backend.app.db.repositories import AppRepository
from backend.app.main import runtime_config_summary
from backend.app.services.ingestion.service import run_once
from backend.app.services.notifications.router import DeliveryResult, DeliveryTarget


class LoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_logging()

    def test_configure_logging_writes_console_and_file_with_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "hot-insight.log"
            configure_logging("INFO", file_enabled=True, file_path=log_path, file_max_bytes=4096, file_backup_count=1)

            logger = logging.getLogger("test.logging")
            with logging_run("run-test"):
                logger.info("hello logging")

            _flush_logging_handlers()
            text = log_path.read_text(encoding="utf-8")

            self.assertTrue(log_path.is_file())
            self.assertIn("run_id=run-test", text)
            self.assertIn("hello logging", text)
            self.assertIn("+0800", text)
            self.assertGreaterEqual(len(logging.getLogger().handlers), 2)
            _reset_logging()

    def test_now_iso_uses_app_time_zone(self) -> None:
        self.assertTrue(now_iso("Asia/Shanghai").endswith("+08:00"))

    def test_mask_external_target_hides_channel_ids(self) -> None:
        self.assertEqual(mask_external_target("wecom", "@all"), "@all")
        self.assertEqual(mask_external_target("telegram", "-1003920743813"), "-100***3813")

    def test_redact_sensitive_text_masks_credentials(self) -> None:
        text = redact_sensitive_text(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=secret-token "
            "https://api.telegram.org/bot123456:ABC/sendPhoto "
            "https://login.sina.com.cn/visitor/visitor?a=crossdomain&s=sub-value&sp=subp-value "
            "Authorization: Bearer ai-key Cookie: SUB=abc "
        )

        self.assertNotIn("secret-token", text)
        self.assertNotIn("123456:ABC", text)
        self.assertNotIn("ai-key", text)
        self.assertNotIn("SUB=abc", text)
        self.assertNotIn("sub-value", text)
        self.assertNotIn("subp-value", text)
        self.assertIn("access_token=***", text)
        self.assertIn("s=***", text)
        self.assertIn("sp=***", text)
        self.assertIn("/bot***/", text)

    def test_runtime_config_summary_excludes_secret_values(self) -> None:
        config = AppConfig(
            wecom=type(
                "WeCom",
                (),
                {
                    "enabled": True,
                    "corp_id": "corp",
                    "corp_secret": "secret",
                    "agent_id": "agent",
                    "to_user": "@all",
                },
            )(),
            telegram=type("Telegram", (), {"enabled": True, "bot_token": "token", "chat_id": "@channel"})(),
            ai_detail=AIDetailConfig(enabled=True, api_key="ai-key", model="model"),
        )

        summary_text = str(runtime_config_summary(config, scheduler_enabled=True))

        self.assertNotIn("secret", summary_text.lower())
        self.assertNotIn("token", summary_text.lower())
        self.assertNotIn("ai-key", summary_text)
        self.assertIn("ai_detail_available", summary_text)

    def test_run_once_logs_key_flow_with_same_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stream = io.StringIO()
            _configure_stream_logging(stream)
            config = AppConfig(
                alert_tags=("爆",),
                track_tags=("爆", "沸", "热"),
                weibo_source_order=("xunjinlu",),
                database_path=Path(temp_dir) / "hot_insight.sqlite3",
                ai_detail=AIDetailConfig(enabled=True, model="test-model"),
            )
            repository = AppRepository(config.database_path)

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("爆点新闻", "爆")]),
                repository=repository,
                notifier=FakeNotifier(),
                ai_client=FakeAIDetailClient(),
            )

            logs = stream.getvalue()
            run_ids = {
                part.split("]", 1)[0]
                for part in logs.split("[run_id=")[1:]
                if part.startswith("run-")
            }
            self.assertEqual(result.sent_count, 1)
            self.assertEqual(len(run_ids), 1)
            self.assertIn("采集运行开始", logs)
            self.assertIn("数据源尝试开始", logs)
            self.assertIn("热点入库完成", logs)
            self.assertIn("AI 洞察生成失败并已缓存", logs)
            self.assertIn("通知投递状态已记录", logs)
            self.assertIn("采集运行完成", logs)
            repository.close()


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def get(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeNotifier:
    def delivery_targets(self) -> list[DeliveryTarget]:
        return [DeliveryTarget("test", "target")]

    def send_topic(
        self,
        topic,
        alert_tags,
        ai_detail=None,
        ai_error: str = "",
        targets: list[tuple[str, str]] | None = None,
    ) -> list[DeliveryResult]:
        return [DeliveryResult("test", "target", True, "", "msg-1")]

    def send_health_alert(self, message: str) -> bool:
        return True


class FakeAIDetailClient:
    def generate(self, topic):
        return type("Result", (), {"ok": False, "detail": None, "error_message": "AI 失败"})()


def _xunjinlu_response(title: str, tag: str) -> FakeResponse:
    return FakeResponse(
        {
            "code": 200,
            "data": {
                "list": [
                    {
                        "rank": 0,
                        "title": title,
                        "hot" "_value": 900000,
                        "label": tag,
                        "url": "https://s.weibo.com/weibo?q=test",
                    }
                ]
            },
        }
    )


def _configure_stream_logging(stream: io.StringIO) -> None:
    _reset_logging()
    handler = logging.StreamHandler(stream)
    handler.addFilter(type("RunIdFilter", (logging.Filter,), {"filter": _add_run_id})())
    handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] [run_id=%(run_id)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


def _add_run_id(self, record: logging.LogRecord) -> bool:
    from backend.app.core.logging import get_run_id

    record.run_id = get_run_id()
    return True


def _flush_logging_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def _reset_logging() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    unittest.main()
