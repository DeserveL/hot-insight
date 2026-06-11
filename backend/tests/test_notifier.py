import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import WeComConfig
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, AIDetailSource, TopicCandidate
from backend.app.services.notifications.wecom import (
    WeComNotifier,
    build_mpnews_payload,
    cover_media_cache_key,
)


class FakeResponse:
    def __init__(self, payload: dict, *, content: bytes = b"", headers: dict | None = None) -> None:
        self.payload = payload
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeWeComSession:
    def __init__(
        self,
        *,
        media_ids: list[str] | None = None,
        send_responses: list[dict] | None = None,
        material_items: list[dict] | None = None,
    ) -> None:
        self.media_ids = media_ids or ["media-1"]
        self.send_responses = send_responses or [{"errcode": 0, "errmsg": "ok"}]
        self.material_items = material_items or []
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.gets.append({"url": url, "params": params, "timeout": timeout, "headers": headers})
        if str(url).startswith("https://img.example.com"):
            return FakeResponse({}, content=b"image-bytes", headers={"content-type": "image/jpeg"})
        return FakeResponse({"access_token": "token-1", "expires_in": 7200})

    def post(self, url, params=None, json=None, files=None, timeout=None):
        self.posts.append({"url": url, "params": params, "json": json, "has_files": files is not None})
        if "material/batchget" in str(url):
            return FakeResponse({"errcode": 0, "errmsg": "ok", "itemlist": self.material_items})
        if files is not None:
            return FakeResponse({"errcode": 0, "errmsg": "ok", "media_id": self.media_ids.pop(0)})
        return FakeResponse(self.send_responses.pop(0))


class NotifierTests(unittest.TestCase):
    def test_mpnews_payload_contains_required_article_fields(self) -> None:
        topic = _topic("爆点新闻", "爆")
        payload = build_mpnews_payload(topic, _config(Path("cover.png")), "media-1")
        article = payload["mpnews"]["articles"][0]

        self.assertEqual(payload["msgtype"], "mpnews")
        self.assertEqual(article["title"], "💥【爆】爆点新闻")
        self.assertEqual(article["thumb_media_id"], "media-1")
        self.assertEqual(article["content_source_url"], topic.url)
        self.assertIn("洞察暂未生成", article["content"])
        self.assertIn("热度", article["digest"])

    def test_mpnews_content_renders_ai_detail(self) -> None:
        topic = _topic("爆点新闻", "爆")
        detail = AIDetail(
            summary="这是原热搜内容梳理。",
            takeaway="一句话结论。",
            facts=["事实一", "事实二"],
            commentary="AI 评价内容。",
            risk_note="仍需关注后续信息。",
            sources=[AIDetailSource(title="来源一", url="https://example.com/a")],
            confidence="medium",
        )
        payload = build_mpnews_payload(topic, _config(Path("cover.png")), "media-1", detail)
        content = payload["mpnews"]["articles"][0]["content"]

        self.assertIn("这是原热搜内容梳理。", content)
        self.assertIn("一句话结论。", content)
        self.assertIn("事实一", content)
        self.assertIn("AI 评价内容。", content)
        self.assertIn("https://example.com/a", content)

    def test_uploads_official_cover_url_and_caches_media_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cover = _write_cover(Path(temp_dir) / "cover.png")
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            session = FakeWeComSession(media_ids=["media-cached"])
            notifier = WeComNotifier(_config(cover), session=session, asset_store=repository)
            topic = _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg")

            self.assertTrue(notifier.send_mpnews_topic(topic, ("爆", "沸", "热")))
            self.assertEqual(
                repository.get_integration_asset("wecom", cover_media_cache_key(topic.cover_image_url)),
                "media-cached",
            )
            self.assertEqual(sum(1 for post in session.posts if post["has_files"]), 1)
            self.assertEqual(session.posts[-1]["json"]["mpnews"]["articles"][0]["thumb_media_id"], "media-cached")
            repository.close()

    def test_uses_wecom_material_named_hot_jpeg_as_default_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cover = _write_cover(Path(temp_dir) / "cover.png")
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            session = FakeWeComSession(material_items=[{"name": "hot.jpeg", "media_id": "material-media"}])
            notifier = WeComNotifier(_config(cover), session=session, asset_store=repository)

            self.assertTrue(notifier.send_mpnews_topic(_topic("爆点新闻", "爆"), ("爆",)))
            self.assertEqual(sum(1 for post in session.posts if post["has_files"]), 0)
            self.assertEqual(session.posts[-1]["json"]["mpnews"]["articles"][0]["thumb_media_id"], "material-media")
            repository.close()

    def test_reuploads_when_cached_media_id_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cover = _write_cover(Path(temp_dir) / "cover.png")
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            topic = _topic("爆点新闻", "爆", cover_image_url="https://img.example.com/hot.jpg")
            repository.set_integration_asset("wecom", cover_media_cache_key(topic.cover_image_url), "expired-media")
            session = FakeWeComSession(
                media_ids=["fresh-media"],
                send_responses=[
                    {"errcode": 40007, "errmsg": "invalid media_id"},
                    {"errcode": 0, "errmsg": "ok"},
                ],
            )
            notifier = WeComNotifier(_config(cover), session=session, asset_store=repository)

            self.assertTrue(notifier.send_mpnews_topic(topic, ("爆",)))
            self.assertEqual(
                repository.get_integration_asset("wecom", cover_media_cache_key(topic.cover_image_url)),
                "fresh-media",
            )
            self.assertEqual(sum(1 for post in session.posts if post["has_files"]), 1)
            self.assertEqual(session.posts[-1]["json"]["mpnews"]["articles"][0]["thumb_media_id"], "fresh-media")
            repository.close()


def _config(cover: Path) -> WeComConfig:
    return WeComConfig(
        corp_id="corp",
        corp_secret="secret",
        agent_id="agent",
        to_user="@all",
        default_cover=cover,
    )


def _topic(title: str, tag: str, cover_image_url: str = "") -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=120000,
        tag=tag,
        url="https://s.weibo.com/weibo?q=test",
        source_id="test",
        fetched_at="2026-06-09T18:00:00+08:00",
        cover_image_url=cover_image_url,
    )


def _write_cover(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


if __name__ == "__main__":
    unittest.main()
