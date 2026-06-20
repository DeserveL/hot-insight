import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.app.db.repositories import AppRepository
from backend.app.domain.models import TopicCandidate, WeiboRealtimePost


class SchemaTests(unittest.TestCase):
    def test_repository_connection_can_close_from_different_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(repository.close)
                future.result(timeout=5)

    def test_initializes_new_database_name_and_schema_without_legacy_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "hot_insight.sqlite3"
            repository = AppRepository(database_path)
            repository.close()

            self.assertTrue(database_path.is_file())
            self.assertEqual(database_path.name, "hot_insight.sqlite3")

            conn = sqlite3.connect(database_path)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(
                tables,
                {
                    "channels",
                    "sources",
                    "fetch_runs",
                    "topics",
                    "topic_observations",
                    "ai_insights",
                    "notification_targets",
                    "notification_deliveries",
                    "integration_assets",
                },
            )

            legacy_tables = {"sent" "_items", "snap" "shots", "source" "_health", "kv", "ai" "_details"}
            self.assertTrue(tables.isdisjoint(legacy_tables))

            topic_columns = {row[1] for row in conn.execute("PRAGMA table_info(topics)")}
            legacy_columns = {"item" "_key", "hot" "_value", "label"}
            self.assertTrue(topic_columns.isdisjoint(legacy_columns))
            self.assertIn("id", topic_columns)
            self.assertIn("title_key", topic_columns)
            self.assertIn("tag", topic_columns)
            self.assertIn("peak_tag", topic_columns)
            self.assertIn("score", topic_columns)
            self.assertIn("peak_score", topic_columns)
            self.assertIn("best_rank", topic_columns)
            self.assertIn("occurrence_started_at", topic_columns)
            self.assertIn("recurrence_window_hours", topic_columns)
            self.assertIn("source_excerpt", topic_columns)
            self.assertIn("source_excerpt_origin", topic_columns)
            self.assertIn("cover_image_url", topic_columns)
            self.assertIn("realtime_posts_json", topic_columns)
            ai_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_insights)")}
            self.assertIn("takeaway", ai_columns)
            self.assertIn("prompt_version", ai_columns)
            self.assertIn("api_mode", ai_columns)
            self.assertIn("context_hash", ai_columns)
            self.assertIn("failed_retry_context_hash", ai_columns)
            self.assertIn("search_source_count", ai_columns)
            conn.close()

    def test_migrates_legacy_topics_with_tag_specific_recurrence_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "hot_insight.sqlite3"
            conn = sqlite3.connect(database_path)
            conn.execute(
                """
                CREATE TABLE topics (
                    id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    rank INTEGER,
                    score INTEGER,
                    source_excerpt TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                INSERT INTO topics
                    (
                        id, channel_id, title, url, tag, rank, score, source_excerpt, source_id,
                        first_seen_at, last_seen_at, seen_count
                    )
                VALUES
                    ('legacy-topic', 'weibo', '  旧 热点  ', 'https://s.weibo.com/weibo?q=test',
                     '爆', 1, 100, '旧摘要', 'legacy', '2026-06-09T00:00:00+08:00',
                     '2026-06-09T00:00:00+08:00', 1)
                """
            )
            conn.commit()
            conn.close()

            repository = AppRepository(database_path)
            topic = repository.get_topic("legacy-topic")
            origin = repository.conn.execute(
                "SELECT source_excerpt_origin FROM topics WHERE id = 'legacy-topic'"
            ).fetchone()[0]

            self.assertEqual(topic["title_key"], "旧 热点")
            self.assertEqual(topic["occurrence_started_at"], "2026-06-09T00:00:00+08:00")
            self.assertEqual(topic["recurrence_window_hours"], 12)
            self.assertEqual(topic["peak_tag"], "爆")
            self.assertEqual(topic["best_rank"], 1)
            self.assertEqual(topic["peak_score"], 100)
            self.assertEqual(topic["source_excerpt"], "旧摘要")
            self.assertEqual(origin, "mobile")
            self.assertEqual(topic["realtime_posts"], [])
            self.assertIn("m.weibo.cn/search", topic["mobile_url"])
            repository.close()

    def test_realtime_posts_are_stored_and_mobile_excerpt_does_not_overwrite_existing_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            first = _topic_at("实时热点", "爆", "2026-06-09T00:00:00+08:00").with_source_material(
                source_excerpt="移动摘要",
                source_excerpt_origin="mobile",
                realtime_posts=[
                    WeiboRealtimePost(
                        author="用户A",
                        created_at="2026-06-09T00:00:00+08:00",
                        text="实时内容",
                        reposts=1,
                        comments=2,
                        attitudes=3,
                        url="https://m.weibo.cn/status/1",
                    )
                ],
            )
            repository.save_topics([first])
            second = _topic_at("实时热点", "爆", "2026-06-09T01:00:00+08:00").with_source_material(
                source_excerpt="新的移动摘要",
                source_excerpt_origin="mobile",
            )
            repository.save_topics([second])
            third = _topic_at("实时热点", "爆", "2026-06-09T02:00:00+08:00")
            repository.save_topics([third])
            saved = repository.get_topic(first.id)
            origin = repository.conn.execute(
                "SELECT source_excerpt_origin FROM topics WHERE id = ?",
                (first.id,),
            ).fetchone()[0]

            self.assertEqual(saved["source_excerpt"], "移动摘要")
            self.assertEqual(saved["realtime_posts"][0]["author"], "用户A")
            self.assertIn("m.weibo.cn/search", saved["mobile_url"])
            self.assertEqual(origin, "mobile")
            repository.close()

    def test_official_excerpt_overwrites_mobile_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            mobile = _topic_at("官方覆盖热点", "爆", "2026-06-09T00:00:00+08:00").with_source_material(
                source_excerpt="移动摘要",
                source_excerpt_origin="mobile",
            )
            official = _topic_at("官方覆盖热点", "爆", "2026-06-09T01:00:00+08:00").with_source_material(
                source_excerpt="官方摘要",
                source_excerpt_origin="official",
            )

            repository.save_topics([mobile])
            repository.save_topics([official])
            saved = repository.get_topic(mobile.id)
            origin = repository.conn.execute(
                "SELECT source_excerpt_origin FROM topics WHERE id = ?",
                (mobile.id,),
            ).fetchone()[0]

            self.assertEqual(saved["source_excerpt"], "官方摘要")
            self.assertEqual(origin, "official")
            repository.close()

    def test_official_detail_url_is_not_overwritten_by_lower_priority_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")
            official = _topic(
                source_id="weibo_official",
                url="https://weibo.com/a/hot/abc_0.html?type=grab",
            )
            fallback = _topic(
                source_id="xunjinlu",
                url="https://api.example.com/topic",
            )

            repository.save_topics([official])
            repository.save_topics([fallback])
            saved = repository.get_topic(official.id)

            self.assertEqual(saved["url"], "https://weibo.com/a/hot/abc_0.html?type=grab")
            repository.close()

    def test_bao_topic_within_11_hours_updates_same_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            first = repository.save_topics([_topic_at("复现热点", "爆", "2026-06-09T00:00:00+08:00")])[0]
            second = repository.save_topics([_topic_at("复现热点", "爆", "2026-06-09T11:00:00+08:00")])[0]
            saved = repository.get_topic(first.id)

            self.assertEqual(second.id, first.id)
            self.assertEqual(saved["seen_count"], 2)
            self.assertEqual(saved["recurrence_window_hours"], 12)
            repository.close()

    def test_bao_topic_at_12_hours_creates_new_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            first = repository.save_topics([_topic_at("复现热点", "爆", "2026-06-09T00:00:00+08:00")])[0]
            second = repository.save_topics([_topic_at("复现热点", "爆", "2026-06-09T12:00:00+08:00")])[0]

            self.assertNotEqual(second.id, first.id)
            self.assertEqual(repository.get_topic(first.id)["seen_count"], 1)
            self.assertEqual(repository.get_topic(second.id)["seen_count"], 1)
            repository.close()

    def test_re_topic_uses_24_hour_recurrence_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            first = repository.save_topics([_topic_at("复现热点", "热", "2026-06-09T00:00:00+08:00")])[0]
            within = repository.save_topics([_topic_at("复现热点", "热", "2026-06-09T23:00:00+08:00")])[0]
            boundary = repository.save_topics([_topic_at("复现热点", "热", "2026-06-10T23:00:00+08:00")])[0]

            self.assertEqual(within.id, first.id)
            self.assertNotEqual(boundary.id, first.id)
            self.assertEqual(repository.get_topic(first.id)["seen_count"], 2)
            repository.close()

    def test_same_occurrence_preserves_peak_tag_best_rank_and_peak_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            first = repository.save_topics(
                [_topic_at("峰值热点", "热", "2026-06-09T00:00:00+08:00", rank=11, score=1_000_000)]
            )[0]
            second = repository.save_topics(
                [_topic_at("峰值热点", "爆", "2026-06-09T01:00:00+08:00", rank=1, score=3_000_000)]
            )[0]
            third = repository.save_topics(
                [_topic_at("峰值热点", "热", "2026-06-09T02:00:00+08:00", rank=11, score=2_000_000)]
            )[0]
            saved = repository.get_topic(first.id)

            self.assertEqual(second.id, first.id)
            self.assertEqual(third.id, first.id)
            self.assertEqual(saved["tag"], "热")
            self.assertEqual(saved["rank"], 11)
            self.assertEqual(saved["score"], 2_000_000)
            self.assertEqual(saved["peak_tag"], "爆")
            self.assertEqual(saved["best_rank"], 1)
            self.assertEqual(saved["peak_score"], 3_000_000)
            self.assertEqual(saved["seen_count"], 3)

            bao_topics = repository.list_topics(tag="爆", limit=10)["items"]
            re_topics = repository.list_topics(tag="热", limit=10)["items"]
            summary = repository.get_trends_summary()

            self.assertEqual([topic["id"] for topic in bao_topics], [first.id])
            self.assertEqual(re_topics, [])
            self.assertEqual(summary["tags"], [{"tag": "爆", "count": 1}])
            repository.close()

    def test_new_occurrence_has_independent_ai_and_notification_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = AppRepository(Path(temp_dir) / "hot_insight.sqlite3")

            first = repository.save_topics([_topic_at("复现热点", "沸", "2026-06-09T00:00:00+08:00")])[0]
            second = repository.save_topics([_topic_at("复现热点", "沸", "2026-06-09T12:00:00+08:00")])[0]
            repository.save_ai_insight_success(first, _detail(), "model-a")
            repository.record_notification_delivery(topic=first, provider="test", target="target", success=True)

            self.assertNotEqual(first.id, second.id)
            self.assertIsNotNone(repository.get_ai_insight_record(first.id))
            self.assertIsNone(repository.get_ai_insight_record(second.id))
            self.assertEqual(repository.pending_delivery_targets(first, [("test", "target")]), [])
            self.assertEqual(repository.pending_delivery_targets(second, [("test", "target")]), [("test", "target")])
            repository.close()


def _topic(source_id: str, url: str) -> TopicCandidate:
    return TopicCandidate(
        title="同一热点",
        rank=1,
        score=100,
        tag="爆",
        url=url,
        source_id=source_id,
        fetched_at="2026-06-09T18:00:00+08:00",
    )


def _topic_at(title: str, tag: str, fetched_at: str, *, rank: int = 1, score: int = 100) -> TopicCandidate:
    return TopicCandidate(
        title=title,
        rank=rank,
        score=score,
        tag=tag,
        url="https://s.weibo.com/weibo?q=test",
        source_id="test",
        fetched_at=fetched_at,
    )


def _detail():
    from backend.app.domain.models import AIDetail

    return AIDetail(
        summary="摘要",
        takeaway="一句话结论",
        facts=["事实"],
        commentary="评价",
        risk_note="风险",
        sources=[],
        confidence="medium",
    )


if __name__ == "__main__":
    unittest.main()
