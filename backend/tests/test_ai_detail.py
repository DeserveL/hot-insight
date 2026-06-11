import tempfile
import unittest
from pathlib import Path

import requests

from backend.app.core.config import AIDetailConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import TopicCandidate
from backend.app.services.ai.detail_client import (
    AIDetailClient,
    build_user_prompt,
    parse_chat_completion_detail,
    sanitize_ai_detail,
)


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
        self.posts: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AIDetailTests(unittest.TestCase):
    def test_chat_completions_request_includes_web_search_options(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(_config(web_search_options={}), session=session)

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["url"], "https://ai.example.com/v1/chat/completions")
        self.assertEqual(session.posts[0]["headers"]["Authorization"], "Bearer key")
        self.assertEqual(session.posts[0]["json"]["model"], "search-model")
        self.assertEqual(session.posts[0]["json"]["web_search_options"], {})
        self.assertIn("messages", session.posts[0]["json"])

    def test_web_search_options_can_be_disabled(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(_config(web_search_options=None), session=session)

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertNotIn("web_search_options", session.posts[0]["json"])

    def test_retries_until_max_attempts(self) -> None:
        session = FakeSession(
            [
                requests.Timeout("timeout"),
                ValueError("bad response"),
                requests.ConnectionError("down"),
            ]
        )
        client = AIDetailClient(_config(max_retries=3), session=session)

        result = client.generate(_topic())

        self.assertFalse(result.ok)
        self.assertEqual(len(session.posts), 3)
        self.assertIn("down", result.error_message)

    def test_parse_ai_json_from_fenced_content(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        '{"summary":"摘要","takeaway":"一句话结论","facts":["事实"],"commentary":"评价",'
                        '"risk_note":"风险","sources":[{"title":"源","url":"https://example.com"}],'
                        '"confidence":"high"}\n```'
                    }
                }
            ]
        }

        detail = parse_chat_completion_detail(payload)

        self.assertEqual(detail.summary, "摘要")
        self.assertEqual(detail.takeaway, "一句话结论")
        self.assertEqual(detail.facts, ["事实"])
        self.assertEqual(detail.commentary, "评价")
        self.assertEqual(detail.sources[0].url, "https://example.com")

    def test_user_prompt_can_include_official_context(self) -> None:
        prompt = build_user_prompt(_topic(), official_context="微博官方详情页内容")

        self.assertIn("official_context", prompt)
        self.assertIn("微博官方详情页内容", prompt)

    def test_extra_payload_merges_without_overriding_core_fields(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(
            _config(extra_payload={"metadata": {"search": True}, "model": "blocked"}),
            session=session,
        )

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["json"]["model"], "search-model")
        self.assertEqual(session.posts[0]["json"]["metadata"], {"search": True})

    def test_sanitize_risk_note_hides_technical_tooling_language(self) -> None:
        detail = parse_chat_completion_detail(
            _ai_payload(risk_note="当前环境未提供可用实时搜索工具，无法核验。")
        )

        sanitized = sanitize_ai_detail(detail)

        self.assertNotIn("搜索工具", sanitized.risk_note)
        self.assertIn("后续公开说明", sanitized.risk_note)

    def test_ai_insight_storage_success_and_failure_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic()
            failed_topic = _topic("失败热点")
            repository.save_topics([topic, failed_topic])
            detail = parse_chat_completion_detail(_ai_payload())

            repository.save_ai_insight_success(topic, detail, "model-a")
            success = repository.get_ai_insight_record(topic.id)
            repository.save_ai_insight_failure(failed_topic, "network down", "model-a")
            failure = repository.get_ai_insight_record(failed_topic.id)

            self.assertEqual(success["status"], "success")
            self.assertEqual(success["detail"].summary, "摘要")
            self.assertEqual(failure["status"], "failed")
            self.assertIn("network down", failure["error_message"])
            repository.close()


def _config(web_search_options={}, max_retries: int = 3, extra_payload: dict | None = None) -> AIDetailConfig:
    return AIDetailConfig(
        enabled=True,
        base_url="https://ai.example.com/v1",
        api_key="key",
        model="search-model",
        max_retries=max_retries,
        timeout_seconds=30,
        temperature=0.2,
        web_search_options=web_search_options,
        extra_payload=extra_payload or {},
    )


def _topic(title: str = "测试热搜") -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=100000,
        tag="爆",
        url="https://s.weibo.com/weibo?q=test",
        source_id="test",
        fetched_at="2026-06-09T18:00:00+08:00",
    )


def _ai_payload(risk_note: str = "风险") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"summary":"摘要","facts":["事实"],"commentary":"评价",'
                        '"takeaway":"一句话结论",'
                        f'"risk_note":"{risk_note}","sources":[{{"title":"源","url":"https://example.com"}}],'
                        '"confidence":"high"}'
                    )
                }
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
