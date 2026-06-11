from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests

from backend.app.domain.models import SourceResult, TopicCandidate, now_iso, weibo_search_url


class SourceError(RuntimeError):
    pass


class HotTopicSource(ABC):
    id: str
    url: str
    supports_tags: bool

    def __init__(self, session: requests.Session, timeout: int) -> None:
        self.session = session
        self.timeout = timeout

    def fetch(self) -> SourceResult:
        fetched_at = now_iso()
        try:
            response = self.session.get(
                self.url,
                timeout=self.timeout,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/132.0.0.0 Safari/537.36"
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceError(f"{self.id} 请求失败: {exc}") from exc

        topics = self.parse_payload(payload, fetched_at)
        return SourceResult(
            source_id=self.id,
            topics=topics,
            supports_tags=self.supports_tags,
            fetched_at=fetched_at,
        )

    @abstractmethod
    def parse_payload(self, payload: dict[str, Any], fetched_at: str) -> list[TopicCandidate]:
        raise NotImplementedError


class XkHotTopicSource(HotTopicSource):
    id = "xk"
    url = "https://api.xk.ee/hot/weibo.php?type=json"
    supports_tags = True

    def parse_payload(self, payload: dict[str, Any], fetched_at: str) -> list[TopicCandidate]:
        if payload.get("code") != 200:
            raise SourceError(f"{self.id} 返回异常: {payload.get('msg') or payload.get('message')}")
        raw_topics = payload.get("data")
        if not isinstance(raw_topics, list):
            raise SourceError(f"{self.id} 返回数据格式异常")

        topics: list[TopicCandidate] = []
        for index, raw in enumerate(raw_topics, start=1):
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            topics.append(
                TopicCandidate.from_raw(
                    title=raw.get("title"),
                    rank=index,
                    score=raw.get("hotnum"),
                    tag=raw.get("tag"),
                    url=weibo_search_url(str(raw.get("title") or "")),
                    source_id=self.id,
                    fetched_at=fetched_at,
                )
            )
        return topics


class XunjinluHotTopicSource(HotTopicSource):
    id = "xunjinlu"
    url = "https://api.xunjinlu.fun/api/rebang/weibo.php"
    supports_tags = True

    def parse_payload(self, payload: dict[str, Any], fetched_at: str) -> list[TopicCandidate]:
        if payload.get("code") != 200:
            raise SourceError(f"{self.id} 返回异常: {payload.get('message') or payload.get('msg')}")
        data = payload.get("data")
        raw_topics = data.get("list") if isinstance(data, dict) else None
        if not isinstance(raw_topics, list):
            raise SourceError(f"{self.id} 返回数据格式异常")

        topics: list[TopicCandidate] = []
        for index, raw in enumerate(raw_topics, start=1):
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            raw_rank = raw.get("rank")
            rank = raw_rank + 1 if isinstance(raw_rank, int) and raw_rank >= 0 else index
            topics.append(
                TopicCandidate.from_raw(
                    title=raw.get("title"),
                    rank=rank,
                    score=raw.get("hot" "_value"),
                    tag=raw.get("label"),
                    url=raw.get("url"),
                    source_id=self.id,
                    fetched_at=fetched_at,
                )
            )
        return topics


class XxApiHotTopicSource(HotTopicSource):
    id = "xxapi"
    url = "https://v2.xxapi.cn/api/weibohot"
    supports_tags = False

    def parse_payload(self, payload: dict[str, Any], fetched_at: str) -> list[TopicCandidate]:
        if payload.get("code") not in {200, "200"}:
            raise SourceError(f"{self.id} 返回异常: {payload.get('msg') or payload.get('message')}")
        return _parse_index_topics(payload.get("data"), self.id, fetched_at)


class NsuuuHotTopicSource(HotTopicSource):
    id = "nsuuu"
    url = "https://v1.nsuuu.com/api/weibohot"
    supports_tags = False

    def parse_payload(self, payload: dict[str, Any], fetched_at: str) -> list[TopicCandidate]:
        if payload.get("code") not in {200, "200"}:
            raise SourceError(f"{self.id} 返回异常: {payload.get('msg') or payload.get('message')}")
        return _parse_index_topics(payload.get("data"), self.id, fetched_at)


def build_weibo_sources(
    source_order: tuple[str, ...],
    session: requests.Session,
    timeout: int,
    *,
    weibo_official_timeout: int | None = None,
    weibo_official_visitor_timeout: int | None = None,
    weibo_official_realtime_timeout: int | None = None,
    weibo_official_max_retries: int = 2,
) -> list[HotTopicSource]:
    from backend.app.services.ingestion.weibo_official import WeiboOfficialHotTopicSource

    registry: dict[str, type[HotTopicSource]] = {
        "weibo_official": WeiboOfficialHotTopicSource,
        "xk": XkHotTopicSource,
        "xunjinlu": XunjinluHotTopicSource,
        "xxapi": XxApiHotTopicSource,
        "nsuuu": NsuuuHotTopicSource,
    }
    sources: list[HotTopicSource] = []
    for source_id in source_order:
        source_type = registry.get(source_id)
        if source_type is None:
            raise ValueError(f"未知数据源: {source_id}")
        if source_type is WeiboOfficialHotTopicSource:
            sources.append(
                source_type(
                    session,
                    weibo_official_timeout or timeout,
                    visitor_timeout=weibo_official_visitor_timeout or weibo_official_timeout or timeout,
                    realtime_timeout=weibo_official_realtime_timeout or weibo_official_timeout or timeout,
                    max_retries=weibo_official_max_retries,
                )
            )
        else:
            sources.append(source_type(session, timeout))
    return sources


def _parse_index_topics(raw_topics: Any, source_id: str, fetched_at: str) -> list[TopicCandidate]:
    if not isinstance(raw_topics, list):
        raise SourceError(f"{source_id} 返回数据格式异常")

    topics: list[TopicCandidate] = []
    for index, raw in enumerate(raw_topics, start=1):
        if not isinstance(raw, dict) or not raw.get("title"):
            continue
        topics.append(
            TopicCandidate.from_raw(
                title=raw.get("title"),
                rank=raw.get("index") or index,
                score=raw.get("hot"),
                tag="",
                url=raw.get("url"),
                source_id=source_id,
                fetched_at=fetched_at,
            )
        )
    return topics
