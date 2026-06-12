from __future__ import annotations

from backend.app.domain.models import TopicCandidate

TAG_TITLE_PREFIX = {
    "爆": "💥【爆】",
    "沸": "⚡【沸】",
    "热": "🔥【热】",
}

SOURCE_LABELS = {
    "weibo_official": "微博官方热搜",
    "xk": "微博热搜",
    "xunjinlu": "微博热搜",
    "xxapi": "微博热搜",
    "nsuuu": "微博热搜",
}

USER_VISIBLE_AI_ERROR = "洞察生成中，可先查看微博来源。"


def notification_title(topic: TopicCandidate) -> str:
    prefix = TAG_TITLE_PREFIX.get(topic.tag, f"【{topic.tag}】" if topic.tag else "")
    return f"{prefix}{topic.title}" if prefix else topic.title


def notification_source_label(source_id: str) -> str:
    return SOURCE_LABELS.get(source_id, "热点来源")


def notification_meta_line(topic: TopicCandidate, score_text: str) -> str:
    rank = f"#{topic.rank}" if topic.rank is not None else "-"
    return f"{notification_source_label(topic.source_id)} · 排名 {rank} · 热度 {score_text}"


def confidence_label(value: str) -> str:
    if value == "high":
        return "高"
    if value == "medium":
        return "中"
    if value == "low":
        return "低"
    return value or "未标注"


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def user_visible_ai_error(_error: str = "") -> str:
    return USER_VISIBLE_AI_ERROR
