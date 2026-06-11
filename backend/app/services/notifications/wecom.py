from __future__ import annotations

import html
import io
import logging
import mimetypes
import re
import time
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import requests

from backend.app.core.config import WeComConfig
from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import AIDetail, TopicCandidate, now_iso
from backend.app.services.notifications.renderers import notification_title, user_visible_ai_error

logger = logging.getLogger(__name__)

MEDIA_ID_INVALID_CODES = {40007, 40009, 42007}


class AssetStore(Protocol):
    def get_integration_asset(self, provider: str, target_key: str) -> str | None:
        raise NotImplementedError

    def set_integration_asset(self, provider: str, target_key: str, value: str) -> None:
        raise NotImplementedError


@dataclass
class _TokenCache:
    value: str = ""
    expires_at: float = 0.0

    def valid(self) -> bool:
        return bool(self.value and time.time() < self.expires_at)


class WeComNotifier:
    def __init__(
        self,
        config: WeComConfig,
        session: requests.Session | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.asset_store = asset_store
        self._token = _TokenCache()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ) -> bool:
        if self.config.message_type == "markdown":
            return self.send_markdown(
                notification_title(topic),
                render_topic_markdown(topic, alert_tags, ai_detail, ai_error, detail_url),
            )
        return self.send_mpnews_topic(topic, alert_tags, ai_detail, ai_error, detail_url)

    def send_health_alert(self, message: str) -> bool:
        content = f"**热点洞察通知异常**\n\n> 时间：{now_iso()}\n> {message}"
        return self.send_markdown("热点洞察通知异常", content)

    def send_mpnews_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ) -> bool:
        if not self.enabled:
            logger.warning("企业微信未配置，跳过发送: %s", topic.title)
            return False

        try:
            thumb_media_id = self._get_cover_media_id(topic)
            payload = build_mpnews_payload(topic, self.config, thumb_media_id, ai_detail, ai_error, detail_url)
            ok, data = self._send_payload(payload)
            if ok:
                logger.info("企业微信 mpnews 推送成功: topic_id=%s title=%s", topic.id, topic.title)
                return True

            if _is_media_id_invalid(data):
                logger.warning("企业微信素材失效，重新上传后重试: topic_id=%s title=%s", topic.id, topic.title)
                thumb_media_id = self._get_cover_media_id(topic, force_upload=True)
                payload = build_mpnews_payload(topic, self.config, thumb_media_id, ai_detail, ai_error, detail_url)
                ok, data = self._send_payload(payload)
                if ok:
                    logger.info("企业微信 mpnews 重试成功: topic_id=%s title=%s", topic.id, topic.title)
                    return True

            logger.warning("企业微信 mpnews 推送失败，降级 markdown: %s", redact_sensitive_text(data))
        except Exception as exc:
            logger.warning("企业微信 mpnews 推送异常，降级 markdown: %s", redact_sensitive_text(exc))

        return self.send_markdown(
            notification_title(topic),
            render_topic_markdown(topic, alert_tags, ai_detail, ai_error, detail_url),
        )

    def send_markdown(self, title: str, content: str) -> bool:
        if not self.enabled:
            logger.warning("企业微信未配置，跳过发送: %s", title)
            return False

        payload = {
            "touser": self.config.to_user,
            "msgtype": "markdown",
            "agentid": self.config.agent_id,
            "markdown": {"content": content},
            "enable_duplicate_check": 0,
        }
        ok, data = self._send_payload(payload)
        if ok:
            logger.info("企业微信 markdown 推送成功: %s", title)
            return True

        logger.warning("企业微信 markdown 推送失败，退回 text: %s", redact_sensitive_text(data))
        text_payload = {
            "touser": self.config.to_user,
            "msgtype": "text",
            "agentid": self.config.agent_id,
            "text": {"content": _markdown_to_text(content)},
            "safe": 0,
            "enable_duplicate_check": 0,
        }
        ok, text_data = self._send_payload(text_payload)
        if ok:
            logger.info("企业微信 text 推送成功: %s", title)
            return True
        logger.error("企业微信推送失败: %s", redact_sensitive_text(text_data))
        return False

    def _get_cover_media_id(self, topic: TopicCandidate, *, force_upload: bool = False) -> str:
        if topic.cover_image_url:
            cache_key = cover_media_cache_key(topic.cover_image_url)
            if not force_upload and self.asset_store is not None:
                cached = self.asset_store.get_integration_asset("wecom", cache_key)
                if cached:
                    return cached
            try:
                media_id = self._upload_cover_image_url(topic.cover_image_url)
                if self.asset_store is not None:
                    self.asset_store.set_integration_asset("wecom", cache_key, media_id)
                return media_id
            except Exception as exc:
                logger.warning(
                    "企业微信官方封面上传失败，尝试默认封面: topic_id=%s title=%s error=%s",
                    topic.id,
                    topic.title,
                    redact_sensitive_text(exc),
                )

        return self._get_default_cover_media_id(force_upload=force_upload)

    def _get_default_cover_media_id(self, *, force_upload: bool = False) -> str:
        if self.config.default_cover_media_id and not force_upload:
            return self.config.default_cover_media_id

        if self.config.default_cover_name:
            cache_key = f"default_cover_name_{self.config.default_cover_name}"
            if not force_upload and self.asset_store is not None:
                cached = self.asset_store.get_integration_asset("wecom", cache_key)
                if cached:
                    return cached
            try:
                media_id = self._find_material_media_id_by_name(self.config.default_cover_name)
                if media_id:
                    if self.asset_store is not None:
                        self.asset_store.set_integration_asset("wecom", cache_key, media_id)
                    return media_id
            except Exception as exc:
                logger.warning(
                    "企业微信默认素材查询失败，尝试本地默认封面: name=%s error=%s",
                    self.config.default_cover_name,
                    redact_sensitive_text(exc),
                )

        cache_key = cover_media_cache_key(str(self.config.default_cover))
        if not force_upload and self.asset_store is not None:
            cached = self.asset_store.get_integration_asset("wecom", cache_key)
            if cached:
                return cached
        media_id = self._upload_cover_image(self.config.default_cover)
        if self.asset_store is not None:
            self.asset_store.set_integration_asset("wecom", cache_key, media_id)
        return media_id

    def _upload_cover_image(self, image_path: Path) -> str:
        if not image_path.is_file():
            raise FileNotFoundError(f"企业微信封面图不存在: {image_path}")

        token = self._get_access_token()
        url = f"{self.config.origin}/cgi-bin/media/upload"
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        with image_path.open("rb") as file_obj:
            response = self.session.post(
                url,
                params={"access_token": token, "type": "image"},
                files={"media": (image_path.name, file_obj, mime_type)},
                timeout=30,
            )
        response.raise_for_status()
        data = response.json()
        media_id = data.get("media_id")
        if data.get("errcode", 0) not in {0, "0"} or not media_id:
            raise RuntimeError(f"企业微信封面上传失败: {redact_sensitive_text(data)}")
        logger.info("企业微信封面上传成功: %s", image_path)
        return str(media_id)

    def _upload_cover_image_url(self, image_url: str) -> str:
        response = self.session.get(
            image_url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://weibo.com/"},
            timeout=15,
        )
        response.raise_for_status()
        content = response.content
        if not content:
            raise RuntimeError("官方封面图片响应为空")
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        mime_type = content_type if content_type.startswith("image/") else "image/jpeg"
        filename = Path(urlparse(image_url).path).name or "weibo-cover.jpg"
        return self._upload_cover_bytes(filename, content, mime_type)

    def _upload_cover_bytes(self, filename: str, content: bytes, mime_type: str) -> str:
        token = self._get_access_token()
        url = f"{self.config.origin}/cgi-bin/media/upload"
        response = self.session.post(
            url,
            params={"access_token": token, "type": "image"},
            files={"media": (filename, io.BytesIO(content), mime_type)},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        media_id = data.get("media_id")
        if data.get("errcode", 0) not in {0, "0"} or not media_id:
            raise RuntimeError(f"企业微信封面上传失败: {redact_sensitive_text(data)}")
        logger.info("企业微信远程封面上传成功: filename=%s bytes=%s", filename, len(content))
        return str(media_id)

    def _find_material_media_id_by_name(self, name: str) -> str:
        token = self._get_access_token()
        url = f"{self.config.origin}/cgi-bin/material/batchget"
        for offset in range(0, 100, 20):
            response = self.session.post(
                url,
                params={"access_token": token},
                json={"type": "image", "offset": offset, "count": 20},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("errcode", 0) not in {0, "0"}:
                raise RuntimeError(f"企业微信素材列表获取失败: {redact_sensitive_text(data)}")
            items = data.get("itemlist")
            if not isinstance(items, list):
                items = data.get("item")
            if not isinstance(items, list):
                return ""
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name") or "").strip() == name and item.get("media_id"):
                    logger.info("企业微信默认素材命中: name=%s", name)
                    return str(item["media_id"])
            if len(items) < 20:
                return ""
        return ""

    def _send_payload(self, payload: dict) -> tuple[bool, dict]:
        token = self._get_access_token()
        url = f"{self.config.origin}/cgi-bin/message/send"
        response = self.session.post(url, params={"access_token": token}, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") == 0:
            return True, data

        if data.get("errcode") in {40014, 42001, 40001}:
            self._token = _TokenCache()
            token = self._get_access_token()
            response = self.session.post(url, params={"access_token": token}, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get("errcode") == 0:
                return True, data

        return False, data

    def _get_access_token(self) -> str:
        if self._token.valid():
            return self._token.value

        url = f"{self.config.origin}/cgi-bin/gettoken"
        response = self.session.get(
            url,
            params={"corpid": self.config.corp_id, "corpsecret": self.config.corp_secret},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"企业微信 access_token 获取失败: {data}")

        expires_in = int(data.get("expires_in", 7200))
        self._token = _TokenCache(value=token, expires_at=time.time() + max(expires_in - 300, 60))
        return token


def build_mpnews_payload(
    topic: TopicCandidate,
    config: WeComConfig,
    thumb_media_id: str,
    ai_detail: AIDetail | None = None,
    ai_error: str = "",
    detail_url: str = "",
) -> dict:
    return {
        "touser": config.to_user,
        "msgtype": "mpnews",
        "agentid": config.agent_id,
        "mpnews": {
            "articles": [
                {
                    "title": _truncate(notification_title(topic), 64),
                    "thumb_media_id": thumb_media_id,
                    "author": config.mpnews_author,
                    "content_source_url": detail_url or topic.url,
                    "content": render_mpnews_content(topic, ai_detail, ai_error, detail_url),
                    "digest": _truncate(_digest(topic), 120),
                }
            ]
        },
        "enable_duplicate_check": 0,
    }


def render_mpnews_content(
    topic: TopicCandidate,
    ai_detail: AIDetail | None = None,
    ai_error: str = "",
    detail_url: str = "",
) -> str:
    tag = html.escape(topic.tag or "无标记")
    title = html.escape(notification_title(topic))
    rank = html.escape(f"#{topic.rank}" if topic.rank is not None else "-")
    score = html.escape(format_score(topic.score))
    source = html.escape(topic.source_id)
    fetched_at = html.escape(topic.fetched_at)
    url = html.escape(topic.url, quote=True)
    detail_link = html.escape(detail_url, quote=True)
    detail_html_link = f'<div style="margin-top:16px;"><a href="{detail_link}">查看网站详情页</a></div>' if detail_url else ""
    source_excerpt = html.escape(topic.source_excerpt or "微博官方公开详情页暂未提供更多摘要。")

    detail_html = render_ai_detail_html(ai_detail, ai_error)
    return f"""
<div style="font-size:18px;font-weight:bold;line-height:1.5;">{title}</div>
<div style="margin:12px 0;padding:10px 12px;background:#fff7e6;border-left:4px solid #fa8c16;">
  <div><strong>标记：</strong>{tag}</div>
  <div><strong>排名：</strong>{rank}</div>
  <div><strong>热度：</strong>{score}</div>
  <div><strong>来源：</strong>{source}</div>
  <div><strong>抓取时间：</strong>{fetched_at}</div>
</div>
<div style="margin:14px 0;">
  <div style="font-weight:bold;">微博原始信息</div>
  <div style="margin-top:8px;line-height:1.6;">{source_excerpt}</div>
</div>
<div style="margin:14px 0;">
  {detail_html}
</div>
{detail_html_link}
<div style="margin-top:16px;"><a href="{url}">查看微博来源</a></div>
""".strip()


def render_ai_detail_html(ai_detail: AIDetail | None, ai_error: str = "") -> str:
    if ai_detail is None:
        error = html.escape(ai_error or "AI 详情生成失败")
        return (
            '<div style="font-weight:bold;">AI 热点详情</div>'
            f'<div style="color:#666;line-height:1.6;">{user_visible_ai_error(error)}</div>'
        )

    facts = "".join(f"<li>{html.escape(fact)}</li>" for fact in ai_detail.facts)
    sources = "".join(
        f'<li><a href="{html.escape(source.url, quote=True)}">{html.escape(source.title or source.url)}</a></li>'
        for source in ai_detail.sources
        if source.url
    )
    if not sources:
        sources = "<li>未能确认可靠来源链接</li>"
    confidence = html.escape(ai_detail.confidence or "未标注")
    return f"""
<div style="font-weight:bold;">AI 热点详情</div>
<div style="margin-top:8px;font-weight:bold;line-height:1.6;">{html.escape(ai_detail.takeaway or "值得继续关注该热点后续进展。")}</div>
<div style="margin-top:8px;line-height:1.6;">{html.escape(ai_detail.summary)}</div>
<div style="margin-top:12px;font-weight:bold;">关键事实</div>
<ul>{facts or "<li>未能确认</li>"}</ul>
<div style="margin-top:12px;font-weight:bold;">AI 评价</div>
<div style="line-height:1.6;">{html.escape(ai_detail.commentary or "未能确认")}</div>
<div style="margin-top:12px;font-weight:bold;">风险提示</div>
<div style="line-height:1.6;">{html.escape(ai_detail.risk_note or "未能确认")}（可信度：{confidence}）</div>
<div style="margin-top:12px;font-weight:bold;">参考来源</div>
<ul>{sources}</ul>
""".strip()


def render_topic_markdown(
    topic: TopicCandidate,
    alert_tags: tuple[str, ...],
    ai_detail: AIDetail | None = None,
    ai_error: str = "",
    detail_url: str = "",
) -> str:
    base = render_topics_markdown([topic], alert_tags)
    detail_line = f"\n\n网站详情：{detail_url}" if detail_url else ""
    if ai_detail is None:
        return f"{base}{detail_line}\n\nAI 洞察：{user_visible_ai_error(ai_error)}"
    facts = "\n".join(f"- {fact}" for fact in ai_detail.facts) or "- 未能确认"
    sources = "\n".join(f"- {source.title or source.url}: {source.url}" for source in ai_detail.sources) or "- 未能确认"
    return (
        f"{base}{detail_line}\n\n"
        f"一句话结论：{ai_detail.takeaway or '值得继续关注该热点后续进展。'}\n\n"
        f"热点梳理：{ai_detail.summary}\n\n"
        f"关键事实：\n{facts}\n\n"
        f"AI 评价：{ai_detail.commentary or '未能确认'}\n\n"
        f"风险提示：{ai_detail.risk_note or '未能确认'}（可信度：{ai_detail.confidence or '未标注'}）\n\n"
        f"参考来源：\n{sources}"
    )


def render_topics_markdown(topics: list[TopicCandidate], alert_tags: tuple[str, ...]) -> str:
    lines = [
        f"**热点洞察 {len(topics)} 条**",
        "",
        f"> 时间：{now_iso()}",
        f"> 推送标记：{', '.join(alert_tags) if alert_tags else '未配置'}",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        tag = f"【{topic.tag}】" if topic.tag else "【无标记】"
        rank = f"#{topic.rank}" if topic.rank is not None else "-"
        score = format_score(topic.score)
        title = _escape_link_text(notification_title(topic))
        lines.extend(
            [
                f"{index}. <font color=\"warning\">{tag}</font> [{title}]({topic.url})",
                f"   排名：{rank} | 热度：{score} | 来源：{topic.source_id}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def cover_media_cache_key(value: str) -> str:
    return f"cover_media_id_{sha1(value.encode('utf-8')).hexdigest()}"


def format_score(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 10000:
        return f"{value / 10000:.1f}万"
    return f"{value:,}"


def _digest(topic: TopicCandidate) -> str:
    tag = f"【{topic.tag}】" if topic.tag else ""
    rank = f"排名 #{topic.rank}" if topic.rank is not None else "排名 -"
    score = f"热度 {format_score(topic.score)}"
    return f"{tag}{rank} | {score} | 来源 {topic.source_id}"


def _escape_link_text(text: str) -> str:
    return text.replace("[", "［").replace("]", "］").replace("\n", " ")


def _markdown_to_text(content: str) -> str:
    text = re.sub(r"<font[^>]*>(.*?)</font>", r"\1", content)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1\n\2", text)
    return text.replace("> ", "")


def _is_media_id_invalid(data: dict) -> bool:
    errmsg = str(data.get("errmsg", "")).lower()
    return data.get("errcode") in MEDIA_ID_INVALID_CODES or "media_id" in errmsg


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"
