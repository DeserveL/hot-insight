from __future__ import annotations

from backend.app.domain.models import TopicCandidate

TAG_TITLE_PREFIX = {
    "爆": "💥【爆】",
    "沸": "⚡【沸】",
    "热": "🔥【热】",
}

USER_VISIBLE_AI_ERROR = "洞察暂未生成，已保留微博来源链接。"


def notification_title(topic: TopicCandidate) -> str:
    prefix = TAG_TITLE_PREFIX.get(topic.tag, f"【{topic.tag}】" if topic.tag else "")
    return f"{prefix}{topic.title}" if prefix else topic.title


def user_visible_ai_error(_error: str = "") -> str:
    return USER_VISIBLE_AI_ERROR
