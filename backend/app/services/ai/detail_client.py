from __future__ import annotations

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
from backend.app.domain.models import AIDetail, TopicCandidate
from backend.app.services.ai.prompts import SYSTEM_PROMPT
from backend.app.services.ingestion.weibo_official import fetch_weibo_official_detail_context

logger = logging.getLogger(__name__)
PROTECTED_EXTRA_PAYLOAD_KEYS = {"model", "messages", "temperature", "web_search_options", "stream"}
TECHNICAL_RISK_TERMS = (
    "搜索工具",
    "实时搜索工具",
    "联网工具",
    "联网能力",
    "当前环境",
    "API",
    "api",
    "模型",
    "web_search",
    "web_search_options",
    "提示词",
)
GENERIC_RISK_NOTE = "相关信息仍需以当事方、权威媒体或平台后续公开说明为准，注意区分事实、观点和未经证实的传播内容。"


@dataclass(frozen=True)
class AIDetailResult:
    detail: AIDetail | None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.detail is not None


class AIDetailClient:
    def __init__(self, config: AIDetailConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def generate(self, topic: TopicCandidate) -> AIDetailResult:
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
        if self.config.api_mode != "chat_completions":
            logger.warning(
                "AI 调用跳过: topic_id=%s title=%s reason=unsupported_api_mode api_mode=%s",
                topic.id,
                topic.title,
                self.config.api_mode,
            )
            return AIDetailResult(None, f"不支持的 AI_DETAIL_API_MODE: {self.config.api_mode}")

        total_started = time.perf_counter()
        official_context = self._load_official_context(topic)
        logger.info(
            (
                "AI 调用准备完成: topic_id=%s title=%s model=%s api_mode=%s base_host=%s "
                "web_search_options=%s official_context_chars=%s max_retries=%s timeout_seconds=%s"
            ),
            topic.id,
            topic.title,
            self.config.model,
            self.config.api_mode,
            _base_host(self.config.base_url),
            self.config.web_search_options is not None,
            len(official_context),
            self.config.max_retries,
            self.config.timeout_seconds,
        )
        logger.info(
            "AI 请求配置摘要: topic_id=%s search_options_sent=%s extra_payload_keys=%s",
            topic.id,
            self.config.web_search_options is not None,
            ",".join(sorted(self.config.extra_payload.keys())) if self.config.extra_payload else "无",
        )
        last_error = ""
        for attempt in range(1, self.config.max_retries + 1):
            attempt_started = time.perf_counter()
            try:
                logger.info(
                    "AI 请求开始: topic_id=%s title=%s attempt=%s/%s model=%s",
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    self.config.model,
                )
                response = self.session.post(
                    f"{self.config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._build_payload(topic, official_context),
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                detail = sanitize_ai_detail(parse_chat_completion_detail(response.json()))
                logger.info(
                    (
                        "AI 请求成功: topic_id=%s title=%s attempt=%s/%s duration_ms=%.1f "
                        "total_duration_ms=%.1f sources=%s facts=%s confidence=%s takeaway=%s"
                    ),
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    (time.perf_counter() - attempt_started) * 1000,
                    (time.perf_counter() - total_started) * 1000,
                    len(detail.sources),
                    len(detail.facts),
                    detail.confidence or "-",
                    bool(detail.takeaway),
                )
                return AIDetailResult(detail)
            except Exception as exc:
                last_error = redact_sensitive_text(exc)
                logger.warning(
                    "AI 请求失败: topic_id=%s title=%s attempt=%s/%s duration_ms=%.1f error=%s",
                    topic.id,
                    topic.title,
                    attempt,
                    self.config.max_retries,
                    (time.perf_counter() - attempt_started) * 1000,
                    last_error,
                )
        logger.warning(
            "AI 调用最终失败: topic_id=%s title=%s attempts=%s total_duration_ms=%.1f last_error=%s",
            topic.id,
            topic.title,
            self.config.max_retries,
            (time.perf_counter() - total_started) * 1000,
            last_error or "AI 详情生成失败",
        )
        return AIDetailResult(None, last_error or "AI 详情生成失败")

    def _build_payload(self, topic: TopicCandidate, official_context: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(topic, official_context=official_context)},
            ],
            "temperature": self.config.temperature,
        }
        if self.config.web_search_options is not None:
            payload["web_search_options"] = self.config.web_search_options
        for key, value in self.config.extra_payload.items():
            if key in PROTECTED_EXTRA_PAYLOAD_KEYS:
                logger.warning("AI 额外 payload 字段被忽略: key=%s reason=protected", key)
                continue
            payload[key] = value
        return payload

    def _load_official_context(self, topic: TopicCandidate) -> str:
        if topic.source_excerpt:
            logger.info(
                "AI 复用已保存微博官方原始材料: topic_id=%s title=%s chars=%s",
                topic.id,
                topic.title,
                len(topic.source_excerpt),
            )
            return topic.source_excerpt
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
            return context
        except Exception as exc:
            logger.info(
                "AI 官方上下文加载失败，继续生成 AI 详情: topic_id=%s title=%s duration_ms=%.1f error=%s",
                topic.id,
                topic.title,
                (time.perf_counter() - started) * 1000,
                redact_sensitive_text(exc),
            )
            return ""


def build_user_prompt(topic: TopicCandidate, official_context: str = "") -> str:
    context = {
        "title": topic.title,
        "tag": topic.tag,
        "rank": topic.rank,
        "score": topic.score,
        "source_url": topic.url,
        "source_id": topic.source_id,
        "channel_id": topic.channel_id,
        "fetched_at": topic.fetched_at,
    }
    if topic.source_excerpt:
        context["weibo_source_excerpt"] = topic.source_excerpt
    if official_context:
        context["official_context"] = official_context
    return (
        "请联网搜索并分析下面这个热点。优先核验热点标题本身、主流媒体报道、原始搜索页相关信息。"
        "如果 official_context 非空，它来自微博官方公开详情页，请优先作为原热搜内容上下文，但仍需用搜索结果交叉核验。"
        "请按 system 指定 JSON schema 返回。\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def parse_chat_completion_detail(payload: dict[str, Any]) -> AIDetail:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI 响应缺少 choices[0].message.content") from exc
    if isinstance(content, list):
        content = "".join(str(part.get("text", part)) for part in content)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI 响应内容为空")

    data = json.loads(_extract_json_object(content))
    detail = AIDetail.from_raw(data)
    if not detail.summary:
        raise ValueError("AI 详情缺少 summary")
    return detail


def sanitize_ai_detail(detail: AIDetail) -> AIDetail:
    risk_note = detail.risk_note.strip()
    if not risk_note or any(term in risk_note for term in TECHNICAL_RISK_TERMS):
        risk_note = GENERIC_RISK_NOTE
    takeaway = detail.takeaway.strip() or _fallback_takeaway(detail)
    return AIDetail(
        summary=detail.summary,
        takeaway=takeaway,
        facts=detail.facts,
        commentary=detail.commentary,
        risk_note=risk_note,
        sources=detail.sources,
        confidence=detail.confidence,
    )


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
