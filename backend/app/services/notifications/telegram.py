from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from hashlib import sha1
from typing import Protocol
from urllib.parse import urlparse

import requests

from backend.app.core.config import TelegramConfig
from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import AIDetail, TopicCandidate, now_iso
from backend.app.services.notifications.renderers import (
    compact_text,
    confidence_label,
    notification_meta_line,
    notification_title,
    user_visible_ai_error,
)
from backend.app.services.notifications.wecom import format_score

logger = logging.getLogger(__name__)

TELEGRAM_CAPTION_LIMIT = 1024


class AssetStore(Protocol):
    def get_integration_asset(self, provider: str, target_key: str) -> str | None:
        raise NotImplementedError

    def set_integration_asset(self, provider: str, target_key: str, value: str) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    error_message: str = ""
    external_message_id: str = ""
    media_file_id: str = ""


class TelegramNotifier:
    provider = "telegram"

    def __init__(
        self,
        config: TelegramConfig,
        session: requests.Session | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.asset_store = asset_store

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def target(self) -> str:
        return self.config.chat_id

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ) -> TelegramSendResult:
        if not self.enabled:
            return TelegramSendResult(False, "Telegram 未配置")

        caption = render_telegram_caption(topic, ai_detail, ai_error)
        reply_markup = build_reply_markup(detail_url or topic.url, topic.url)
        if not topic.cover_image_url:
            return self._send_message(caption, reply_markup)

        cached_file_id = self._get_cached_file_id(topic.cover_image_url)

        if cached_file_id:
            result = self._send_photo_by_file_id(cached_file_id, caption, reply_markup)
            if result.ok:
                logger.info(
                    "Telegram 使用缓存封面发送成功: topic_id=%s title=%s message_id=%s",
                    topic.id,
                    topic.title,
                    result.external_message_id or "-",
                )
                return result
            if not _is_file_id_invalid(result.error_message):
                return result
            logger.warning("Telegram 封面 file_id 失效，改用官方封面 URL 发送: topic_id=%s", topic.id)

        result = self._send_photo_by_url(topic.cover_image_url, caption, reply_markup)
        if result.ok and result.media_file_id and self.asset_store is not None:
            self.asset_store.set_integration_asset("telegram", file_cache_key(topic.cover_image_url), result.media_file_id)
        return result

    def send_health_alert(self, message: str) -> TelegramSendResult:
        if not self.enabled:
            return TelegramSendResult(False, "Telegram 未配置")
        text = f"<b>热点洞察通知异常</b>\n\n时间：{html.escape(now_iso())}\n{html.escape(message)}"
        payload = {
            "chat_id": self.config.chat_id,
            "text": _truncate(text, 4096),
            "parse_mode": self.config.parse_mode,
            "disable_web_page_preview": True,
        }
        return self._post_json("sendMessage", payload)

    def _send_photo_by_file_id(
        self,
        file_id: str,
        caption: str,
        reply_markup: dict,
    ) -> TelegramSendResult:
        payload = {
            "chat_id": self.config.chat_id,
            "photo": file_id,
            "caption": caption,
            "parse_mode": self.config.parse_mode,
            "reply_markup": reply_markup,
        }
        return self._post_json("sendPhoto", payload)

    def _send_photo_by_url(self, image_url: str, caption: str, reply_markup: dict) -> TelegramSendResult:
        payload = {
            "chat_id": self.config.chat_id,
            "photo": image_url,
            "caption": caption,
            "parse_mode": self.config.parse_mode,
            "reply_markup": reply_markup,
        }
        return self._post_json("sendPhoto", payload)

    def _send_message(self, text: str, reply_markup: dict) -> TelegramSendResult:
        payload = {
            "chat_id": self.config.chat_id,
            "text": _truncate(text, 4096),
            "parse_mode": self.config.parse_mode,
            "disable_web_page_preview": False,
            "reply_markup": reply_markup,
        }
        return self._post_json("sendMessage", payload)

    def _post_json(self, method: str, payload: dict) -> TelegramSendResult:
        last_error = ""
        for _attempt in range(self.config.max_retries):
            try:
                response = self.session.post(
                    self._method_url(method),
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
                if not _is_http_success(response):
                    last_error = _extract_telegram_error(response, f"Telegram {method} HTTP 请求失败")
                    logger.warning("Telegram %s 返回失败: %s", method, redact_sensitive_text(last_error))
                    continue
                result = _parse_telegram_response(response.json())
                if result.ok or _is_file_id_invalid(result.error_message):
                    return result
                last_error = redact_sensitive_text(result.error_message)
                logger.warning("Telegram %s 返回失败: %s", method, redact_sensitive_text(result.error_message))
            except Exception as exc:
                last_error = redact_sensitive_text(exc)
                logger.warning("Telegram %s 请求失败: %s", method, redact_sensitive_text(exc))
        return TelegramSendResult(False, last_error or "Telegram 请求失败")

    def _method_url(self, method: str) -> str:
        return f"{self.config.api_base_url}/bot{self.config.bot_token}/{method}"

    def _get_cached_file_id(self, cover_image_url: str) -> str:
        if self.asset_store is None:
            return ""
        return self.asset_store.get_integration_asset("telegram", file_cache_key(cover_image_url)) or ""


def render_telegram_caption(
    topic: TopicCandidate,
    ai_detail: AIDetail | None = None,
    ai_error: str = "",
) -> str:
    lines = [
        f"<b>{html.escape(notification_title(topic))}</b>",
        "",
        html.escape(notification_meta_line(topic, format_score(topic.score))),
    ]
    if ai_detail is not None:
        takeaway = compact_text(ai_detail.takeaway or "值得继续关注该热点后续进展。", 120)
        summary = compact_text(ai_detail.summary or "未能确认", 180)
        risk_note = compact_text(ai_detail.risk_note or "相关信息仍需以后续公开说明为准。", 120)
        lines.extend(
            [
                "",
                "<b>一句话结论</b>",
                html.escape(takeaway),
                "",
                "<b>热点梳理</b>",
                html.escape(summary),
                "",
                "<b>风险提示</b>",
                html.escape(risk_note),
                f"核验程度：{html.escape(confidence_label(ai_detail.confidence))}",
            ]
        )
    else:
        lines.extend(["", html.escape(user_visible_ai_error(ai_error))])
    return _truncate("\n".join(lines), TELEGRAM_CAPTION_LIMIT)


def build_reply_markup(detail_url: str, source_url: str) -> dict:
    buttons = []
    if detail_url and _is_public_http_url(detail_url):
        buttons.append({"text": "查看详情", "url": detail_url})
    if source_url and _is_public_http_url(source_url):
        buttons.append({"text": "微博来源", "url": source_url})
    return {"inline_keyboard": [buttons]} if buttons else {"inline_keyboard": []}


def file_cache_key(cover_image_url: str) -> str:
    return f"cover_file_id_{sha1(cover_image_url.encode('utf-8')).hexdigest()}"


def _parse_telegram_response(payload: dict) -> TelegramSendResult:
    if not payload.get("ok"):
        return TelegramSendResult(False, str(payload.get("description") or payload))
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    message_id = str(result.get("message_id") or "")
    photo = result.get("photo") if isinstance(result, dict) else None
    if isinstance(photo, list) and photo:
        best_photo = photo[-1] if isinstance(photo[-1], dict) else {}
        file_id = str(best_photo.get("file_id") or "")
        return TelegramSendResult(True, external_message_id=message_id, media_file_id=file_id)
    return TelegramSendResult(True, external_message_id=message_id)


def _is_http_success(response: requests.Response) -> bool:
    status_code = getattr(response, "status_code", 200)
    return 200 <= int(status_code) < 300


def _extract_telegram_error(response: requests.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except Exception:
        return fallback
    if isinstance(payload, dict):
        return str(payload.get("description") or payload)
    return fallback


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.startswith("10.") or host.startswith("192.168."):
        return False
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) > 1:
            try:
                second = int(parts[1])
            except ValueError:
                second = -1
            if 16 <= second <= 31:
                return False
    return True


def _is_file_id_invalid(error_message: str) -> bool:
    lowered = error_message.lower()
    return "file_id" in lowered or "file identifier" in lowered or "wrong file" in lowered


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"
