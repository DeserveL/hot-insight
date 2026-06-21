from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha1
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse

from backend.app.core.logging import mask_external_target
from backend.app.db.connection import connect
from backend.app.db.schema import SCHEMA_SQL
from backend.app.domain.models import (
    AIDetail,
    TopicCandidate,
    WEIBO_CHANNEL_ID,
    make_topic_id,
    normalize_title_key,
    now_iso,
    weibo_mobile_search_url,
    WeiboRealtimePost,
)
from backend.app.services.ai.sanitizer import sanitize_public_risk_note

DEFAULT_TAG_RECURRENCE_HOURS = {"爆": 12, "沸": 12, "热": 24}
DEFAULT_RECURRENCE_HOURS = 24
logger = logging.getLogger(__name__)


class AppRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.conn = connect(self.database_path)
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self._migrate_columns()
        self.ensure_channel(WEIBO_CHANNEL_ID, "微博热搜")
        self.conn.commit()
        logger.debug("数据库 schema 已确认: database_path=%s", self.database_path)

    def _migrate_columns(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(topics)").fetchall()}
        migrations = {
            "title_key": "ALTER TABLE topics ADD COLUMN title_key TEXT NOT NULL DEFAULT ''",
            "occurrence_started_at": (
                "ALTER TABLE topics ADD COLUMN occurrence_started_at TEXT NOT NULL DEFAULT ''"
            ),
            "recurrence_window_hours": (
                "ALTER TABLE topics ADD COLUMN recurrence_window_hours INTEGER NOT NULL DEFAULT 24"
            ),
            "source_excerpt": "ALTER TABLE topics ADD COLUMN source_excerpt TEXT NOT NULL DEFAULT ''",
            "source_excerpt_origin": (
                "ALTER TABLE topics ADD COLUMN source_excerpt_origin TEXT NOT NULL DEFAULT ''"
            ),
            "cover_image_url": "ALTER TABLE topics ADD COLUMN cover_image_url TEXT NOT NULL DEFAULT ''",
            "realtime_posts_json": "ALTER TABLE topics ADD COLUMN realtime_posts_json TEXT NOT NULL DEFAULT '[]'",
            "peak_tag": "ALTER TABLE topics ADD COLUMN peak_tag TEXT NOT NULL DEFAULT ''",
            "best_rank": "ALTER TABLE topics ADD COLUMN best_rank INTEGER",
            "peak_score": "ALTER TABLE topics ADD COLUMN peak_score INTEGER",
        }
        for column, statement in migrations.items():
            if column not in columns:
                self.conn.execute(statement)

        ai_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(ai_insights)").fetchall()}
        ai_migrations = {
            "takeaway": "ALTER TABLE ai_insights ADD COLUMN takeaway TEXT NOT NULL DEFAULT ''",
            "prompt_version": "ALTER TABLE ai_insights ADD COLUMN prompt_version TEXT NOT NULL DEFAULT ''",
            "api_mode": "ALTER TABLE ai_insights ADD COLUMN api_mode TEXT NOT NULL DEFAULT ''",
            "context_hash": "ALTER TABLE ai_insights ADD COLUMN context_hash TEXT NOT NULL DEFAULT ''",
            "failed_retry_context_hash": (
                "ALTER TABLE ai_insights ADD COLUMN failed_retry_context_hash TEXT NOT NULL DEFAULT ''"
            ),
            "context_material_json": (
                "ALTER TABLE ai_insights ADD COLUMN context_material_json TEXT NOT NULL DEFAULT '{}'"
            ),
            "search_source_count": (
                "ALTER TABLE ai_insights ADD COLUMN search_source_count INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for column, statement in ai_migrations.items():
            if column not in ai_columns:
                self.conn.execute(statement)

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topics_title_key_last_seen
                ON topics(channel_id, title_key, last_seen_at DESC)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_topics_peak_tag_last_seen
                ON topics(peak_tag, last_seen_at DESC)
            """
        )
        rows = self.conn.execute(
            """
            SELECT id, title, tag, first_seen_at, title_key, occurrence_started_at, recurrence_window_hours
            FROM topics
            """
        ).fetchall()
        for row in rows:
            needs_backfill = not row["title_key"] or not row["occurrence_started_at"]
            title_key = str(row["title_key"] or "") or normalize_title_key(str(row["title"] or ""))
            occurrence_started_at = str(row["occurrence_started_at"] or "") or str(row["first_seen_at"] or "")
            recurrence_window_hours = (
                _recurrence_hours_for_tag(str(row["tag"] or ""), DEFAULT_TAG_RECURRENCE_HOURS)
                if needs_backfill
                else int(row["recurrence_window_hours"] or DEFAULT_RECURRENCE_HOURS)
            )
            self.conn.execute(
                """
                UPDATE topics
                SET title_key = ?, occurrence_started_at = ?, recurrence_window_hours = ?
                WHERE id = ?
                """,
                (title_key, occurrence_started_at, recurrence_window_hours, row["id"]),
            )
        self.conn.execute("UPDATE topics SET peak_tag = tag WHERE peak_tag = ''")
        self.conn.execute("UPDATE topics SET best_rank = rank WHERE best_rank IS NULL AND rank IS NOT NULL")
        self.conn.execute("UPDATE topics SET peak_score = score WHERE peak_score IS NULL AND score IS NOT NULL")
        self.conn.execute(
            "UPDATE topics SET source_excerpt_origin = 'mobile' "
            "WHERE source_excerpt != '' AND source_excerpt_origin = ''"
        )

    def ensure_channel(self, channel_id: str, name: str) -> None:
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO channels (id, name, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (channel_id, name, now, now),
        )

    def ensure_source(self, *, channel_id: str, source_id: str, supports_tags: bool) -> None:
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO sources
                (id, channel_id, name, supports_tags, last_checked_at, status, message, topic_count)
            VALUES
                (?, ?, ?, ?, ?, 'unknown', '', 0)
            ON CONFLICT(id) DO UPDATE SET
                channel_id = excluded.channel_id,
                supports_tags = excluded.supports_tags
            """,
            (source_id, channel_id, source_id, 1 if supports_tags else 0, now),
        )

    def record_fetch_run(
        self,
        *,
        channel_id: str,
        source_id: str,
        started_at: str,
        finished_at: str,
        ok: bool,
        message: str,
        topic_count: int,
        supports_tags: bool,
    ) -> None:
        self.ensure_source(channel_id=channel_id, source_id=source_id, supports_tags=supports_tags)
        status = "success" if ok else "failed"
        self.conn.execute(
            """
            INSERT INTO fetch_runs
                (channel_id, source_id, started_at, finished_at, status, message, topic_count, supports_tags)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (channel_id, source_id, started_at, finished_at, status, message, topic_count, 1 if supports_tags else 0),
        )
        self.conn.execute(
            """
            UPDATE sources
            SET last_checked_at = ?, status = ?, message = ?, topic_count = ?, supports_tags = ?
            WHERE id = ?
            """,
            (finished_at, status, message, topic_count, 1 if supports_tags else 0, source_id),
        )
        self.conn.commit()

    def save_topics(
        self,
        topics: list[TopicCandidate],
        tag_recurrence_hours: Mapping[str, int] | None = None,
    ) -> list[TopicCandidate]:
        if not topics:
            return []
        recurrence_hours = dict(tag_recurrence_hours or DEFAULT_TAG_RECURRENCE_HOURS)
        for topic in topics:
            self.ensure_channel(topic.channel_id, "微博热搜" if topic.channel_id == WEIBO_CHANNEL_ID else topic.channel_id)
            self.ensure_source(channel_id=topic.channel_id, source_id=topic.source_id, supports_tags=bool(topic.tag))
        topic_params = []
        observation_params = []
        resolved_topics: list[TopicCandidate] = []
        new_count = 0
        updated_count = 0
        for topic in topics:
            resolved_topic = self._resolve_topic_occurrence(topic, recurrence_hours)
            resolved_topics.append(resolved_topic)
            if self._topic_exists(resolved_topic.id):
                updated_count += 1
            else:
                new_count += 1
            params = _topic_params(resolved_topic)
            topic_params.append({**params, "url": self._preferred_topic_url(resolved_topic.id, resolved_topic.url)})
            observation_params.append(params)
            logger.debug(
                "热点入库明细: topic_id=%s title=%s tag=%s rank=%s source=%s",
                resolved_topic.id,
                resolved_topic.title,
                resolved_topic.tag,
                resolved_topic.rank,
                resolved_topic.source_id,
            )

        self.conn.executemany(
            """
            INSERT INTO topics
                (
                    id, channel_id, title, title_key, url, source_excerpt, source_excerpt_origin,
                    cover_image_url, realtime_posts_json,
                    tag, peak_tag, rank, best_rank, score, peak_score, source_id,
                    occurrence_started_at, recurrence_window_hours,
                    first_seen_at, last_seen_at, seen_count
                )
            VALUES
                (
                    :id, :channel_id, :title, :title_key, :url, :source_excerpt, :source_excerpt_origin,
                    :cover_image_url, :realtime_posts_json,
                    :tag, :peak_tag, :rank, :best_rank, :score, :peak_score, :source_id,
                    :occurrence_started_at, :recurrence_window_hours,
                    :fetched_at, :fetched_at, 1
                )
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                title_key = excluded.title_key,
                url = excluded.url,
                source_excerpt = CASE
                    WHEN excluded.source_excerpt != '' AND (
                        :source_excerpt_origin = 'official' OR topics.source_excerpt = ''
                    ) THEN excluded.source_excerpt
                    ELSE topics.source_excerpt
                END,
                source_excerpt_origin = CASE
                    WHEN excluded.source_excerpt != '' AND :source_excerpt_origin = 'official' THEN 'official'
                    WHEN excluded.source_excerpt != ''
                        AND topics.source_excerpt = ''
                        AND :source_excerpt_origin IN ('official', 'mobile') THEN :source_excerpt_origin
                    WHEN excluded.source_excerpt != ''
                        AND topics.source_excerpt = excluded.source_excerpt
                        AND topics.source_excerpt_origin = ''
                        AND :source_excerpt_origin IN ('official', 'mobile') THEN :source_excerpt_origin
                    ELSE topics.source_excerpt_origin
                END,
                cover_image_url = CASE
                    WHEN excluded.cover_image_url != '' THEN excluded.cover_image_url
                    ELSE topics.cover_image_url
                END,
                realtime_posts_json = CASE
                    WHEN excluded.realtime_posts_json != '[]' THEN excluded.realtime_posts_json
                    ELSE topics.realtime_posts_json
                END,
                tag = excluded.tag,
                peak_tag = CASE
                    WHEN (
                        CASE excluded.peak_tag
                            WHEN '爆' THEN 3
                            WHEN '沸' THEN 2
                            WHEN '热' THEN 1
                            ELSE 0
                        END
                    ) > (
                        CASE topics.peak_tag
                            WHEN '爆' THEN 3
                            WHEN '沸' THEN 2
                            WHEN '热' THEN 1
                            ELSE 0
                        END
                    ) THEN excluded.peak_tag
                    ELSE topics.peak_tag
                END,
                rank = excluded.rank,
                best_rank = CASE
                    WHEN topics.best_rank IS NULL THEN excluded.best_rank
                    WHEN excluded.best_rank IS NULL THEN topics.best_rank
                    WHEN excluded.best_rank < topics.best_rank THEN excluded.best_rank
                    ELSE topics.best_rank
                END,
                score = excluded.score,
                peak_score = CASE
                    WHEN topics.peak_score IS NULL THEN excluded.peak_score
                    WHEN excluded.peak_score IS NULL THEN topics.peak_score
                    WHEN excluded.peak_score > topics.peak_score THEN excluded.peak_score
                    ELSE topics.peak_score
                END,
                source_id = excluded.source_id,
                recurrence_window_hours = excluded.recurrence_window_hours,
                last_seen_at = excluded.last_seen_at,
                seen_count = topics.seen_count + 1
            """,
            topic_params,
        )
        self.conn.executemany(
            """
            INSERT INTO topic_observations
                (topic_id, channel_id, observed_at, source_id, rank, score, tag, url)
            VALUES
                (:id, :channel_id, :fetched_at, :source_id, :rank, :score, :tag, :url)
            """,
            observation_params,
        )
        self.conn.commit()
        stored_topics = self._load_stored_topic_material(resolved_topics)
        logger.info(
            "热点入库完成: total=%s new_occurrences=%s updated_occurrences=%s observations=%s",
            len(stored_topics),
            new_count,
            updated_count,
            len(observation_params),
        )
        return stored_topics

    def _load_stored_topic_material(self, topics: list[TopicCandidate]) -> list[TopicCandidate]:
        if not topics:
            return []
        rows = {
            str(row["id"]): row
            for row in self.conn.execute(
                f"""
                SELECT id, url, source_excerpt, source_excerpt_origin, cover_image_url, realtime_posts_json
                FROM topics
                WHERE id IN ({','.join('?' for _ in topics)})
                """,
                [topic.id for topic in topics],
            ).fetchall()
        }
        result: list[TopicCandidate] = []
        for topic in topics:
            row = rows.get(topic.id)
            if row is None:
                result.append(topic)
                continue
            stored_excerpt = str(row["source_excerpt"] or "")
            stored_origin = str(row["source_excerpt_origin"] or "").strip()
            if stored_excerpt and stored_origin == "official":
                source_excerpt_origin = "official"
                official_context = stored_excerpt
                mobile_context = topic.mobile_context
            elif stored_excerpt:
                source_excerpt_origin = "mobile"
                official_context = topic.official_context
                mobile_context = stored_excerpt
            else:
                source_excerpt_origin = ""
                official_context = ""
                mobile_context = ""
            result.append(
                replace(
                    topic,
                    url=str(row["url"] or topic.url),
                    source_excerpt=stored_excerpt,
                    cover_image_url=str(row["cover_image_url"] or ""),
                    realtime_posts=tuple(_parse_realtime_posts_json(str(row["realtime_posts_json"] or "[]"))),
                    source_excerpt_origin=source_excerpt_origin,
                    official_context=official_context,
                    mobile_context=mobile_context,
                )
            )
        return result

    def _resolve_topic_occurrence(
        self,
        topic: TopicCandidate,
        tag_recurrence_hours: Mapping[str, int],
    ) -> TopicCandidate:
        title_key = normalize_title_key(topic.title)
        recurrence_window_hours = _recurrence_hours_for_tag(topic.tag, tag_recurrence_hours)
        row = self.conn.execute(
            """
            SELECT id, first_seen_at, last_seen_at, occurrence_started_at
            FROM topics
            WHERE channel_id = ? AND title_key = ?
            ORDER BY last_seen_at DESC
            LIMIT 1
            """,
            (topic.channel_id, title_key),
        ).fetchone()
        if row is not None and _is_within_recurrence_window(
            topic.fetched_at,
            str(row["last_seen_at"] or ""),
            recurrence_window_hours,
        ):
            return topic.with_occurrence(
                topic_id=str(row["id"]),
                title_key=title_key,
                occurrence_started_at=str(row["occurrence_started_at"] or row["first_seen_at"] or topic.fetched_at),
                recurrence_window_hours=recurrence_window_hours,
            )

        occurrence_started_at = topic.fetched_at
        return topic.with_occurrence(
            topic_id=make_topic_id(topic.channel_id, title_key, occurrence_started_at),
            title_key=title_key,
            occurrence_started_at=occurrence_started_at,
            recurrence_window_hours=recurrence_window_hours,
        )

    def _preferred_topic_url(self, topic_id: str, new_url: str) -> str:
        row = self.conn.execute("SELECT url FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if row is None:
            return new_url
        current_url = str(row["url"] or "")
        return new_url if _topic_url_priority(new_url) >= _topic_url_priority(current_url) else current_url

    def _topic_exists(self, topic_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM topics WHERE id = ? LIMIT 1", (topic_id,)).fetchone()
        return row is not None

    def pending_delivery_targets(
        self,
        topic: TopicCandidate,
        targets: Iterable[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        target_list = list(targets)
        if not target_list:
            return []
        rows = self.conn.execute(
            """
            SELECT nt.provider, nt.target
            FROM notification_deliveries nd
            INNER JOIN notification_targets nt ON nd.target_id = nt.id
            WHERE nd.topic_id = ? AND nd.status = 'success'
            """,
            (topic.id,),
        ).fetchall()
        successful = {(str(row["provider"]), str(row["target"])) for row in rows}
        return [target for target in target_list if target not in successful]

    def record_notification_delivery(
        self,
        *,
        topic: TopicCandidate,
        provider: str,
        target: str,
        success: bool,
        error_message: str = "",
        external_message_id: str = "",
    ) -> None:
        target_id = make_target_id(provider, target)
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO notification_targets (id, provider, target, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(provider, target) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (target_id, provider, target, now, now),
        )
        self.conn.execute(
            """
            INSERT INTO notification_deliveries
                (
                    topic_id, target_id, provider, status, title, error_message,
                    external_message_id, attempted_at, sent_at
                )
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id, target_id) DO UPDATE SET
                provider = excluded.provider,
                status = excluded.status,
                title = excluded.title,
                error_message = excluded.error_message,
                external_message_id = excluded.external_message_id,
                attempted_at = excluded.attempted_at,
                sent_at = excluded.sent_at
            """,
            (
                topic.id,
                target_id,
                provider,
                "success" if success else "failed",
                topic.title,
                error_message,
                external_message_id,
                now,
                now if success else "",
            ),
        )
        self.conn.commit()
        logger.info(
            "通知投递状态已记录: topic_id=%s provider=%s target=%s status=%s external_message_id=%s",
            topic.id,
            provider,
            mask_external_target(provider, target),
            "success" if success else "failed",
            external_message_id or "-",
        )

    def list_topics(
        self,
        *,
        channel_id: str = WEIBO_CHANNEL_ID,
        tag: str = "",
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict:
        offset = _cursor_to_offset(cursor)
        limit = max(1, min(limit, 100))
        params: list[object] = [channel_id]
        where = "channel_id = ?"
        if tag:
            where += " AND peak_tag = ?"
            params.append(tag)
        rows = self.conn.execute(
            f"""
            SELECT
                id, channel_id, title, title_key, url, source_excerpt, cover_image_url, realtime_posts_json,
                tag, peak_tag, rank, best_rank, score, peak_score, source_id,
                occurrence_started_at, recurrence_window_hours,
                first_seen_at, last_seen_at, seen_count
            FROM topics
            WHERE {where}
            ORDER BY
                last_seen_at DESC,
                CASE peak_tag
                    WHEN '爆' THEN 3
                    WHEN '沸' THEN 2
                    WHEN '热' THEN 1
                    ELSE 0
                END DESC,
                best_rank IS NULL ASC,
                best_rank ASC,
                peak_score DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit + 1, offset),
        ).fetchall()
        topics = [_topic_row_to_dict(row, self.get_ai_insight_record(str(row["id"]))) for row in rows[:limit]]
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return {"items": topics, "next_cursor": next_cursor}

    def get_topic(self, topic_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT
                id, channel_id, title, title_key, url, source_excerpt, cover_image_url, realtime_posts_json,
                tag, peak_tag, rank, best_rank, score, peak_score, source_id,
                occurrence_started_at, recurrence_window_hours,
                first_seen_at, last_seen_at, seen_count
            FROM topics
            WHERE id = ?
            """,
            (topic_id,),
        ).fetchone()
        if row is None:
            return None
        observations = self.conn.execute(
            """
            SELECT observed_at, source_id, rank, score, tag, url
            FROM topic_observations
            WHERE topic_id = ?
            ORDER BY observed_at DESC
            LIMIT 20
            """,
            (topic_id,),
        ).fetchall()
        topic = _topic_row_to_dict(row, self.get_ai_insight_record(topic_id))
        topic["observations"] = [dict(observation) for observation in observations]
        return topic

    def get_trends_summary(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) AS count FROM topics WHERE channel_id = ?", (WEIBO_CHANNEL_ID,)).fetchone()
        latest = self.conn.execute("SELECT MAX(last_seen_at) AS last_seen_at FROM topics").fetchone()
        tags = self.conn.execute(
            """
            SELECT peak_tag AS tag, COUNT(*) AS count
            FROM topics
            WHERE channel_id = ? AND peak_tag != ''
            GROUP BY peak_tag
            ORDER BY count DESC, tag ASC
            """,
            (WEIBO_CHANNEL_ID,),
        ).fetchall()
        latest_topics = self.list_topics(channel_id=WEIBO_CHANNEL_ID, limit=5)["items"]
        return {
            "channels": [{"id": WEIBO_CHANNEL_ID, "name": "微博热搜", "enabled": True}],
            "topic_count": int(total["count"] if total else 0),
            "last_seen_at": str(latest["last_seen_at"] or "") if latest else "",
            "tags": [{"tag": str(row["tag"]), "count": int(row["count"])} for row in tags],
            "latest_topics": latest_topics,
        }

    def get_integration_asset(self, provider: str, target_key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM integration_assets WHERE provider = ? AND target_key = ?",
            (provider, target_key),
        ).fetchone()
        return str(row["value"]) if row else None

    def set_integration_asset(self, provider: str, target_key: str, value: str) -> None:
        now = now_iso()
        asset_id = make_target_id(provider, target_key)
        self.conn.execute(
            """
            INSERT INTO integration_assets (id, provider, target_key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, target_key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (asset_id, provider, target_key, value, now),
        )
        self.conn.commit()
        logger.debug("外部集成素材缓存已更新: provider=%s target_key=%s", provider, target_key)

    def get_ai_insight_record(self, topic_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT
                topic_id, title, status, summary, takeaway, facts_json, commentary, risk_note,
                sources_json, confidence, error_message, model, prompt_version, api_mode,
                context_hash, failed_retry_context_hash, context_material_json,
                search_source_count, created_at, updated_at
            FROM ai_insights
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchone()
        if row is None:
            return None
        detail = None
        if row["status"] == "success":
            try:
                detail = AIDetail.from_raw(
                    {
                        "summary": row["summary"],
                        "takeaway": row["takeaway"],
                        "facts": json.loads(row["facts_json"]),
                        "commentary": row["commentary"],
                        "risk_note": sanitize_public_risk_note(str(row["risk_note"] or "")),
                        "sources": json.loads(row["sources_json"]),
                        "confidence": row["confidence"],
                    }
                )
            except (json.JSONDecodeError, ValueError):
                detail = None
        return {
            "topic_id": row["topic_id"],
            "title": row["title"],
            "status": row["status"],
            "detail": detail,
            "error_message": row["error_message"],
            "model": row["model"],
            "prompt_version": row["prompt_version"],
            "api_mode": row["api_mode"],
            "context_hash": row["context_hash"],
            "failed_retry_context_hash": row["failed_retry_context_hash"],
            "context_material": _parse_json_object(str(row["context_material_json"] or "{}")),
            "context_material_json": row["context_material_json"],
            "search_source_count": row["search_source_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_ai_insight_success(
        self,
        topic: TopicCandidate,
        detail: AIDetail,
        model: str,
        *,
        prompt_version: str = "",
        api_mode: str = "",
        context_hash: str = "",
        context_material_json: str = "{}",
        search_source_count: int = 0,
    ) -> None:
        now = now_iso()
        detail = replace(detail, risk_note=sanitize_public_risk_note(detail.risk_note))
        self.conn.execute(
            """
            INSERT INTO ai_insights
                (
                    topic_id, channel_id, title, status, summary, facts_json, commentary,
                    takeaway, risk_note, sources_json, confidence, error_message, model,
                    prompt_version, api_mode, context_hash, failed_retry_context_hash,
                    context_material_json, search_source_count, created_at, updated_at
                )
            VALUES
                (?, ?, ?, 'success', ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, '', ?, ?, ?, ?)
            ON CONFLICT(topic_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                title = excluded.title,
                status = excluded.status,
                summary = excluded.summary,
                takeaway = excluded.takeaway,
                facts_json = excluded.facts_json,
                commentary = excluded.commentary,
                risk_note = excluded.risk_note,
                sources_json = excluded.sources_json,
                confidence = excluded.confidence,
                error_message = excluded.error_message,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                api_mode = excluded.api_mode,
                context_hash = excluded.context_hash,
                failed_retry_context_hash = '',
                context_material_json = excluded.context_material_json,
                search_source_count = excluded.search_source_count,
                updated_at = excluded.updated_at
            """,
            (
                topic.id,
                topic.channel_id,
                topic.title,
                detail.summary,
                json.dumps(detail.facts, ensure_ascii=False),
                detail.commentary,
                detail.takeaway,
                detail.risk_note,
                json.dumps([source.to_dict() for source in detail.sources], ensure_ascii=False),
                detail.confidence,
                model,
                prompt_version,
                api_mode,
                context_hash,
                _normalize_json_object_text(context_material_json),
                search_source_count,
                now,
                now,
            ),
        )
        self.conn.commit()
        logger.info(
            "AI 洞察成功记录已保存: topic_id=%s title=%s model=%s api_mode=%s prompt_version=%s context_hash=%s sources=%s search_sources=%s",
            topic.id,
            topic.title,
            model or "未配置",
            api_mode or "-",
            prompt_version or "-",
            context_hash[:12] if context_hash else "-",
            len(detail.sources),
            search_source_count,
        )

    def save_ai_insight_failure(
        self,
        topic: TopicCandidate,
        error_message: str,
        model: str,
        *,
        prompt_version: str = "",
        api_mode: str = "",
        context_hash: str = "",
        failed_retry_context_hash: str = "",
        context_material_json: str = "{}",
        search_source_count: int = 0,
    ) -> None:
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO ai_insights
                (
                    topic_id, channel_id, title, status, summary, facts_json, commentary,
                    takeaway, risk_note, sources_json, confidence, error_message, model,
                    prompt_version, api_mode, context_hash, failed_retry_context_hash,
                    context_material_json, search_source_count, created_at, updated_at
                )
            VALUES
                (?, ?, ?, 'failed', '', '[]', '', '', '', '[]', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                title = excluded.title,
                status = excluded.status,
                summary = excluded.summary,
                takeaway = excluded.takeaway,
                facts_json = excluded.facts_json,
                commentary = excluded.commentary,
                risk_note = excluded.risk_note,
                sources_json = excluded.sources_json,
                confidence = excluded.confidence,
                error_message = excluded.error_message,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                api_mode = excluded.api_mode,
                context_hash = excluded.context_hash,
                failed_retry_context_hash = excluded.failed_retry_context_hash,
                context_material_json = excluded.context_material_json,
                search_source_count = excluded.search_source_count,
                updated_at = excluded.updated_at
            """,
            (
                topic.id,
                topic.channel_id,
                topic.title,
                error_message,
                model,
                prompt_version,
                api_mode,
                context_hash,
                failed_retry_context_hash,
                _normalize_json_object_text(context_material_json),
                search_source_count,
                now,
                now,
            ),
        )
        self.conn.commit()
        logger.info(
            "AI 洞察失败记录已保存: topic_id=%s title=%s model=%s api_mode=%s prompt_version=%s context_hash=%s error=%s",
            topic.id,
            topic.title,
            model or "未配置",
            api_mode or "-",
            prompt_version or "-",
            context_hash[:12] if context_hash else "-",
            error_message,
        )

    def update_ai_context_material(self, topic_id: str, context_material_json: str) -> None:
        self.conn.execute(
            """
            UPDATE ai_insights
            SET context_material_json = ?
            WHERE topic_id = ?
            """,
            (_normalize_json_object_text(context_material_json), topic_id),
        )
        self.conn.commit()

    def should_send_health_alert(self, target_key: str, cooldown_minutes: int) -> bool:
        if cooldown_minutes <= 0:
            return True
        last_value = self.get_integration_asset("system", target_key)
        if not last_value:
            return True
        try:
            last_sent = datetime.fromisoformat(last_value)
        except ValueError:
            return True
        return datetime.now().astimezone() - last_sent >= timedelta(minutes=cooldown_minutes)

    def mark_health_alert_sent(self, target_key: str) -> None:
        self.set_integration_asset("system", target_key, now_iso())


def make_target_id(provider: str, target: str) -> str:
    return sha1(f"{provider}:{target}".encode("utf-8")).hexdigest()


def _topic_params(topic: TopicCandidate) -> dict:
    source_excerpt_origin = topic.source_excerpt_origin
    if source_excerpt_origin not in {"official", "mobile"}:
        source_excerpt_origin = "mobile" if topic.source_excerpt else ""
    return {
        "id": topic.id,
        "channel_id": topic.channel_id,
        "title": topic.title,
        "title_key": topic.normalized_title_key,
        "url": topic.url,
        "source_excerpt": topic.source_excerpt,
        "cover_image_url": topic.cover_image_url,
        "realtime_posts_json": json.dumps(
            [post.to_dict() for post in topic.realtime_posts],
            ensure_ascii=False,
        ),
        "source_excerpt_origin": source_excerpt_origin,
        "tag": topic.tag,
        "peak_tag": topic.tag,
        "rank": topic.rank,
        "best_rank": topic.rank,
        "score": topic.score,
        "peak_score": topic.score,
        "source_id": topic.source_id,
        "fetched_at": topic.fetched_at,
        "occurrence_started_at": topic.occurrence_started_at or topic.fetched_at,
        "recurrence_window_hours": topic.recurrence_window_hours or DEFAULT_RECURRENCE_HOURS,
    }


def _recurrence_hours_for_tag(tag: str, tag_recurrence_hours: Mapping[str, int]) -> int:
    return int(tag_recurrence_hours.get(tag, DEFAULT_RECURRENCE_HOURS))


def _is_within_recurrence_window(fetched_at: str, last_seen_at: str, recurrence_window_hours: int) -> bool:
    fetched = _parse_datetime(fetched_at)
    last_seen = _parse_datetime(last_seen_at)
    if fetched is None or last_seen is None:
        return True
    try:
        return fetched - last_seen < timedelta(hours=recurrence_window_hours)
    except TypeError:
        return True


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _topic_url_priority(url: str) -> int:
    parsed = urlparse(url)
    if (
        parsed.scheme == "https"
        and parsed.netloc == "weibo.com"
        and parsed.path.startswith("/a/hot/")
        and not parsed.path.startswith("/a/hot/realtime/")
        and parsed.path.endswith(".html")
    ):
        return 3
    if parsed.scheme == "https" and parsed.netloc == "s.weibo.com" and parsed.path == "/weibo":
        return 2
    return 1 if url else 0


def _cursor_to_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(int(cursor), 0)
    except ValueError:
        return 0


def _topic_row_to_dict(row: sqlite3.Row, ai_record: dict | None) -> dict:
    detail = None
    ai_status = ""
    ai_error = ""
    if ai_record:
        ai_status = str(ai_record["status"])
        ai_error = str(ai_record["error_message"] or "")
        if ai_record["detail"] is not None:
            detail = ai_record["detail"].to_dict()
    realtime_posts = _parse_realtime_posts_json(str(row["realtime_posts_json"] or "[]"))
    return {
        "id": str(row["id"]),
        "channel_id": str(row["channel_id"]),
        "title": str(row["title"]),
        "title_key": str(row["title_key"]),
        "tag": str(row["tag"]),
        "peak_tag": str(row["peak_tag"]),
        "url": str(row["url"]),
        "mobile_url": weibo_mobile_search_url(str(row["title"])),
        "source_excerpt": str(row["source_excerpt"]),
        "cover_image_url": str(row["cover_image_url"]),
        "realtime_posts": [post.to_dict() for post in realtime_posts],
        "source_id": str(row["source_id"]),
        "occurrence_started_at": str(row["occurrence_started_at"]),
        "recurrence_window_hours": int(row["recurrence_window_hours"]),
        "first_seen_at": str(row["first_seen_at"]),
        "last_seen_at": str(row["last_seen_at"]),
        "rank": row["rank"],
        "best_rank": row["best_rank"],
        "score": row["score"],
        "peak_score": row["peak_score"],
        "seen_count": int(row["seen_count"]),
        "ai_status": ai_status,
        "ai_error": ai_error,
        "ai_detail": detail,
    }


def _parse_realtime_posts_json(value: str) -> list[WeiboRealtimePost]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [
        post
        for post in (WeiboRealtimePost.from_raw(item) for item in data)
        if post.text or post.author or post.url
    ]


def _parse_json_object(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_json_object_text(value: str) -> str:
    data = _parse_json_object(value)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
