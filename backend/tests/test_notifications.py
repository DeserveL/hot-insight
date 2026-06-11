import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import AIDetailConfig, AppConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import TopicCandidate
from backend.app.services.ingestion.service import run_once
from backend.app.services.notifications.router import DeliveryResult, NotificationRouter


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


class FakeProvider:
    def __init__(self, provider: str, target: str, results: list[bool]) -> None:
        self.provider = provider
        self._target = target
        self.results = results
        self.calls: list[TopicCandidate] = []

    @property
    def enabled(self) -> bool:
        return True

    @property
    def target(self) -> str:
        return self._target

    def send_topic(self, topic, alert_tags, ai_detail=None, ai_error="", detail_url="") -> DeliveryResult:
        self.calls.append(topic)
        ok = self.results.pop(0)
        return DeliveryResult(self.provider, self.target, ok, "" if ok else "failed", f"{self.provider}-msg")


class FakeAIDetailClient:
    def generate(self, topic: TopicCandidate):
        return type("Result", (), {"ok": False, "detail": None, "error_message": "AI 失败"})()


class NotificationRouterTests(unittest.TestCase):
    def test_targets_are_deduped_independently_and_failed_target_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, alert_tags=("爆",), source_order=("xunjinlu",))
            repository = AppRepository(config.database_path)
            wecom = FakeProvider("wecom", "@all", [True])
            telegram = FakeProvider("telegram", "@channel", [False, True])
            router = NotificationRouter([wecom, telegram], "https://site.test")

            result = run_once(
                config,
                session=_source_session("爆点新闻", "爆"),
                repository=repository,
                notifier=router,
                ai_client=FakeAIDetailClient(),
            )
            repeat = run_once(
                config,
                session=_source_session("爆点新闻", "爆"),
                repository=repository,
                notifier=router,
                ai_client=FakeAIDetailClient(),
            )

            self.assertEqual(result.sent_count, 1)
            self.assertEqual(repeat.sent_count, 1)
            self.assertEqual(len(wecom.calls), 1)
            self.assertEqual(len(telegram.calls), 2)
            targets = [target.as_tuple() for target in router.delivery_targets()]
            saved_topic = repository.list_topics(limit=1)["items"][0]
            self.assertEqual(
                repository.pending_delivery_targets(
                    _topic("爆点新闻", "爆", topic_id=saved_topic["id"]),
                    targets,
                ),
                [],
            )
            repository.close()

    def test_router_respects_alert_tags_before_generating_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, alert_tags=("爆", "沸"), source_order=("xunjinlu",))
            repository = AppRepository(config.database_path)
            telegram = FakeProvider("telegram", "@channel", [True])
            router = NotificationRouter([telegram], "https://site.test")

            result = run_once(
                config,
                session=_source_session("热榜新闻", "热"),
                repository=repository,
                notifier=router,
                ai_client=FakeAIDetailClient(),
            )

            self.assertEqual(result.sent_count, 0)
            self.assertEqual(telegram.calls, [])
            repository.close()


def _config(temp_dir: str, *, alert_tags: tuple[str, ...], source_order: tuple[str, ...]) -> AppConfig:
    return AppConfig(
        alert_tags=alert_tags,
        weibo_source_order=source_order,
        database_path=Path(temp_dir) / "hot_insight.sqlite3",
        ai_detail=AIDetailConfig(enabled=False),
    )


def _source_session(title: str, tag: str) -> FakeSession:
    return FakeSession(
        [
            FakeResponse(
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
        ]
    )


def _topic(title: str, tag: str, topic_id: str = "") -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=100,
        tag=tag,
        url="https://s.weibo.com/weibo?q=test",
        source_id="xunjinlu",
        fetched_at="2026-06-09T18:00:00+08:00",
        topic_id=topic_id,
    )


if __name__ == "__main__":
    unittest.main()
