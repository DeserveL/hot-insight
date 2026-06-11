from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import requests

from backend.app.core.config import AppConfig
from backend.app.core.logging import mask_external_target, redact_sensitive_text
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, TopicCandidate, topic_detail_url
from backend.app.services.notifications.telegram import TelegramNotifier, TelegramSendResult
from backend.app.services.notifications.wecom import WeComNotifier

logger = logging.getLogger(__name__)


class TopicNotifier(Protocol):
    provider: str

    @property
    def enabled(self) -> bool:
        raise NotImplementedError

    @property
    def target(self) -> str:
        raise NotImplementedError

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ):
        raise NotImplementedError


@dataclass(frozen=True)
class DeliveryTarget:
    provider: str
    target: str

    def as_tuple(self) -> tuple[str, str]:
        return (self.provider, self.target)


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    target: str
    success: bool
    error_message: str = ""
    external_message_id: str = ""


class WeComNotificationProvider:
    provider = "wecom"

    def __init__(self, notifier: WeComNotifier) -> None:
        self.notifier = notifier

    @property
    def enabled(self) -> bool:
        return self.notifier.enabled

    @property
    def target(self) -> str:
        return self.notifier.config.to_user

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ) -> DeliveryResult:
        ok = self.notifier.send_topic(topic, alert_tags, ai_detail, ai_error, detail_url)
        return DeliveryResult(self.provider, self.target, ok, "" if ok else "企业微信推送失败")

    def send_health_alert(self, message: str) -> DeliveryResult:
        ok = self.notifier.send_health_alert(message)
        return DeliveryResult(self.provider, self.target, ok, "" if ok else "企业微信健康告警推送失败")


class TelegramNotificationProvider:
    provider = "telegram"

    def __init__(self, notifier: TelegramNotifier) -> None:
        self.notifier = notifier

    @property
    def enabled(self) -> bool:
        return self.notifier.enabled

    @property
    def target(self) -> str:
        return self.notifier.target

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        detail_url: str = "",
    ) -> DeliveryResult:
        result: TelegramSendResult = self.notifier.send_topic(
            topic,
            alert_tags,
            ai_detail,
            ai_error,
            detail_url,
        )
        return DeliveryResult(
            self.provider,
            self.target,
            result.ok,
            result.error_message,
            result.external_message_id,
        )

    def send_health_alert(self, message: str) -> DeliveryResult:
        result = self.notifier.send_health_alert(message)
        return DeliveryResult(
            self.provider,
            self.target,
            result.ok,
            result.error_message,
            result.external_message_id,
        )


class NotificationRouter:
    def __init__(self, providers: list[TopicNotifier], public_site_url: str = "") -> None:
        self.providers = [provider for provider in providers if provider.enabled]
        self.public_site_url = public_site_url
        logger.info(
            "通知路由初始化完成: enabled_targets=%s public_site_url_configured=%s",
            ",".join(_format_target(provider.provider, provider.target) for provider in self.providers) or "无",
            bool(public_site_url),
        )

    def delivery_targets(self) -> list[DeliveryTarget]:
        return [DeliveryTarget(provider.provider, provider.target) for provider in self.providers]

    def send_topic(
        self,
        topic: TopicCandidate,
        alert_tags: tuple[str, ...],
        ai_detail: AIDetail | None = None,
        ai_error: str = "",
        targets: list[tuple[str, str]] | None = None,
    ) -> list[DeliveryResult]:
        target_set = set(targets or [target.as_tuple() for target in self.delivery_targets()])
        detail_url = topic_detail_url(self.public_site_url, topic.id) or topic.url
        results: list[DeliveryResult] = []
        for provider in self.providers:
            provider_target = (provider.provider, provider.target)
            if provider_target not in target_set:
                continue
            started = time.perf_counter()
            logger.info(
                "通知目标发送开始: topic_id=%s title=%s provider=%s target=%s",
                topic.id,
                topic.title,
                provider.provider,
                mask_external_target(provider.provider, provider.target),
            )
            try:
                raw_result = provider.send_topic(topic, alert_tags, ai_detail, ai_error, detail_url)
                result = DeliveryResult(
                    raw_result.provider,
                    raw_result.target,
                    raw_result.success,
                    redact_sensitive_text(raw_result.error_message),
                    raw_result.external_message_id,
                )
                results.append(result)
                logger.info(
                    "通知目标发送完成: topic_id=%s provider=%s target=%s success=%s external_message_id=%s duration_ms=%.1f error=%s",
                    topic.id,
                    result.provider,
                    mask_external_target(result.provider, result.target),
                    result.success,
                    result.external_message_id or "-",
                    (time.perf_counter() - started) * 1000,
                    result.error_message or "-",
                )
            except Exception as exc:
                error_message = redact_sensitive_text(exc)
                logger.error(
                    "通知目标发送异常: topic_id=%s title=%s provider=%s target=%s error=%s",
                    topic.id,
                    topic.title,
                    provider.provider,
                    mask_external_target(provider.provider, provider.target),
                    error_message,
                )
                results.append(DeliveryResult(provider.provider, provider.target, False, error_message, ""))
        return results

    def send_health_alert(self, message: str) -> bool:
        sent = False
        for provider in self.providers:
            send_health = getattr(provider, "send_health_alert", None)
            if send_health is None:
                continue
            try:
                raw_result = send_health(message)
                result = DeliveryResult(
                    raw_result.provider,
                    raw_result.target,
                    raw_result.success,
                    redact_sensitive_text(raw_result.error_message),
                    raw_result.external_message_id,
                )
                sent = sent or bool(result.success)
                logger.info(
                    "健康告警通知完成: provider=%s target=%s success=%s external_message_id=%s error=%s",
                    result.provider,
                    mask_external_target(result.provider, result.target),
                    result.success,
                    result.external_message_id or "-",
                    result.error_message or "-",
                )
            except Exception as exc:
                logger.error(
                    "健康告警通知异常: provider=%s target=%s error=%s",
                    provider.provider,
                    mask_external_target(provider.provider, provider.target),
                    redact_sensitive_text(exc),
                )
        return sent


def build_notification_router(
    config: AppConfig,
    *,
    session: requests.Session | None = None,
    repository: AppRepository | None = None,
) -> NotificationRouter:
    session = session or requests.Session()
    channels = set(config.notify_channels)
    providers: list[TopicNotifier] = []
    if "wecom" in channels:
        providers.append(WeComNotificationProvider(WeComNotifier(config.wecom, session=session, asset_store=repository)))
    if "telegram" in channels:
        providers.append(
            TelegramNotificationProvider(
                TelegramNotifier(config.telegram, session=session, asset_store=repository)
            )
        )
    return NotificationRouter(providers, config.public_site_url)


def _format_target(provider: str, target: str) -> str:
    return f"{provider}:{mask_external_target(provider, target)}"
