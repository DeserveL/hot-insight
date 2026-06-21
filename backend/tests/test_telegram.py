import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import TelegramConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, TopicCandidate, weibo_mobile_search_url
from backend.app.services.notifications.telegram import (
    TelegramNotifier,
    build_reply_markup,
    file_cache_key,
    render_telegram_caption,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeTelegramSession:
    def __init__(self, responses: list[dict | FakeResponse]) -> None:
        self.responses = responses
        self.posts: list[dict] = []

    def post(self, url, json=None, data=None, files=None, timeout=None):
        self.posts.append({"url": url, "json": json, "data": data, "has_files": files is not None})
        response = self.responses.pop(0)
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)


class TelegramTests(unittest.TestCase):
    def test_caption_escapes_html_and_contains_summary_sections(self) -> None:
        caption = render_telegram_caption(
            _topic("<爆点>", "爆", source_id="weibo_official"),
            AIDetail(
                summary="摘要 <x>",
                takeaway="一句话 <x>",
                facts=["事实不应进入 TG"],
                commentary="评价不应进入 TG",
                risk_note="风险",
                sources=[],
                confidence="medium",
            ),
        )

        self.assertIn("💥【爆】&lt;爆点&gt;", caption)
        self.assertIn("微博官方热搜 · 排名 #1 · 热度 12.0万", caption)
        self.assertIn("一句话结论", caption)
        self.assertIn("一句话 &lt;x&gt;", caption)
        self.assertIn("热点梳理", caption)
        self.assertIn("摘要 &lt;x&gt;", caption)
        self.assertIn("风险提示", caption)
        self.assertIn("核验程度：中", caption)
        self.assertNotIn("AI 摘要", caption)
        self.assertNotIn("关键事实", caption)
        self.assertNotIn("事实不应进入 TG", caption)
        self.assertNotIn("AI 评价", caption)
        self.assertNotIn("评价不应进入 TG", caption)
        self.assertNotIn("参考来源", caption)
        self.assertNotIn("weibo_official", caption)

    def test_caption_contains_source_excerpt_when_available(self) -> None:
        caption = render_telegram_caption(_topic("爆点新闻", "爆", source_excerpt="微博实时材料内容。"))

        self.assertIn("微博实时材料", caption)
        self.assertIn("微博实时材料内容。", caption)

    def test_caption_truncates_long_summary_and_risk_but_keeps_sections(self) -> None:
        caption = render_telegram_caption(
            _topic("长文本热点", "热", source_id="weibo_official"),
            AIDetail(
                summary="梳理" * 120,
                takeaway="结论" * 80,
                facts=[],
                commentary="评价",
                risk_note="风险" * 80,
                sources=[],
                confidence="low",
            ),
        )

        self.assertLessEqual(len(caption), 1024)
        self.assertIn("一句话结论", caption)
        self.assertIn("热点梳理", caption)
        self.assertIn("风险提示", caption)
        self.assertIn("核验程度：低", caption)

    def test_reply_markup_contains_detail_and_weibo_buttons(self) -> None:
        markup = build_reply_markup("https://site.test/topics/a", "https://s.weibo.com/weibo?q=a")

        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "查看详情")
        self.assertEqual(markup["inline_keyboard"][0][1]["text"], "微博来源")

    def test_reply_markup_omits_localhost_detail_url(self) -> None:
        markup = build_reply_markup("http://localhost:3000/topics/a", "https://s.weibo.com/weibo?q=a")

        self.assertEqual(len(markup["inline_keyboard"][0]), 1)
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "微博来源")

    def test_sends_photo_url_and_caches_file_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            session = FakeTelegramSession([_ok_photo("message-1", "file-1")])
            notifier = TelegramNotifier(_config(), session=session, asset_store=repository)
            topic = _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg")

            result = notifier.send_topic(topic, ("爆",), detail_url="https://site.test/topics/a")

            self.assertTrue(result.ok)
            self.assertEqual(result.external_message_id, "message-1")
            self.assertEqual(repository.get_integration_asset("telegram", file_cache_key(topic.cover_image_url)), "file-1")
            self.assertFalse(session.posts[0]["has_files"])
            self.assertEqual(session.posts[0]["json"]["photo"], topic.cover_image_url)
            self.assertIn("reply_markup", session.posts[0]["json"])
            self.assertEqual(
                session.posts[0]["json"]["reply_markup"]["inline_keyboard"][0][1]["url"],
                weibo_mobile_search_url(topic.title),
            )
            repository.close()

    def test_reuses_cached_file_id_without_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg")
            repository.set_integration_asset("telegram", file_cache_key(topic.cover_image_url), "cached-file")
            session = FakeTelegramSession([_ok_photo("message-2", "cached-file")])
            notifier = TelegramNotifier(_config(), session=session, asset_store=repository)

            result = notifier.send_topic(topic, ("爆",))

            self.assertTrue(result.ok)
            self.assertFalse(session.posts[0]["has_files"])
            self.assertEqual(session.posts[0]["json"]["photo"], "cached-file")
            repository.close()

    def test_reuploads_when_cached_file_id_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg")
            repository.set_integration_asset("telegram", file_cache_key(topic.cover_image_url), "expired-file")
            session = FakeTelegramSession(
                [
                    {"ok": False, "description": "wrong file identifier"},
                    _ok_photo("message-3", "fresh-file"),
                ]
            )
            notifier = TelegramNotifier(_config(), session=session, asset_store=repository)

            result = notifier.send_topic(topic, ("爆",))

            self.assertTrue(result.ok)
            self.assertFalse(session.posts[0]["has_files"])
            self.assertFalse(session.posts[1]["has_files"])
            self.assertEqual(session.posts[1]["json"]["photo"], topic.cover_image_url)
            self.assertEqual(repository.get_integration_asset("telegram", file_cache_key(topic.cover_image_url)), "fresh-file")
            repository.close()

    def test_sends_message_when_topic_has_no_cover_image(self) -> None:
        session = FakeTelegramSession([{"ok": True, "result": {"message_id": "message-4"}}])
        notifier = TelegramNotifier(_config(), session=session)

        result = notifier.send_topic(_topic("爆点新闻", "爆"), ("爆",), detail_url="https://site.test/topics/a")

        self.assertTrue(result.ok)
        self.assertTrue(session.posts[0]["url"].endswith("/sendMessage"))
        self.assertIn("text", session.posts[0]["json"])

    def test_falls_back_to_message_when_photo_url_content_type_is_rejected(self) -> None:
        session = FakeTelegramSession(
            [
                {"ok": False, "description": "Bad Request: wrong type of the web page content"},
                {"ok": True, "result": {"message_id": "message-fallback"}},
            ]
        )
        notifier = TelegramNotifier(_config(), session=session)

        result = notifier.send_topic(
            _topic("爆点新闻", "爆", cover_image_url="https://wx2.sinaimg.cn/orj480/hot.jpg"),
            ("爆",),
            detail_url="https://site.test/topics/a",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.external_message_id, "message-fallback")
        self.assertEqual(len(session.posts), 2)
        self.assertTrue(session.posts[0]["url"].endswith("/sendPhoto"))
        self.assertTrue(session.posts[1]["url"].endswith("/sendMessage"))
        self.assertIn("text", session.posts[1]["json"])

    def test_keeps_failure_when_photo_and_message_fallback_both_fail(self) -> None:
        session = FakeTelegramSession(
            [
                {"ok": False, "description": "Bad Request: wrong type of the web page content"},
                {"ok": False, "description": "Bad Request: chat not found"},
            ]
        )
        notifier = TelegramNotifier(_config(max_retries=1), session=session)

        result = notifier.send_topic(
            _topic("爆点新闻", "爆", cover_image_url="https://wx2.sinaimg.cn/orj480/hot.jpg"),
            ("爆",),
            detail_url="https://site.test/topics/a",
        )

        self.assertFalse(result.ok)
        self.assertIn("wrong type of the web page content", result.error_message)
        self.assertIn("文本降级失败", result.error_message)
        self.assertEqual(len(session.posts), 2)

    def test_http_error_uses_platform_description_without_bot_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session = FakeTelegramSession(
                [FakeResponse({"ok": False, "description": "Bad Request: BUTTON_URL_INVALID"}, status_code=400)]
            )
            notifier = TelegramNotifier(_config(max_retries=1), session=session)

            result = notifier.send_topic(
                _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg"),
                ("爆",),
                detail_url="http://localhost:3000/topics/a",
            )

            self.assertFalse(result.ok)
            self.assertIn("BUTTON_URL_INVALID", result.error_message)
            self.assertNotIn("/bot", result.error_message)


def _ok_photo(message_id: str, file_id: str) -> dict:
    return {
        "ok": True,
        "result": {
            "message_id": message_id,
            "photo": [{"file_id": "small"}, {"file_id": file_id}],
        },
    }


def _config(max_retries: int = 3) -> TelegramConfig:
    return TelegramConfig(
        bot_token="token",
        chat_id="@channel",
        max_retries=max_retries,
    )


def _topic(
    title: str,
    tag: str,
    cover_image_url: str = "",
    *,
    source_id: str = "test",
    source_excerpt: str = "",
) -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=120000,
        tag=tag,
        url="https://s.weibo.com/weibo?q=test",
        source_id=source_id,
        fetched_at="2026-06-09T18:00:00+08:00",
        cover_image_url=cover_image_url,
        source_excerpt=source_excerpt,
    )


if __name__ == "__main__":
    unittest.main()
