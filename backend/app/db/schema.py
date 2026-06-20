SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    supports_tags INTEGER NOT NULL,
    last_checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    topic_count INTEGER NOT NULL,
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    topic_count INTEGER NOT NULL,
    supports_tags INTEGER NOT NULL,
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    url TEXT NOT NULL,
    source_excerpt TEXT NOT NULL DEFAULT '',
    source_excerpt_origin TEXT NOT NULL DEFAULT '',
    cover_image_url TEXT NOT NULL DEFAULT '',
    realtime_posts_json TEXT NOT NULL DEFAULT '[]',
    tag TEXT NOT NULL,
    peak_tag TEXT NOT NULL DEFAULT '',
    rank INTEGER,
    best_rank INTEGER,
    score INTEGER,
    peak_score INTEGER,
    source_id TEXT NOT NULL,
    occurrence_started_at TEXT NOT NULL,
    recurrence_window_hours INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE INDEX IF NOT EXISTS idx_topics_channel_last_seen
    ON topics(channel_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_topics_tag_last_seen
    ON topics(tag, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS topic_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_id TEXT NOT NULL,
    rank INTEGER,
    score INTEGER,
    tag TEXT NOT NULL,
    url TEXT NOT NULL,
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE INDEX IF NOT EXISTS idx_topic_observations_topic
    ON topic_observations(topic_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS ai_insights (
    topic_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    takeaway TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL,
    commentary TEXT NOT NULL,
    risk_note TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    error_message TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT '',
    api_mode TEXT NOT NULL DEFAULT '',
    context_hash TEXT NOT NULL DEFAULT '',
    failed_retry_context_hash TEXT NOT NULL DEFAULT '',
    search_source_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS notification_targets (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    target TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, target)
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    error_message TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(target_id) REFERENCES notification_targets(id),
    UNIQUE(topic_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_topic
    ON notification_deliveries(topic_id);

CREATE TABLE IF NOT EXISTS integration_assets (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    target_key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, target_key)
);
"""
