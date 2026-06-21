import tempfile
import unittest
from pathlib import Path

import requests

from backend.app.core.config import AIDetailConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import TopicCandidate
from backend.app.services.ai.detail_client import (
    AIDetailClient,
    build_context_hash,
    build_user_prompt,
    parse_responses_detail,
    parse_chat_completion_detail,
    sanitize_ai_detail,
)
from backend.app.services.ai.context_change import (
    ContextChangeThresholds,
    build_context_material_snapshot,
    evaluate_context_material_change,
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
    def test_responses_request_disables_web_search_by_default(self) -> None:
        session = FakeSession([FakeResponse(_responses_payload())])
        client = AIDetailClient(_config(api_mode="responses"), session=session)

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["url"], "https://ai.example.com/v1/responses")
        self.assertEqual(session.posts[0]["headers"]["Authorization"], "Bearer key")
        self.assertEqual(session.posts[0]["json"]["model"], "search-model")
        self.assertNotIn("tools", session.posts[0]["json"])
        self.assertNotIn("tool_choice", session.posts[0]["json"])
        self.assertNotIn("include", session.posts[0]["json"])
        self.assertIn("input", session.posts[0]["json"])
        self.assertEqual(result.search_call_count, 1)
        self.assertEqual(result.search_source_count, 1)
        self.assertEqual(result.detail.confidence, "medium")

    def test_responses_optional_search_sends_tools_without_tool_choice(self) -> None:
        session = FakeSession([FakeResponse(_responses_payload())])
        client = AIDetailClient(_config(api_mode="responses", external_search="optional"), session=session)

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["json"]["tools"], [{"type": "web_search"}])
        self.assertEqual(session.posts[0]["json"]["include"], ["web_search_call.action.sources"])
        self.assertNotIn("tool_choice", session.posts[0]["json"])

    def test_responses_required_search_keeps_required_tool_choice(self) -> None:
        session = FakeSession([FakeResponse(_responses_payload())])
        client = AIDetailClient(_config(api_mode="responses", external_search="required"), session=session)

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["json"]["tool_choice"], "required")

    def test_chat_completions_optional_search_includes_web_search_options(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(
            _config(api_mode="chat_completions", external_search="optional", web_search_options=None),
            session=session,
        )

        result = client.generate(_topic())

        self.assertTrue(result.ok)
        self.assertEqual(session.posts[0]["url"], "https://ai.example.com/v1/chat/completions")
        self.assertEqual(session.posts[0]["headers"]["Authorization"], "Bearer key")
        self.assertEqual(session.posts[0]["json"]["model"], "search-model")
        self.assertEqual(session.posts[0]["json"]["web_search_options"], {})
        self.assertIn("messages", session.posts[0]["json"])

    def test_web_search_options_can_be_disabled(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(_config(api_mode="chat_completions", web_search_options=None), session=session)

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
        client = AIDetailClient(_config(api_mode="chat_completions", max_retries=3), session=session)

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

    def test_parse_responses_json_and_search_sources(self) -> None:
        parsed = parse_responses_detail(_responses_payload())

        self.assertEqual(parsed.detail.summary, "摘要")
        self.assertEqual(parsed.search_call_count, 1)
        self.assertEqual(parsed.search_source_count, 1)
        self.assertEqual(parsed.json_source_count, 1)
        self.assertEqual([source.url for source in parsed.detail.sources], ["https://s.weibo.com/weibo?q=test", "https://news.example.com/a"])

    def test_user_prompt_can_include_official_context(self) -> None:
        prompt = build_user_prompt(_topic(), official_context="微博官方详情页内容")

        self.assertIn("official_context", prompt)
        self.assertIn("微博官方详情页内容", prompt)

    def test_context_hash_ignores_rank_url_and_mobile_content_jitter(self) -> None:
        topic = _topic().with_source_material(source_excerpt="移动摘要", source_excerpt_origin="mobile")
        changed = TopicCandidate(
            title=topic.title,
            rank=9,
            score=999999,
            tag="热",
            url="https://s.weibo.com/weibo?q=test&band_rank=9",
            source_id=topic.source_id,
            fetched_at=topic.fetched_at,
        ).with_source_material(source_excerpt="另一段移动摘要", source_excerpt_origin="mobile")

        self.assertEqual(
            build_context_hash(topic, "", has_mobile_context=True),
            build_context_hash(changed, "", has_mobile_context=True),
        )
        self.assertNotEqual(
            build_context_hash(topic, "", has_mobile_context=False),
            build_context_hash(topic, "", has_mobile_context=True),
        )
        self.assertNotEqual(
            build_context_hash(topic, "", has_mobile_context=True),
            build_context_hash(topic, "微博官方详情页内容", has_mobile_context=True),
        )

    def test_context_material_change_detects_official_context_becoming_available(self) -> None:
        previous = build_context_material_snapshot(official_context="", mobile_context="", has_mobile_context=False)
        current = build_context_material_snapshot(
            official_context="微博官方详情页新增了完整事件说明。",
            mobile_context="",
            has_mobile_context=False,
        )

        decision = evaluate_context_material_change(previous, current, ContextChangeThresholds())

        self.assertTrue(decision.significant)
        self.assertEqual(decision.reason, "official_became_available")

    def test_context_material_change_ignores_minor_punctuation_and_spacing_changes(self) -> None:
        previous = build_context_material_snapshot(
            official_context="苹果全面涨价，多个机型价格调整。 官方回应称以页面信息为准。",
            mobile_context="",
            has_mobile_context=False,
        )
        current = build_context_material_snapshot(
            official_context="苹果全面涨价, 多个机型价格调整。官方回应称以页面信息为准。 查看全文",
            mobile_context="",
            has_mobile_context=False,
        )

        decision = evaluate_context_material_change(previous, current, ContextChangeThresholds())

        self.assertFalse(decision.significant)
        self.assertIn(decision.reason, {"same_context_material", "minor_context_change"})

    def test_context_material_change_detects_meaningful_new_paragraph(self) -> None:
        previous = build_context_material_snapshot(
            official_context="某热点已有基本说明，相关讨论仍在发酵。",
            mobile_context="",
            has_mobile_context=False,
        )
        current = build_context_material_snapshot(
            official_context=(
                "某热点已有基本说明，相关讨论仍在发酵。"
                "随后官方补充关键进展，明确时间线、涉事主体和后续处理安排，"
                "这会显著改变对事件的梳理和风险提示。"
            ),
            mobile_context="",
            has_mobile_context=False,
        )

        decision = evaluate_context_material_change(previous, current, ContextChangeThresholds())

        self.assertTrue(decision.significant)
        self.assertIn(decision.reason, {"similarity_below_threshold", "length_delta_exceeded", "length_ratio_exceeded"})

    def test_unknown_source_excerpt_origin_is_treated_as_mobile_context(self) -> None:
        client = AIDetailClient(_config())
        topic = _topic(url="https://weibo.com/a/hot/abc_0.html?type=grab").with_source_material(
            source_excerpt="旧移动摘要",
        )

        context = client.prepare_context(topic)

        self.assertEqual(context.official_context, "")
        self.assertEqual(context.mobile_context, "旧移动摘要")
        self.assertEqual(context.combined_context, "旧移动摘要")

    def test_extra_payload_merges_without_overriding_core_fields(self) -> None:
        session = FakeSession([FakeResponse(_ai_payload())])
        client = AIDetailClient(
            _config(api_mode="chat_completions", extra_payload={"metadata": {"search": True}, "model": "blocked"}),
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

    def test_sanitize_risk_note_hides_internal_context_field_names(self) -> None:
        for term in ("mobile_context", "official_context", "realtime_posts", "weibo_context"):
            with self.subTest(term=term):
                detail = parse_chat_completion_detail(_ai_payload(risk_note=f"{term} 补充不足，仍需核验。"))

                sanitized = sanitize_ai_detail(detail)

                self.assertNotIn(term, sanitized.risk_note)
                self.assertIn("后续公开说明", sanitized.risk_note)

    def test_sanitize_risk_note_keeps_natural_mobile_discussion_wording(self) -> None:
        detail = parse_chat_completion_detail(_ai_payload(risk_note="微博移动端讨论材料不足，仍需以后续公开说明为准。"))

        sanitized = sanitize_ai_detail(detail)

        self.assertEqual(sanitized.risk_note, "微博移动端讨论材料不足，仍需以后续公开说明为准。")

    def test_ai_insight_storage_success_and_failure_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic()
            failed_topic = _topic("失败热点")
            repository.save_topics([topic, failed_topic])
            detail = parse_chat_completion_detail(_ai_payload())

            repository.save_ai_insight_success(
                topic,
                detail,
                "model-a",
                prompt_version="prompt-a",
                api_mode="responses",
                context_hash="hash-a",
                search_source_count=2,
            )
            success = repository.get_ai_insight_record(topic.id)
            repository.save_ai_insight_failure(
                failed_topic,
                "network down",
                "model-a",
                prompt_version="prompt-a",
                api_mode="responses",
                context_hash="hash-b",
            )
            failure = repository.get_ai_insight_record(failed_topic.id)

            self.assertEqual(success["status"], "success")
            self.assertEqual(success["detail"].summary, "摘要")
            self.assertEqual(success["prompt_version"], "prompt-a")
            self.assertEqual(success["api_mode"], "responses")
            self.assertEqual(success["context_hash"], "hash-a")
            self.assertEqual(success["search_source_count"], 2)
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["context_hash"], "hash-b")
            self.assertEqual(failure["failed_retry_context_hash"], "")
            self.assertIn("network down", failure["error_message"])
            repository.close()

    def test_ai_insight_storage_sanitizes_cached_internal_field_names_without_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic()
            repository.save_topics([topic])
            detail = parse_chat_completion_detail(_ai_payload(risk_note="mobile_context与实时帖子补充不足。"))

            repository.save_ai_insight_success(
                topic,
                detail,
                "model-a",
                prompt_version="prompt-a",
                api_mode="responses",
                context_hash="hash-a",
            )
            repository.conn.execute(
                "UPDATE ai_insights SET risk_note = ? WHERE topic_id = ?",
                ("mobile_context与实时帖子补充不足。", topic.id),
            )
            repository.conn.commit()
            record = repository.get_ai_insight_record(topic.id)

            self.assertEqual(record["status"], "success")
            self.assertNotIn("mobile_context", record["detail"].risk_note)
            self.assertIn("后续公开说明", record["detail"].risk_note)
            self.assertEqual(record["context_hash"], "hash-a")
            repository.close()


def _config(
    web_search_options=None,
    max_retries: int = 3,
    extra_payload: dict | None = None,
    api_mode: str = "chat_completions",
    external_search: str = "off",
) -> AIDetailConfig:
    return AIDetailConfig(
        enabled=True,
        base_url="https://ai.example.com/v1",
        api_key="key",
        model="search-model",
        api_mode=api_mode,
        max_retries=max_retries,
        timeout_seconds=30,
        temperature=0.2,
        external_search=external_search,
        web_search_options=web_search_options,
        extra_payload=extra_payload or {},
    )


def _topic(title: str = "测试热搜", url: str = "https://s.weibo.com/weibo?q=test") -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=100000,
        tag="爆",
        url=url,
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


def _responses_payload() -> dict:
    return {
        "output_text": (
            '{"summary":"摘要","facts":["事实"],"commentary":"评价","takeaway":"一句话结论",'
            '"risk_note":"风险","sources":[{"title":"微博搜索","url":"https://s.weibo.com/weibo?q=test"}],'
            '"confidence":"low"}'
        ),
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {"title": "媒体源", "url": "https://news.example.com/a"},
                    ]
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
