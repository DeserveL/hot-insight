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
            topic = _topic("爆点新闻", "爆")
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
            self.assertEqual(detail.status_code, 200)
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
