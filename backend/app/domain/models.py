from __future__ import annotations

import re
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Any
from urllib.parse import quote

from backend.app.core.timezone import now_iso as _now_iso


WEIBO_CHANNEL_ID = "weibo"


def now_iso() -> str:
    return _now_iso()


def normalize_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip()


def make_topic_id(channel_id: str, title_key: str, occurrence_started_at: str = "") -> str:
    normalized_title = normalize_title_key(title_key)
    normalized = f"{channel_id}:{normalized_title}:{occurrence_started_at.strip()}"
    return sha1(normalized.encode("utf-8")).hexdigest()


def weibo_search_url(title: str) -> str:
    return f"https://s.weibo.com/weibo?q={quote(title)}"


def weibo_mobile_search_url(title: str) -> str:
    clean_title = _strip_hashtag(str(title or "").strip())
    container_id = f"100103type=1&q={clean_title}"
    return f"https://m.weibo.cn/search?containerid={quote(container_id, safe='')}"


def topic_detail_url(public_site_url: str, topic_id: str) -> str:
    if not public_site_url:
        return ""
    return f"{public_site_url.rstrip('/')}/topics/{quote(topic_id)}"


@dataclass(frozen=True)
class WeiboRealtimePost:
    author: str
    created_at: str
    text: str
    reposts: int | None = None
    comments: int | None = None
    attitudes: int | None = None
    url: str = ""

    @classmethod
    def from_raw(cls, data: Any) -> "WeiboRealtimePost":
        if not isinstance(data, dict):
            return cls(author="", created_at="", text="")
        return cls(
            author=str(data.get("author") or "").strip(),
            created_at=str(data.get("created_at") or "").strip(),
            text=str(data.get("text") or "").strip(),
            reposts=_to_int(data.get("reposts")),
            comments=_to_int(data.get("comments")),
            attitudes=_to_int(data.get("attitudes")),
            url=str(data.get("url") or "").strip(),
        )

    def to_dict(self) -> dict:
        return {
            "author": self.author,
            "created_at": self.created_at,
            "text": self.text,
            "reposts": self.reposts,
            "comments": self.comments,
            "attitudes": self.attitudes,
            "url": self.url,
        }


@dataclass(frozen=True)
class TopicCandidate:
    title: str
    rank: int | None
    score: int | None
    tag: str
    url: str
    source_id: str
    fetched_at: str
    channel_id: str = WEIBO_CHANNEL_ID
    topic_id: str = ""
    title_key: str = ""
    occurrence_started_at: str = ""
    recurrence_window_hours: int | None = None
    source_excerpt: str = ""
    cover_image_url: str = ""
    realtime_posts: tuple[WeiboRealtimePost, ...] = ()
    source_excerpt_origin: str = ""
    official_context: str = ""
    mobile_context: str = ""

    @property
    def id(self) -> str:
        if self.topic_id:
            return self.topic_id
        return make_topic_id(self.channel_id, self.normalized_title_key, self.occurrence_started_at or self.fetched_at)

    @property
    def normalized_title_key(self) -> str:
        return self.title_key or normalize_title_key(self.title)

    def with_occurrence(
        self,
        *,
        topic_id: str,
        title_key: str,
        occurrence_started_at: str,
        recurrence_window_hours: int,
    ) -> "TopicCandidate":
        return replace(
            self,
            topic_id=topic_id,
            title_key=title_key,
            occurrence_started_at=occurrence_started_at,
            recurrence_window_hours=recurrence_window_hours,
        )

    def with_source_material(
        self,
        *,
        source_excerpt: str = "",
        cover_image_url: str = "",
        realtime_posts: tuple[WeiboRealtimePost, ...] | list[WeiboRealtimePost] = (),
        source_excerpt_origin: str = "",
        official_context: str = "",
        mobile_context: str = "",
    ) -> "TopicCandidate":
        return replace(
            self,
            source_excerpt=source_excerpt.strip(),
            cover_image_url=cover_image_url.strip(),
            realtime_posts=tuple(realtime_posts),
            source_excerpt_origin=source_excerpt_origin.strip(),
            official_context=official_context.strip(),
            mobile_context=mobile_context.strip(),
        )

    @classmethod
    def from_raw(
        cls,
        *,
        title: Any,
        rank: Any,
        score: Any,
        tag: Any,
        url: Any,
        source_id: str,
        fetched_at: str,
        channel_id: str = WEIBO_CHANNEL_ID,
        source_excerpt: Any = "",
        cover_image_url: Any = "",
        realtime_posts: Any = (),
    ) -> "TopicCandidate":
        clean_title = str(title or "").strip()
        fallback_url = weibo_search_url(clean_title) if channel_id == WEIBO_CHANNEL_ID else ""
        posts = tuple(
            post
            for post in (WeiboRealtimePost.from_raw(item) for item in realtime_posts)
            if post.text or post.author or post.url
        ) if isinstance(realtime_posts, list) else ()
        return cls(
            title=clean_title,
            rank=_to_int(rank),
            score=_to_int(score),
            tag=str(tag or "").strip(),
            url=str(url or "").strip() or fallback_url,
            source_id=source_id,
            fetched_at=fetched_at,
            channel_id=channel_id,
            source_excerpt=str(source_excerpt or "").strip(),
            cover_image_url=str(cover_image_url or "").strip(),
            realtime_posts=posts,
        )


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    topics: list[TopicCandidate]
    supports_tags: bool
    fetched_at: str


@dataclass(frozen=True)
class AIDetailSource:
    title: str
    url: str

    @classmethod
    def from_raw(cls, data: Any) -> "AIDetailSource":
        if not isinstance(data, dict):
            return cls(title="", url="")
        return cls(title=str(data.get("title") or "").strip(), url=str(data.get("url") or "").strip())

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url}


@dataclass(frozen=True)
class AIDetail:
    summary: str
    takeaway: str
    facts: list[str]
    commentary: str
    risk_note: str
    sources: list[AIDetailSource]
    confidence: str

    @classmethod
    def from_raw(cls, data: Any) -> "AIDetail":
        if not isinstance(data, dict):
            raise ValueError("AI detail must be a JSON object")
        return cls(
            summary=str(data.get("summary") or "").strip(),
            takeaway=str(data.get("takeaway") or "").strip(),
            facts=[str(item).strip() for item in data.get("facts", []) if str(item).strip()]
            if isinstance(data.get("facts"), list)
            else [],
            commentary=str(data.get("commentary") or "").strip(),
            risk_note=str(data.get("risk_note") or "").strip(),
            sources=[
                source
                for source in (AIDetailSource.from_raw(item) for item in data.get("sources", []))
                if source.title or source.url
            ]
            if isinstance(data.get("sources"), list)
            else [],
            confidence=str(data.get("confidence") or "").strip(),
        )

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "takeaway": self.takeaway,
            "facts": self.facts,
            "commentary": self.commentary,
            "risk_note": self.risk_note,
            "sources": [source.to_dict() for source in self.sources],
            "confidence": self.confidence,
        }


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    if text.endswith("万"):
        try:
            return int(float(text[:-1]) * 10000)
        except ValueError:
            return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _strip_hashtag(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > 2 and normalized.startswith("#") and normalized.endswith("#"):
        return normalized[1:-1].strip()
    return normalized
