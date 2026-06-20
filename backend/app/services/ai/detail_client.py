from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from backend.app.core.config import AIDetailConfig
from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import AIDetail, AIDetailSource, TopicCandidate, WeiboRealtimePost, weibo_mobile_search_url
from backend.app.services.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from backend.app.services.ai.sanitizer import sanitize_public_risk_note
from backend.app.services.ingestion.weibo_official import fetch_weibo_official_detail_context

logger = logging.getLogger(__name__)
PROTECTED_EXTRA_PAYLOAD_KEYS = {
    "model",
    "messages",
    "instructions",
    "input",
    "temperature",
    "web_search_options",
    "tools",
    "tool_choice",
    "include",
    "stream",
}
@dataclass(frozen=True)
class AIContext:
    official_context: str
    context_hash: str
    mobile_context: str = ""
    realtime_posts: tuple[WeiboRealtimePost, ...] = ()
    combined_context: str = ""


@dataclass(frozen=True)
class ParsedAIDetail:
    detail: AIDetail
    search_call_count: int = 0
    search_source_count: int = 0
    json_source_count: int = 0


@dataclass(frozen=True)
class AIDetailResult:
    detail: AIDetail | None
    error_message: str = ""
    context_hash: str = ""
    search_call_count: int = 0
    search_source_count: int = 0
    json_source_count: int = 0

    @property
    def ok(self) -> bool:
        return self.detail is not None


class AIDetailClient:
    def __init__(self, config: AIDetailConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def prepare_context(self, topic: TopicCandidate) -> AIContext:
        official_context, mobile_context, realtime_posts = self._load_weibo_context(topic)
        return AIContext(
            official_context=official_context,
            mobile_context=mobile_context,
            realtime_posts=realtime_posts,
            combined_context=combine_weibo_context(official_context, mobile_context, realtime_posts),
            context_hash=build_context_hash(
                topic,
                official_context,
                has_mobile_context=bool(mobile_context or realtime_posts),
            ),
        )

    def generate(self, topic: TopicCandidate, context: AIContext | None = None) -> AIDetailResult:
        if not self.config.enabled:
            logger.info("AI 调用跳过: topic_id=%s title=%s reason=disabled", topic.id, topic.title)
            return AIDetailResult(None, "AI 详情未启用")
        if not self.config.available:
            logger.warning(
                "AI 调用跳过: topic_id=%s title=%s reason=incomplete_config base_url_configured=%s model_configured=%s api_key_configured=%s",
                topic.id,
                topic.title,
                bool(self.config.base_url),
                bool(self.config.model),
                bool(self.config.api_key),
            )
            return AIDetailResult(None, "AI 详情未配置完整")
        if self.config.api_mode not in {"responses", "chat_completions"}:
            logger.warning(
                "AI 调用跳过: topic_id=%s title=%s reason=unsupported_api_mode api_mode=%s",
                topic.id,
                topic.title,
                self.config.api_mode,
            )
            return AIDetailResult(None, f"不支持的 AI_DETAIL_API_MODE: {self.config.api_mode}")

        total_started = time.perf_counter()
        ai_context = context or self.prepare_context(topic)
        logger.info(
            (
                "AI 调用准备完成: topic_id=%s title=%s model=%s api_mode=%s base_host=%s "
                "prompt_version=%s context_hash=%s official_chars=%s mobile_chars=%s posts=%s max_retries=%s timeout_seconds=%s"
            ),
            topic.id,
            topic.title,
            self.config.model,
            self.config.api_mode,
            _base_host(self.config.base_url),
            PROMPT_VERSION,
            ai_context.context_hash[:12],
            len(ai_context.official_context),
            len(ai_context.mobile_context),
            len(ai_context.realtime_posts),
            self.config.max_retries,
            self.config.timeout_seconds,
        )
        if self.config.api_mode == "chat_completions" and self.config.external_search != "off":
            logger.warning(
                "AI Chat Completions 搜索不保证触发: topic_id=%s model=%s suggestion=gpt-5-search-api_or_responses",
                topic.id,
                self.config.model,
            )
        logger.info(
            "AI 请求配置摘要: topic_id=%s api_mode=%s tool_choice=%s search_options_sent=%s extra_payload_keys=%s",
            topic.id,
            self.config.api_mode,
            self._tool_choice_label(),
            self.config.api_mode == "chat_completions" and self.config.external_search != "off",
            ",".join(sorted(self.config.extra_payload.keys())) if self.config.extra_payload else "无",
        )

        last_error = ""
        for attempt in range(1, self.config.max_retries + 1):
            attempt_started = time.perf_counter()
            try:
                logger.info(
                    "AI 请求开始: topic_id=%s title=%s attempt=%s/%s model=%s api_mode=%s",
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    self.config.model,
                    self.config.api_mode,
                )
                response = self.session.post(
                    self._request_url(),
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._build_payload(topic, ai_context),
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                parsed = self._parse_response(response.json(), ai_context)
                logger.info(
                    (
                        "AI 请求成功: topic_id=%s title=%s attempt=%s/%s duration_ms=%.1f "
                        "total_duration_ms=%.1f api_mode=%s search_calls=%s search_sources=%s "
                        "json_sources=%s final_sources=%s facts=%s confidence=%s takeaway=%s"
                    ),
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    (time.perf_counter() - attempt_started) * 1000,
                    (time.perf_counter() - total_started) * 1000,
                    self.config.api_mode,
                    parsed.search_call_count,
                    parsed.search_source_count,
                    parsed.json_source_count,
                    len(parsed.detail.sources),
                    len(parsed.detail.facts),
                    parsed.detail.confidence or "-",
                    bool(parsed.detail.takeaway),
                )
                return AIDetailResult(
                    parsed.detail,
                    context_hash=ai_context.context_hash,
                    search_call_count=parsed.search_call_count,
                    search_source_count=parsed.search_source_count,
                    json_source_count=parsed.json_source_count,
                )
            except Exception as exc:
                last_error = redact_sensitive_text(exc)
                logger.warning(
                    "AI 请求失败: topic_id=%s title=%s attempt=%s/%s api_mode=%s duration_ms=%.1f error=%s",
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    self.config.api_mode,
                    (time.perf_counter() - attempt_started) * 1000,
                    last_error,
                )
        logger.warning(
            "AI 调用最终失败: topic_id=%s title=%s api_mode=%s attempts=%s total_duration_ms=%.1f last_error=%s",
            topic.id,
            topic.title,
            self.config.api_mode,
            self.config.max_retries,
            (time.perf_counter() - total_started) * 1000,
            last_error or "AI 详情生成失败",
        )
        return AIDetailResult(None, last_error or "AI 详情生成失败", context_hash=ai_context.context_hash)

    def _request_url(self) -> str:
        if self.config.api_mode == "responses":
            return f"{self.config.base_url}/responses"
        return f"{self.config.base_url}/chat/completions"

    def _build_payload(self, topic: TopicCandidate, context: AIContext) -> dict[str, Any]:
        if self.config.api_mode == "responses":
            payload: dict[str, Any] = {
                "model": self.config.model,
                "instructions": SYSTEM_PROMPT,
                "input": build_user_prompt(topic, context=context),
                "temperature": self.config.temperature,
            }
            if self.config.external_search in {"optional", "required"}:
                payload["tools"] = [{"type": "web_search"}]
                payload["include"] = ["web_search_call.action.sources"]
            if self.config.external_search == "required":
                payload["tool_choice"] = "required"
        else:
            payload = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(topic, context=context)},
                ],
                "temperature": self.config.temperature,
            }
            if self.config.external_search in {"optional", "required"}:
                payload["web_search_options"] = self.config.web_search_options or {}
                if self.config.external_search == "required":
                    logger.warning(
                        "AI Chat Completions 模式无法强制搜索: topic_id=%s model=%s",
                        topic.id,
                        self.config.model,
                    )

        for key, value in self.config.extra_payload.items():
            if key in PROTECTED_EXTRA_PAYLOAD_KEYS:
                logger.warning("AI 额外 payload 字段被忽略: key=%s reason=protected", key)
                continue
            payload[key] = value
        return payload

    def _parse_response(self, payload: dict[str, Any], context: AIContext) -> ParsedAIDetail:
        if self.config.api_mode == "responses":
            parsed = parse_responses_detail(payload)
        else:
            parsed = parse_chat_completion_result(payload)
        detail = sanitize_ai_detail(
            parsed.detail,
            has_official_context=bool(context.official_context),
            has_weibo_context=bool(context.combined_context),
            search_source_count=parsed.search_source_count,
        )
        return ParsedAIDetail(
            detail=detail,
            search_call_count=parsed.search_call_count,
            search_source_count=parsed.search_source_count,
            json_source_count=parsed.json_source_count,
        )

    def _load_weibo_context(self, topic: TopicCandidate) -> tuple[str, str, tuple[WeiboRealtimePost, ...]]:
        official_context = topic.official_context
        mobile_context = topic.mobile_context
        if not official_context and not mobile_context and topic.source_excerpt:
            if topic.source_excerpt_origin == "official":
                official_context = topic.source_excerpt
            else:
                mobile_context = topic.source_excerpt
        if official_context or mobile_context:
            logger.info(
                "AI 复用已保存微博原始材料: topic_id=%s title=%s official_chars=%s mobile_chars=%s posts=%s",
                topic.id,
                topic.title,
                len(official_context),
                len(mobile_context),
                len(topic.realtime_posts),
            )
            return official_context, mobile_context, topic.realtime_posts
        timeout = max(1, min(self.config.timeout_seconds, 15))
        started = time.perf_counter()
        try:
            context = fetch_weibo_official_detail_context(self.session, topic.url, timeout)
            logger.info(
                "AI 官方上下文加载完成: topic_id=%s title=%s chars=%s duration_ms=%.1f",
                topic.id,
                topic.title,
                len(context),
                (time.perf_counter() - started) * 1000,
            )
            return context, "", topic.realtime_posts
        except Exception as exc:
            logger.info(
                "AI 官方上下文加载失败，继续生成 AI 详情: topic_id=%s title=%s duration_ms=%.1f error=%s",
                topic.id,
                topic.title,
                (time.perf_counter() - started) * 1000,
                redact_sensitive_text(exc),
            )
            return "", "", topic.realtime_posts

    def _tool_choice_label(self) -> str:
        if self.config.api_mode != "responses" or self.config.external_search == "off":
            return "-"
        return "required" if self.config.external_search == "required" else "auto"


def build_user_prompt(topic: TopicCandidate, official_context: str = "", context: AIContext | None = None) -> str:
    ai_context = context
    if ai_context is None:
        ai_context = AIContext(
            official_context=official_context,
            context_hash=build_context_hash(topic, official_context),
            combined_context=official_context,
        )
    payload_context = {
        "title": topic.title,
        "tag": topic.tag,
        "rank": topic.rank,
        "score": topic.score,
        "source_url": topic.url,
        "mobile_url": weibo_mobile_search_url(topic.title),
        "source_id": topic.source_id,
        "channel_id": topic.channel_id,
        "fetched_at": topic.fetched_at,
    }
    if topic.source_excerpt:
        payload_context["weibo_source_excerpt"] = topic.source_excerpt
    payload_context["weibo_context"] = {
        "official_context": ai_context.official_context,
        "mobile_context": ai_context.mobile_context,
        "combined": ai_context.combined_context,
        "realtime_posts": [post.to_dict() for post in ai_context.realtime_posts],
    }
    return (
        "请优先阅读 weibo_context 内的微博材料：官方公开详情页优先级最高，"
        "微博移动端热搜词页和实时帖子用于补充当前讨论现场。"
        "外部搜索结果只能辅助核验，不得覆盖微博实时材料。无法确认时明确写未能确认。"
        "输出给用户时严禁出现 JSON key、字段名或上下文变量名，例如 weibo_context、official_context、"
        "mobile_context、realtime_posts、combined、source_excerpt、context_hash；"
        "请改写成“微博官方详情”“微博移动端讨论”“实时帖子”等自然中文。"
        "请按 system 指定 JSON schema 返回。\n"
        + json.dumps(payload_context, ensure_ascii=False, indent=2)
    )


def combine_weibo_context(
    official_context: str = "",
    mobile_context: str = "",
    realtime_posts: tuple[WeiboRealtimePost, ...] | list[WeiboRealtimePost] = (),
) -> str:
    if official_context.strip():
        return official_context.strip()
    if mobile_context.strip():
        return mobile_context.strip()
    parts: list[str] = []
    for post in realtime_posts:
        prefix = f"{post.author}：" if post.author else ""
        value = f"{prefix}{post.text}".strip()
        if value:
            parts.append(value)
    return "\n\n".join(parts[:5])


def build_context_hash(
    topic: TopicCandidate,
    official_context: str = "",
    *,
    has_mobile_context: bool = False,
) -> str:
    payload = {
        "title": topic.title,
        "official_context": official_context,
        "has_mobile_context": has_mobile_context,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_chat_completion_result(payload: dict[str, Any]) -> ParsedAIDetail:
    try:
        message = payload["choices"][0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 响应缺少 choices[0].message.content") from exc
    text = _content_to_text(content)
    if not text.strip():
        raise ValueError("AI 响应内容为空")

    detail = _detail_from_text(text)
    annotation_sources = _extract_annotation_sources(message)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                annotation_sources.extend(_extract_annotation_sources(item))
        annotation_sources = _dedupe_sources(annotation_sources)
    merged_detail = merge_sources(detail, annotation_sources)
    return ParsedAIDetail(
        detail=merged_detail,
        search_call_count=0,
        search_source_count=len(annotation_sources),
        json_source_count=len(detail.sources),
    )


def parse_chat_completion_detail(payload: dict[str, Any]) -> AIDetail:
    return parse_chat_completion_result(payload).detail


def parse_responses_detail(payload: dict[str, Any]) -> ParsedAIDetail:
    text = _extract_responses_text(payload)
    if not text.strip():
        raise ValueError("AI 响应内容为空")
    detail = _detail_from_text(text)
    search_sources, search_call_count = _extract_responses_sources(payload)
    merged_detail = merge_sources(detail, search_sources)
    return ParsedAIDetail(
        detail=merged_detail,
        search_call_count=search_call_count,
        search_source_count=len(search_sources),
        json_source_count=len(detail.sources),
    )


def sanitize_ai_detail(
    detail: AIDetail,
    *,
    has_official_context: bool = False,
    has_weibo_context: bool = False,
    search_source_count: int = 0,
) -> AIDetail:
    risk_note = sanitize_public_risk_note(detail.risk_note)
    takeaway = detail.takeaway.strip() or _fallback_takeaway(detail)
    confidence = normalize_confidence(
        detail.confidence,
        detail.sources,
        has_official_context=has_official_context,
        has_weibo_context=has_weibo_context,
        search_source_count=search_source_count,
    )
    return AIDetail(
        summary=detail.summary,
        takeaway=takeaway,
        facts=detail.facts,
        commentary=detail.commentary,
        risk_note=risk_note,
        sources=detail.sources,
        confidence=confidence,
    )


def normalize_confidence(
    value: str,
    sources: list[AIDetailSource],
    *,
    has_official_context: bool = False,
    has_weibo_context: bool = False,
    search_source_count: int = 0,
) -> str:
    raw = value.strip().lower()
    if raw not in {"high", "medium", "low"}:
        raw = "low"
    reliable_count = sum(1 for source in sources if _is_reliable_source_url(source.url))
    if raw == "high":
        return (
            "high"
            if reliable_count >= 2
            else "medium"
            if reliable_count >= 1 or has_official_context or has_weibo_context
            else "low"
        )
    if reliable_count >= 1 or has_official_context or has_weibo_context or search_source_count >= 1:
        return "medium" if raw == "low" else raw
    return "low"


def merge_sources(detail: AIDetail, extra_sources: list[AIDetailSource]) -> AIDetail:
    seen: set[str] = set()
    merged: list[AIDetailSource] = []
    for source in [*detail.sources, *extra_sources]:
        key = (source.url or source.title).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return AIDetail(
        summary=detail.summary,
        takeaway=detail.takeaway,
        facts=detail.facts,
        commentary=detail.commentary,
        risk_note=detail.risk_note,
        sources=merged,
        confidence=detail.confidence,
    )


def _detail_from_text(text: str) -> AIDetail:
    data = json.loads(_extract_json_object(text))
    detail = AIDetail.from_raw(data)
    if not detail.summary:
        raise ValueError("AI 详情缺少 summary")
    return detail


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def _extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    parts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                parts.append(item["text"])
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text") or content_item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
    return "".join(parts)


def _extract_responses_sources(payload: dict[str, Any]) -> tuple[list[AIDetailSource], int]:
    sources: list[AIDetailSource] = []
    search_call_count = 0
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "web_search_call":
                search_call_count += 1
                sources.extend(_extract_sources_from_search_call(item))
            sources.extend(_extract_annotation_sources(item))
            content = item.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if isinstance(content_item, dict):
                        sources.extend(_extract_annotation_sources(content_item))
    return _dedupe_sources(sources), search_call_count


def _extract_sources_from_search_call(item: dict[str, Any]) -> list[AIDetailSource]:
    action = item.get("action")
    if not isinstance(action, dict):
        return []
    values = action.get("sources") or action.get("results") or []
    if not isinstance(values, list):
        return []
    return _dedupe_sources([_source_from_raw(value) for value in values])


def _extract_annotation_sources(item: dict[str, Any]) -> list[AIDetailSource]:
    annotations = item.get("annotations")
    if not isinstance(annotations, list):
        return []
    sources: list[AIDetailSource] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        sources.append(_source_from_raw(annotation))
    return _dedupe_sources(sources)


def _source_from_raw(value: Any) -> AIDetailSource:
    if not isinstance(value, dict):
        return AIDetailSource(title="", url="")
    return AIDetailSource(
        title=str(value.get("title") or value.get("source_title") or value.get("name") or "").strip(),
        url=str(value.get("url") or value.get("source_url") or value.get("link") or "").strip(),
    )


def _dedupe_sources(sources: list[AIDetailSource]) -> list[AIDetailSource]:
    seen: set[str] = set()
    result: list[AIDetailSource] = []
    for source in sources:
        key = (source.url or source.title).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _is_reliable_source_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if not host:
        return False
    if host in {"s.weibo.com", "m.weibo.cn"}:
        return False
    if host == "weibo.com" and path.startswith("/a/hot/"):
        return False
    return True


def _fallback_takeaway(detail: AIDetail) -> str:
    for value in (detail.commentary, detail.summary):
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            return value[:45]
    return "该热点仍需结合更多来源持续观察。"


def _extract_json_object(content: str) -> str:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI 响应不是 JSON 对象")
    return text[start : end + 1]


def _base_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    return parsed.netloc or parsed.path or "未配置"
