from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import now_iso
from backend.app.services.notifications.renderers import compact_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeComRobotAlertResult:
    ok: bool
    error_message: str = ""


def send_wecom_robot_health_alert(
    *,
    webhook_url: str,
    message: str,
    timeout_seconds: int,
    session: requests.Session,
) -> WeComRobotAlertResult:
    if not webhook_url:
        return WeComRobotAlertResult(False, "企业微信群机器人 webhook 未配置")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": render_health_alert_markdown(message),
        },
    }
    try:
        response = session.post(webhook_url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        error_message = redact_sensitive_text(exc)
        logger.warning("企微机器人健康告警请求失败: provider=wecom_robot error=%s", error_message)
        return WeComRobotAlertResult(False, error_message)

    if data.get("errcode", 0) in {0, "0"}:
        logger.info("企微机器人健康告警发送成功: provider=wecom_robot")
        return WeComRobotAlertResult(True)

    error_message = redact_sensitive_text(data)
    logger.warning("企微机器人健康告警返回失败: provider=wecom_robot error=%s", error_message)
    return WeComRobotAlertResult(False, error_message)


def render_health_alert_markdown(message: str) -> str:
    reason = summarize_health_alert_reason(message)
    return "\n".join(
        [
            "## 热点洞察采集异常",
            "",
            f"> 时间：{now_iso()}",
            "> 摘要：所有微博热搜数据源本轮均不可用",
            f"> 原因：{reason}",
            "> 提示：系统将在下一轮调度自动重试，可查看 `data/logs/hot-insight.log` 按 `run_id` 排查。",
        ]
    )


def summarize_health_alert_reason(message: str) -> str:
    text = redact_sensitive_text(message)
    lowered = text.lower()
    if "temporary failure in name resolution" in lowered or "failed to resolve" in lowered:
        return "DNS 解析失败，服务器短时间无法解析微博或备用数据源域名。"
    if "timed out" in lowered or "timeout" in lowered or "read timed out" in lowered:
        return "请求超时，可能是网络波动或远端响应变慢。"
    if "http" in lowered and ("status" in lowered or "请求失败" in text):
        return "数据源 HTTP 请求失败，可能是远端服务异常或网络不稳定。"
    return compact_text(text, 360) or "未知采集异常。"
