import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, TopicCandidate
from backend.app.main import app


class ApiTests(unittest.TestCase):
    def test_health_channels_topics_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "hot_insight.sqlite3"
            topic = _topic("爆点新闻", "爆").with_source_material(
                source_excerpt="官方来源摘要",
                source_excerpt_origin="official",
            )
            repository = AppRepository(database_path)
            repository.save_topics([topic])
            repository.save_ai_insight_success(
                topic,
                AIDetail(
                    summary="摘要",
                    takeaway="一句话结论",
                    facts=["事实"],
                    commentary="评价",
                    risk_note="风险",
                    sources=[],
                    confidence="medium",
                ),
                "model",
            )
            repository.close()

            with patch.dict(
                os.environ,
                {"DATABASE_PATH": str(database_path), "API_SCHEDULER_ENABLED": "false", "LOG_FILE_ENABLED": "false"},
                clear=False,
            ):
                with TestClient(app) as client:
                    health = client.get("/health")
                    channels = client.get("/api/v1/channels")
                    topics = client.get("/api/v1/topics?channel=weibo")
                    detail = client.get(f"/api/v1/topics/{topic.id}")
                    summary = client.get("/api/v1/trends/summary")

            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["ok"])
            self.assertEqual(channels.status_code, 200)
            self.assertEqual(topics.status_code, 200)
            self.assertEqual(topics.json()["items"][0]["title"], "爆点新闻")
            self.assertEqual(topics.json()["items"][0]["tag"], "爆")
            self.assertEqual(topics.json()["items"][0]["peak_tag"], "爆")
            self.assertEqual(topics.json()["items"][0]["best_rank"], 1)
            self.assertEqual(topics.json()["items"][0]["peak_score"], 100)
            self.assertIn("m.weibo.cn/search", topics.json()["items"][0]["mobile_url"])
            self.assertEqual(topics.json()["items"][0]["source_excerpt_origin"], "official")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["peak_tag"], "爆")
            self.assertEqual(detail.json()["best_rank"], 1)
            self.assertEqual(detail.json()["peak_score"], 100)
            self.assertEqual(detail.json()["source_excerpt_origin"], "official")
            self.assertEqual(detail.json()["ai_detail"]["summary"], "摘要")
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json()["topic_count"], 1)

    def test_topic_detail_404(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "hot_insight.sqlite3"
            AppRepository(database_path).close()
            with patch.dict(
                os.environ,
                {"DATABASE_PATH": str(database_path), "API_SCHEDULER_ENABLED": "false", "LOG_FILE_ENABLED": "false"},
                clear=False,
            ):
                with TestClient(app) as client:
                    response = client.get("/api/v1/topics/missing")

            self.assertEqual(response.status_code, 404)

    def test_ai_failure_error_is_not_exposed_in_topic_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "hot_insight.sqlite3"
            topic = _topic("失败热点", "热")
            raw_error = "503 Server Error: Service Unavailable for url: https://ccpa.234248.xyz/v1/responses"
            repository = AppRepository(database_path)
            repository.save_topics([topic])
            repository.save_ai_insight_failure(topic, raw_error, "model")
            record = repository.get_ai_insight_record(topic.id)
            self.assertIn("503 Server Error", record["error_message"])
            repository.close()

            with patch.dict(
                os.environ,
                {"DATABASE_PATH": str(database_path), "API_SCHEDULER_ENABLED": "false", "LOG_FILE_ENABLED": "false"},
                clear=False,
            ):
                with TestClient(app) as client:
                    topics = client.get("/api/v1/topics?channel=weibo")
                    detail = client.get(f"/api/v1/topics/{topic.id}")

            self.assertEqual(topics.status_code, 200)
            self.assertEqual(detail.status_code, 200)
            for payload in (topics.json()["items"][0], detail.json()):
                with self.subTest(payload=payload["id"]):
                    self.assertEqual(payload["ai_status"], "failed")
                    self.assertIsNone(payload["ai_detail"])
                    self.assertEqual(payload["ai_error"], "洞察生成中，请稍后查看。")
                    self.assertNotIn("503 Server Error", payload["ai_error"])
                    self.assertNotIn("ccpa.234248.xyz", payload["ai_error"])
                    self.assertNotIn("/v1/responses", payload["ai_error"])


def _topic(title: str, tag: str) -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=1,
        score=100,
        tag=tag,
        url="https://s.weibo.com/weibo?q=test",
        source_id="test",
        fetched_at="2026-06-09T18:00:00+08:00",
    )


if __name__ == "__main__":
    unittest.main()
