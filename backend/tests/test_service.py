import tempfile
import unittest
from pathlib import Path

import requests

from backend.app.core.config import AIDetailConfig, AppConfig, WeComConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, TopicCandidate
from backend.app.services.ai.detail_client import AIContext, build_context_hash
from backend.app.services.ai.prompts import PROMPT_VERSION
from backend.app.services.ingestion.service import _generate_ai_detail_if_missing, filter_alert_topics, filter_track_topics, run_once
from backend.app.services.notifications.router import DeliveryResult, DeliveryTarget


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[object], post_responses: list[object] | None = None) -> None:
        self.responses = responses
        self.post_responses = post_responses or []
        self.posts: list[dict] = []

    def get(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, json=None, timeout=None, **kwargs):
        self.posts.append({"url": url, "json": json, "timeout": timeout})
        response = self.post_responses.pop(0) if self.post_responses else FakeResponse({"errcode": 0, "errmsg": "ok"})
        if isinstance(response, Exception):
            raise response
        return response


class FakeNotifier:
    def __init__(self) -> None:
        self.sent_topics: list[TopicCandidate] = []
        self.health_messages: list[str] = []
        self.fail_titles: set[str] = set()
        self.targets = [DeliveryTarget("test", "target")]

    def delivery_targets(self) -> list[DeliveryTarget]:
        return self.targets

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail=None,
        ai_error: str = "",
        targets: list[tuple[str, str]] | None = None,
    ) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        selected = targets or [target.as_tuple() for target in self.targets]
        for provider, target in selected:
            ok = topic.title not in self.fail_titles
            if ok:
                self.sent_topics.append(topic)
            results.append(DeliveryResult(provider, target, ok, "" if ok else "failed", "msg-1" if ok else ""))
        return results


class FakeAIDetailClient:
    def __init__(self) -> None:
        self.calls: list[TopicCandidate] = []
        self.detail: AIDetail | None = None
        self.error_message = "fake ai disabled"

    def prepare_context(self, topic: TopicCandidate) -> AIContext:
        official_context = topic.source_excerpt
        return AIContext(official_context=official_context, context_hash=build_context_hash(topic, official_context))

    def generate(self, topic: TopicCandidate, context: AIContext | None = None):
        self.calls.append(topic)
        return type(
            "Result",
            (),
            {
                "ok": self.detail is not None,
                "detail": self.detail,
                "error_message": self.error_message,
                "context_hash": context.context_hash if context else build_context_hash(topic, topic.source_excerpt),
                "search_source_count": 0,
            },
        )()


class ServiceTests(unittest.TestCase):
    def test_filter_alert_topics_uses_configured_tags(self) -> None:
        topics = [
            _topic("爆点", "爆"),
            _topic("热搜", "热"),
            _topic("普通", ""),
            _topic("新内容", "新"),
        ]

        self.assertEqual([topic.title for topic in filter_alert_topics(topics, ("爆", "沸", "热"))], ["爆点", "热搜"])
        self.assertEqual([topic.title for topic in filter_alert_topics(topics, ("爆", "沸"))], ["爆点"])
        self.assertEqual([topic.title for topic in filter_track_topics(topics, ("爆", "沸", "热"))], ["爆点", "热搜"])

    def test_primary_failure_falls_back_to_tagged_source_and_dedupes_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, alert_tags=("爆", "沸", "热"), source_order=("xk", "xunjinlu"))
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            ai_client = FakeAIDetailClient()

            result = run_once(
                config,
                session=FakeSession([requests.ConnectionError("boom"), _xunjinlu_response("爆点新闻", "爆")]),
                repository=repository,
                notifier=notifier,
                ai_client=ai_client,
            )
            repeat = run_once(
                config,
                session=FakeSession([requests.ConnectionError("boom"), _xunjinlu_response("爆点新闻", "爆")]),
                repository=repository,
                notifier=notifier,
                ai_client=ai_client,
            )

            self.assertEqual(result.fetched_source, "xunjinlu")
            self.assertEqual(result.sent_count, 1)
            self.assertEqual(repeat.sent_count, 0)
            self.assertEqual([topic.title for topic in notifier.sent_topics], ["爆点新闻"])
            self.assertEqual(len(ai_client.calls), 1)
            repository.close()

    def test_each_topic_is_marked_only_after_successful_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, alert_tags=("爆", "沸", "热"), source_order=("xunjinlu",))
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            notifier.fail_titles = {"失败热点"}

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("成功热点", "爆", second=("失败热点", "沸"))]),
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            targets = [target.as_tuple() for target in notifier.delivery_targets()]
            saved_topics = {
                item["title"]: item["id"]
                for item in repository.list_topics(limit=10)["items"]
            }
            pending_success = repository.pending_delivery_targets(
                _topic("成功热点", "爆", topic_id=saved_topics["成功热点"]),
                targets,
            )
            pending_failure = repository.pending_delivery_targets(
                _topic("失败热点", "沸", topic_id=saved_topics["失败热点"]),
                targets,
            )

            self.assertEqual(result.sent_count, 1)
            self.assertEqual([topic.title for topic in notifier.sent_topics], ["成功热点"])
            self.assertEqual(pending_success, [])
            self.assertEqual(pending_failure, [("test", "target")])
            repository.close()

    def test_untagged_source_does_not_trigger_business_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                source_order=("nsuuu",),
                health_alert_cooldown_minutes=0,
                health_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            session = FakeSession([_untagged_response()])

            result = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertEqual(result.sent_count, 0)
            self.assertFalse(result.health_alert_sent)
            self.assertEqual(notifier.sent_topics, [])
            self.assertEqual(notifier.health_messages, [])
            self.assertEqual(session.posts, [])
            repository.close()

    def test_all_sources_failure_sends_wecom_robot_health_alert_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                source_order=("xunjinlu",),
                health_alert_cooldown_minutes=0,
                health_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            session = FakeSession([requests.ConnectionError("Temporary failure in name resolution")])

            result = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertTrue(result.health_alert_sent)
            self.assertEqual(notifier.sent_topics, [])
            self.assertEqual(notifier.health_messages, [])
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(session.posts[0]["json"]["msgtype"], "markdown")
            self.assertIn("热点洞察采集异常", session.posts[0]["json"]["markdown"]["content"])
            self.assertIn("DNS 解析失败", session.posts[0]["json"]["markdown"]["content"])
            repository.close()

    def test_all_sources_failure_without_webhook_only_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, source_order=("xunjinlu",), health_alert_cooldown_minutes=0)
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            session = FakeSession([requests.ConnectionError("Temporary failure in name resolution")])

            result = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertFalse(result.health_alert_sent)
            self.assertEqual(notifier.health_messages, [])
            self.assertEqual(session.posts, [])
            repository.close()

    def test_health_alert_respects_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                source_order=("xunjinlu",),
                health_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            session = FakeSession(
                [
                    requests.ConnectionError("Temporary failure in name resolution"),
                    requests.ConnectionError("Temporary failure in name resolution"),
                ]
            )

            first = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )
            second = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertTrue(first.health_alert_sent)
            self.assertFalse(second.health_alert_sent)
            self.assertEqual(len(session.posts), 1)
            repository.close()

    def test_health_alert_webhook_failure_does_not_block_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                source_order=("xunjinlu",),
                health_alert_cooldown_minutes=0,
                health_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            session = FakeSession(
                [requests.ConnectionError("Temporary failure in name resolution")],
                post_responses=[FakeResponse({"errcode": 93000, "errmsg": "invalid webhook"})],
            )

            result = run_once(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertFalse(result.health_alert_sent)
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(notifier.health_messages, [])
            repository.close()

    def test_health_alert_disabled_skips_wecom_robot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                source_order=("xunjinlu",),
                health_alert_cooldown_minutes=0,
                health_alerts=False,
                health_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
            )
            repository = AppRepository(config.database_path)
            session = FakeSession([requests.ConnectionError("Temporary failure in name resolution")])

            result = run_once(
                config,
                session=session,
                repository=repository,
                notifier=FakeNotifier(),
                ai_client=FakeAIDetailClient(),
            )

            self.assertFalse(result.health_alert_sent)
            self.assertEqual(session.posts, [])
            repository.close()

    def test_tracked_hot_topic_is_stored_but_not_pushed_when_alert_tags_exclude_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                alert_tags=("爆", "沸"),
                track_tags=("爆", "沸", "热"),
                source_order=("xunjinlu",),
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            ai_client = FakeAIDetailClient()

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("热榜新闻", "热")]),
                repository=repository,
                notifier=notifier,
                ai_client=ai_client,
            )

            topics = repository.list_topics(tag="热", limit=10)["items"]
            self.assertEqual(result.source_fetched_count, 1)
            self.assertEqual(result.tracked_count, 1)
            self.assertEqual(result.ai_failed_count, 1)
            self.assertEqual(result.alert_eligible_count, 0)
            self.assertEqual(result.sent_count, 0)
            self.assertEqual([topic["title"] for topic in topics], ["热榜新闻"])
            self.assertEqual([topic.title for topic in ai_client.calls], ["热榜新闻"])
            self.assertEqual(notifier.sent_topics, [])
            repository.close()

    def test_source_success_without_tracked_tags_does_not_send_health_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                alert_tags=("爆",),
                track_tags=("爆", "沸", "热"),
                source_order=("xunjinlu",),
                health_alert_cooldown_minutes=0,
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("新内容", "新")]),
                repository=repository,
                notifier=notifier,
                ai_client=FakeAIDetailClient(),
            )

            self.assertEqual(result.source_fetched_count, 1)
            self.assertEqual(result.tracked_count, 0)
            self.assertEqual(result.ai_failed_count, 0)
            self.assertEqual(result.sent_count, 0)
            self.assertEqual(notifier.health_messages, [])
            self.assertEqual(repository.list_topics(limit=10)["items"], [])
            repository.close()

    def test_empty_alert_tags_still_generates_ai_for_tracked_topics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                alert_tags=(),
                track_tags=("爆", "沸", "热"),
                source_order=("xunjinlu",),
            )
            repository = AppRepository(config.database_path)
            notifier = FakeNotifier()
            ai_client = FakeAIDetailClient()

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("展示热点", "热")]),
                repository=repository,
                notifier=notifier,
                ai_client=ai_client,
            )

            self.assertEqual(result.tracked_count, 1)
            self.assertEqual(result.ai_failed_count, 1)
            self.assertEqual(result.alert_eligible_count, 0)
            self.assertEqual(result.sent_count, 0)
            self.assertEqual([topic.title for topic in ai_client.calls], ["展示热点"])
            self.assertEqual(notifier.sent_topics, [])
            repository.close()

    def test_cached_ai_insight_is_reused_without_calling_ai_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                alert_tags=("爆",),
                source_order=("xunjinlu",),
                tag_recurrence_hours={"爆": 9999},
            )
            repository = AppRepository(config.database_path)
            topic = _topic("爆点新闻", "爆")
            repository.save_topics([topic])
            repository.save_ai_insight_success(
                topic,
                _detail(),
                "test-model",
                prompt_version=PROMPT_VERSION,
                api_mode="responses",
                context_hash=build_context_hash(topic, ""),
            )
            ai_client = FakeAIDetailClient()

            result = run_once(
                config,
                session=FakeSession([_xunjinlu_response("爆点新闻", "爆")]),
                repository=repository,
                notifier=FakeNotifier(),
                ai_client=ai_client,
            )

            self.assertEqual(result.sent_count, 1)
            self.assertEqual(ai_client.calls, [])
            repository.close()

    def test_cached_ai_insight_regenerates_when_source_excerpt_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                alert_tags=("爆",),
                source_order=("xunjinlu",),
                tag_recurrence_hours={"爆": 9999},
            )
            repository = AppRepository(config.database_path)
            topic = _topic("爆点新闻", "爆")
            repository.save_topics([topic])
            repository.save_ai_insight_success(
                topic,
                _detail(),
                "test-model",
                prompt_version=PROMPT_VERSION,
                api_mode="responses",
                context_hash=build_context_hash(topic, ""),
            )
            ai_client = FakeAIDetailClient()
            ai_client.detail = _detail()
            enriched_topic = topic.with_source_material(source_excerpt="微博官方详情补充内容")

            result = _generate_ai_detail_if_missing(config, repository, ai_client, enriched_topic)

            self.assertEqual(result, "success")
            self.assertEqual([topic.title for topic in ai_client.calls], ["爆点新闻"])
            record = repository.get_ai_insight_record(topic.id)
            self.assertEqual(record["context_hash"], build_context_hash(enriched_topic, enriched_topic.source_excerpt))
            repository.close()


def _config(
    temp_dir: str,
    *,
    alert_tags: tuple[str, ...] = ("爆", "沸", "热"),
    track_tags: tuple[str, ...] = ("爆", "沸", "热"),
    source_order: tuple[str, ...] = ("xunjinlu",),
    tag_recurrence_hours: dict[str, int] | None = None,
    health_alert_cooldown_minutes: int = 180,
    health_alerts: bool = True,
    health_webhook_url: str = "",
) -> AppConfig:
    return AppConfig(
        alert_tags=alert_tags,
        track_tags=track_tags,
        tag_recurrence_hours=tag_recurrence_hours or {"爆": 12, "沸": 12, "热": 24},
        weibo_source_order=source_order,
        database_path=Path(temp_dir) / "hot_insight.sqlite3",
        ai_detail=AIDetailConfig(enabled=True, model="test-model"),
        wecom=WeComConfig(health_alerts=health_alerts, health_webhook_url=health_webhook_url),
        health_alert_cooldown_minutes=health_alert_cooldown_minutes,
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


def _detail() -> AIDetail:
    return AIDetail(
        summary="摘要",
        takeaway="一句话结论",
        facts=["事实"],
        commentary="评价",
        risk_note="风险",
        sources=[],
        confidence="medium",
    )


def _xunjinlu_response(title: str, tag: str, second: tuple[str, str] | None = None) -> FakeResponse:
    entries = [
        {
            "rank": 0,
            "title": title,
            "hot" "_value": 900000,
            "label": tag,
            "url": "https://s.weibo.com/weibo?q=test",
        }
    ]
    if second is not None:
        entries.append(
            {
                "rank": 1,
                "title": second[0],
                "hot" "_value": 800000,
                "label": second[1],
                "url": "https://s.weibo.com/weibo?q=second",
            }
        )
    return FakeResponse({"code": 200, "data": {"list": entries}})


def _untagged_response() -> FakeResponse:
    return FakeResponse(
        {
            "code": 200,
            "data": [
                {
                    "index": 1,
                    "title": "普通热搜",
                    "hot": "190万",
                    "url": "https://s.weibo.com/weibo?q=normal",
                }
            ],
        }
    )


if __name__ == "__main__":
    unittest.main()
