from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from uuid import uuid4

import requests

from backend.app.core.config import AppConfig
from backend.app.core.logging import logging_run, mask_external_target, redact_sensitive_text
from backend.app.db.repositories import AppRepository
from backend.app.domain.models import AIDetail, TopicCandidate, WEIBO_CHANNEL_ID, now_iso
from backend.app.services.ai.detail_client import AIContext, AIDetailClient, build_context_hash, combine_weibo_context
from backend.app.services.ai.context_change import (
    ContextChangeThresholds,
    build_context_material_snapshot,
    evaluate_context_material_change,
    serialize_context_material_snapshot,
)
from backend.app.services.ai.prompts import PROMPT_VERSION
from backend.app.services.ingestion.weibo_official import (
    fetch_weibo_mobile_search_material,
    fetch_weibo_official_detail_material,
)
from backend.app.services.ingestion.weibo_sources import SourceError, build_weibo_sources
from backend.app.services.notifications.router import NotificationRouter, build_notification_router
from backend.app.services.notifications.wecom_robot import send_wecom_robot_health_alert

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    fetched_source: str | None
    source_fetched_count: int
    tracked_count: int
    ai_success_count: int
    ai_failed_count: int
    alert_eligible_count: int
    pending_notification_count: int
    sent_count: int
    health_alert_sent: bool

    @property
    def fetched_count(self) -> int:
        return self.source_fetched_count

    @property
    def eligible_count(self) -> int:
        return self.alert_eligible_count

    @property
    def new_count(self) -> int:
        return self.pending_notification_count


@dataclass(frozen=True)
class FetchTopicsResult:
    topics: list[TopicCandidate]
    source_id: str | None
    health_message: str
    source_fetched_count: int


@dataclass(frozen=True)
class AIInsightRunResult:
    success_count: int
    failed_count: int
    skipped_count: int


def run_once(
    config: AppConfig,
    *,
    session: requests.Session | None = None,
    repository: AppRepository | None = None,
    notifier: NotificationRouter | None = None,
    ai_client: AIDetailClient | None = None,
) -> RunResult:
    run_id = f"run-{uuid4().hex[:12]}"
    started = time.perf_counter()
    with logging_run(run_id):
        logger.info(
            "采集运行开始: source_order=%s track_tags=%s alert_tags=%s max_topics_per_run=%s",
            ",".join(config.weibo_source_order),
            ",".join(config.track_tags) if config.track_tags else "未配置",
            ",".join(config.alert_tags) if config.alert_tags else "未配置",
            config.max_topics_per_run,
        )
        try:
            result = _run_once_inner(
                config,
                session=session,
                repository=repository,
                notifier=notifier,
                ai_client=ai_client,
            )
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception("采集运行异常结束: duration_ms=%.1f", duration_ms)
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            (
                "采集运行完成: source=%s source_fetched=%s tracked=%s ai_success=%s "
                "ai_failed=%s alert_eligible=%s pending_notifications=%s sent=%s "
                "health_alert=%s duration_ms=%.1f"
            ),
            result.fetched_source,
            result.source_fetched_count,
            result.tracked_count,
            result.ai_success_count,
            result.ai_failed_count,
            result.alert_eligible_count,
            result.pending_notification_count,
            result.sent_count,
            result.health_alert_sent,
            duration_ms,
        )
        return result


def _run_once_inner(
    config: AppConfig,
    *,
    session: requests.Session | None = None,
    repository: AppRepository | None = None,
    notifier: NotificationRouter | None = None,
    ai_client: AIDetailClient | None = None,
) -> RunResult:
    session = session or requests.Session()
    own_repository = repository is None
    repository = repository or AppRepository(config.database_path)
    notifier = notifier or build_notification_router(config, session=session, repository=repository)
    ai_client = ai_client or AIDetailClient(config.ai_detail, session=session)

    try:
        fetch_result = _fetch_business_topics(
            config,
            session,
            repository,
        )
        selected_topics = fetch_result.topics
        selected_source = fetch_result.source_id

        if not selected_topics:
            health_sent = (
                _send_health_alert_if_needed(config, repository, session, fetch_result.health_message)
                if fetch_result.health_message
                else False
            )
            return RunResult(selected_source, fetch_result.source_fetched_count, 0, 0, 0, 0, 0, 0, health_sent)

        ai_result = _ensure_ai_insights(config, repository, ai_client, selected_topics)

        eligible = filter_alert_topics(selected_topics, config.alert_tags)
        if not config.alert_tags:
            logger.info("ALERT_TAGS 为空，本轮只记录采集数据，不发送业务通知")
            return RunResult(
                selected_source,
                fetch_result.source_fetched_count,
                len(selected_topics),
                ai_result.success_count,
                ai_result.failed_count,
                0,
                0,
                0,
                False,
            )

        if not eligible:
            logger.info("本轮没有命中标记 %s 的热点", ",".join(config.alert_tags))
            return RunResult(
                selected_source,
                fetch_result.source_fetched_count,
                len(selected_topics),
                ai_result.success_count,
                ai_result.failed_count,
                0,
                0,
                0,
                False,
            )

        targets = [target.as_tuple() for target in notifier.delivery_targets()]
        if not targets:
            logger.warning("没有启用任何通知目标，本轮不发送业务通知")
            return RunResult(
                selected_source,
                fetch_result.source_fetched_count,
                len(selected_topics),
                ai_result.success_count,
                ai_result.failed_count,
                len(eligible),
                0,
                0,
                False,
            )

        pending_by_topic = {
            topic.id: repository.pending_delivery_targets(topic, targets)
            for topic in eligible
        }
        new_topics = [topic for topic in eligible if pending_by_topic[topic.id]]
        limited_topics = new_topics[: config.max_topics_per_run]
        if not limited_topics:
            logger.info("本轮命中热点均已完成通知投递")
            return RunResult(
                selected_source,
                fetch_result.source_fetched_count,
                len(selected_topics),
                ai_result.success_count,
                ai_result.failed_count,
                len(eligible),
                0,
                0,
                False,
            )

        logger.info(
            "准备逐条推送新增热点: limited=%s total_pending=%s targets=%s",
            len(limited_topics),
            len(new_topics),
            _format_delivery_targets(targets),
        )
        sent_count = 0
        for topic in limited_topics:
            logger.info(
                "热点处理开始: topic_id=%s title=%s tag=%s rank=%s pending_targets=%s",
                topic.id,
                topic.title,
                topic.tag,
                topic.rank,
                _format_delivery_targets(pending_by_topic[topic.id]),
            )
            ai_detail, ai_error = _load_cached_ai_detail_for_notification(repository, topic)
            results = notifier.send_topic(
                topic,
                config.alert_tags,
                ai_detail,
                ai_error,
                targets=pending_by_topic[topic.id],
            )
            topic_sent = False
            for result in results:
                repository.record_notification_delivery(
                    topic=topic,
                    provider=result.provider,
                    target=result.target,
                    success=result.success,
                    error_message=result.error_message,
                    external_message_id=result.external_message_id,
                )
                topic_sent = topic_sent or result.success
            if topic_sent:
                sent_count += 1
                logger.info("热点至少一个通知目标发送成功: topic_id=%s title=%s", topic.id, topic.title)
            else:
                logger.error("热点所有通知目标推送失败: topic_id=%s title=%s", topic.id, topic.title)

        return RunResult(
            selected_source,
            fetch_result.source_fetched_count,
            len(selected_topics),
            ai_result.success_count,
            ai_result.failed_count,
            len(eligible),
            len(new_topics),
            sent_count,
            False,
        )
    finally:
        if own_repository:
            repository.close()


def filter_alert_topics(topics: list[TopicCandidate], alert_tags: tuple[str, ...]) -> list[TopicCandidate]:
    tag_set = set(alert_tags)
    if not tag_set:
        return []
    return [topic for topic in topics if topic.tag and topic.tag in tag_set]


def filter_track_topics(topics: list[TopicCandidate], track_tags: tuple[str, ...]) -> list[TopicCandidate]:
    tag_set = set(track_tags)
    if not tag_set:
        return []
    return [topic for topic in topics if topic.tag and topic.tag in tag_set]


def _ensure_ai_insights(
    config: AppConfig,
    repository: AppRepository,
    ai_client: AIDetailClient,
    topics: list[TopicCandidate],
) -> AIInsightRunResult:
    if not topics:
        return AIInsightRunResult(0, 0, 0)
    if not config.ai_detail.enabled:
        logger.info("AI 洞察未启用，本轮跳过生成: topics=%s", len(topics))
        return AIInsightRunResult(0, 0, len(topics))

    logger.info(
        "AI 洞察队列开始: topics=%s model=%s available=%s",
        len(topics),
        config.ai_detail.model or "未配置",
        config.ai_detail.available,
    )
    success_count = 0
    failed_count = 0
    skipped_count = 0
    for topic in topics:
        result = _generate_ai_detail_if_missing(config, repository, ai_client, topic)
        if result == "success":
            success_count += 1
        elif result == "failed":
            failed_count += 1
        else:
            skipped_count += 1
    logger.info(
        "AI 洞察处理完成: topics=%s success=%s failed=%s skipped=%s",
        len(topics),
        success_count,
        failed_count,
        skipped_count,
    )
    return AIInsightRunResult(success_count, failed_count, skipped_count)


def _generate_ai_detail_if_missing(
    config: AppConfig,
    repository: AppRepository,
    ai_client: AIDetailClient,
    topic: TopicCandidate,
) -> str:
    context = _prepare_ai_context(ai_client, topic)
    context_material = _build_context_material(context)
    context_material_json = serialize_context_material_snapshot(context_material)
    cached = repository.get_ai_insight_record(topic.id)
    retrying_failed_cache = False
    if cached:
        metadata_matches = _ai_cache_metadata_matches(cached, config)
        exact_context_match = metadata_matches and cached.get("context_hash") == context.context_hash
        if exact_context_match:
            if not cached.get("context_material"):
                repository.update_ai_context_material(topic.id, context_material_json)
                logger.info(
                    "AI 洞察缓存补写材料快照: topic_id=%s title=%s context_hash=%s",
                    topic.id,
                    topic.title,
                    context.context_hash[:12],
                )
            if cached["status"] == "success" and cached["detail"] is not None:
                logger.info(
                    "AI 洞察跳过调用: topic_id=%s title=%s reason=success_cache updated_at=%s prompt_version=%s api_mode=%s context_hash=%s",
                    topic.id,
                    topic.title,
                    cached.get("updated_at") or "-",
                    cached.get("prompt_version") or "-",
                    cached.get("api_mode") or "-",
                    str(cached.get("context_hash") or "")[:12] or "-",
                )
                return "skipped"
            if context.combined_context:
                failed_retry_context_hash = str(cached.get("failed_retry_context_hash") or "")
                if failed_retry_context_hash == context.context_hash:
                    logger.info(
                        "AI 洞察跳过调用: topic_id=%s title=%s reason=failed_cache_retry_used updated_at=%s error=%s prompt_version=%s api_mode=%s context_hash=%s",
                        topic.id,
                        topic.title,
                        cached.get("updated_at") or "-",
                        cached.get("error_message") or "-",
                        cached.get("prompt_version") or "-",
                        cached.get("api_mode") or "-",
                        str(cached.get("context_hash") or "")[:12] or "-",
                    )
                    return "skipped"
                retrying_failed_cache = True
                logger.info(
                    "AI 洞察失败缓存有新微博材料，将重试一次: topic_id=%s title=%s updated_at=%s context_hash=%s",
                    topic.id,
                    topic.title,
                    cached.get("updated_at") or "-",
                    str(cached.get("context_hash") or "")[:12] or "-",
                )
            else:
                logger.info(
                    "AI 洞察跳过调用: topic_id=%s title=%s reason=failed_cache updated_at=%s error=%s prompt_version=%s api_mode=%s context_hash=%s",
                    topic.id,
                    topic.title,
                    cached.get("updated_at") or "-",
                    cached.get("error_message") or "-",
                    cached.get("prompt_version") or "-",
                    cached.get("api_mode") or "-",
                    str(cached.get("context_hash") or "")[:12] or "-",
                )
                return "skipped"
        elif metadata_matches:
            decision = evaluate_context_material_change(
                cached.get("context_material") or {},
                context_material,
                _context_change_thresholds(config),
            )
            if cached["status"] == "success" and cached["detail"] is not None and not decision.significant:
                logger.info(
                    (
                        "AI 洞察跳过调用: topic_id=%s title=%s reason=minor_context_change "
                        "change_reason=%s basis=%s similarity=%.4f length_delta=%s length_ratio=%.4f "
                        "cached_context=%s current_context=%s"
                    ),
                    topic.id,
                    topic.title,
                    decision.reason,
                    decision.basis or "-",
                    decision.similarity,
                    decision.length_delta,
                    decision.length_ratio,
                    str(cached.get("context_hash") or "")[:12] or "-",
                    context.context_hash[:12],
                )
                return "skipped"
            if cached["status"] == "failed":
                if not context.combined_context:
                    logger.info(
                        "AI 洞察跳过调用: topic_id=%s title=%s reason=failed_cache updated_at=%s error=%s prompt_version=%s api_mode=%s context_hash=%s",
                        topic.id,
                        topic.title,
                        cached.get("updated_at") or "-",
                        cached.get("error_message") or "-",
                        cached.get("prompt_version") or "-",
                        cached.get("api_mode") or "-",
                        str(cached.get("context_hash") or "")[:12] or "-",
                    )
                    return "skipped"
                if not decision.significant:
                    logger.info(
                        (
                            "AI 洞察跳过调用: topic_id=%s title=%s reason=failed_cache_minor_context_change "
                            "change_reason=%s basis=%s similarity=%.4f length_delta=%s length_ratio=%.4f "
                            "cached_context=%s current_context=%s"
                        ),
                        topic.id,
                        topic.title,
                        decision.reason,
                        decision.basis or "-",
                        decision.similarity,
                        decision.length_delta,
                        decision.length_ratio,
                        str(cached.get("context_hash") or "")[:12] or "-",
                        context.context_hash[:12],
                    )
                    return "skipped"
                failed_retry_context_hash = str(cached.get("failed_retry_context_hash") or "")
                if failed_retry_context_hash == context.context_hash:
                    logger.info(
                        "AI 洞察跳过调用: topic_id=%s title=%s reason=failed_cache_retry_used updated_at=%s error=%s prompt_version=%s api_mode=%s context_hash=%s",
                        topic.id,
                        topic.title,
                        cached.get("updated_at") or "-",
                        cached.get("error_message") or "-",
                        cached.get("prompt_version") or "-",
                        cached.get("api_mode") or "-",
                        str(cached.get("context_hash") or "")[:12] or "-",
                    )
                    return "skipped"
                retrying_failed_cache = True
                logger.info(
                    (
                        "AI 洞察失败缓存遇到重大微博材料变化，将重试一次: topic_id=%s title=%s "
                        "change_reason=%s basis=%s similarity=%.4f length_delta=%s length_ratio=%.4f "
                        "cached_context=%s current_context=%s"
                    ),
                    topic.id,
                    topic.title,
                    decision.reason,
                    decision.basis or "-",
                    decision.similarity,
                    decision.length_delta,
                    decision.length_ratio,
                    str(cached.get("context_hash") or "")[:12] or "-",
                    context.context_hash[:12],
                )
            logger.info(
                (
                    "AI 洞察缓存失效，将重新生成: topic_id=%s title=%s status=%s cached_model=%s current_model=%s "
                    "cached_api_mode=%s current_api_mode=%s cached_prompt=%s current_prompt=%s "
                    "cached_context=%s current_context=%s change_reason=%s basis=%s similarity=%.4f length_delta=%s length_ratio=%.4f"
                ),
                topic.id,
                topic.title,
                cached.get("status") or "-",
                cached.get("model") or "-",
                config.ai_detail.model or "未配置",
                cached.get("api_mode") or "-",
                config.ai_detail.api_mode,
                cached.get("prompt_version") or "-",
                PROMPT_VERSION,
                str(cached.get("context_hash") or "")[:12] or "-",
                context.context_hash[:12],
                decision.reason,
                decision.basis or "-",
                decision.similarity,
                decision.length_delta,
                decision.length_ratio,
            )
        else:
            logger.info(
                "AI 洞察缓存失效，将重新生成: topic_id=%s title=%s status=%s cached_model=%s current_model=%s cached_api_mode=%s current_api_mode=%s cached_prompt=%s current_prompt=%s cached_context=%s current_context=%s change_reason=cache_metadata_changed",
                topic.id,
                topic.title,
                cached.get("status") or "-",
                cached.get("model") or "-",
                config.ai_detail.model or "未配置",
                cached.get("api_mode") or "-",
                config.ai_detail.api_mode,
                cached.get("prompt_version") or "-",
                PROMPT_VERSION,
                str(cached.get("context_hash") or "")[:12] or "-",
                context.context_hash[:12],
            )

    logger.info("AI 洞察生成开始: topic_id=%s title=%s tag=%s", topic.id, topic.title, topic.tag)
    started = time.perf_counter()
    result = ai_client.generate(topic, context=context) if hasattr(ai_client, "prepare_context") else ai_client.generate(topic)
    if result.ok and result.detail is not None:
        repository.save_ai_insight_success(
            topic,
            result.detail,
            config.ai_detail.model,
            prompt_version=PROMPT_VERSION,
            api_mode=config.ai_detail.api_mode,
            context_hash=getattr(result, "context_hash", "") or context.context_hash,
            context_material_json=context_material_json,
            search_source_count=getattr(result, "search_source_count", 0),
        )
        logger.info(
            "AI 洞察生成成功: topic_id=%s title=%s model=%s api_mode=%s search_sources=%s duration_ms=%.1f",
            topic.id,
            topic.title,
            config.ai_detail.model or "未配置",
            config.ai_detail.api_mode,
            getattr(result, "search_source_count", 0),
            (time.perf_counter() - started) * 1000,
        )
        return "success"

    error_message = result.error_message or "AI 详情生成失败"
    repository.save_ai_insight_failure(
        topic,
        error_message,
        config.ai_detail.model,
        prompt_version=PROMPT_VERSION,
        api_mode=config.ai_detail.api_mode,
        context_hash=getattr(result, "context_hash", "") or context.context_hash,
        failed_retry_context_hash=context.context_hash if retrying_failed_cache and context.combined_context else "",
        context_material_json=context_material_json,
        search_source_count=getattr(result, "search_source_count", 0),
    )
    logger.warning(
        "AI 洞察生成失败并已缓存: topic_id=%s title=%s model=%s api_mode=%s duration_ms=%.1f error=%s",
        topic.id,
        topic.title,
        config.ai_detail.model or "未配置",
        config.ai_detail.api_mode,
        (time.perf_counter() - started) * 1000,
        error_message,
    )
    return "failed"


def _prepare_ai_context(ai_client: AIDetailClient, topic: TopicCandidate) -> AIContext:
    if hasattr(ai_client, "prepare_context"):
        return ai_client.prepare_context(topic)
    official_context = topic.official_context or (topic.source_excerpt if topic.source_excerpt_origin == "official" else "")
    mobile_context = topic.mobile_context or (
        topic.source_excerpt if topic.source_excerpt and topic.source_excerpt_origin != "official" else ""
    )
    combined = combine_weibo_context(official_context, mobile_context, topic.realtime_posts)
    return AIContext(
        official_context=official_context,
        mobile_context=mobile_context,
        realtime_posts=topic.realtime_posts,
        combined_context=combined,
        context_hash=build_context_hash(
            topic,
            official_context,
            has_mobile_context=bool(mobile_context or topic.realtime_posts),
        ),
    )


def _build_context_material(context: AIContext) -> dict:
    return build_context_material_snapshot(
        official_context=context.official_context,
        mobile_context=context.mobile_context,
        has_mobile_context=bool(context.mobile_context or context.realtime_posts),
    )


def _context_change_thresholds(config: AppConfig) -> ContextChangeThresholds:
    return ContextChangeThresholds(
        similarity_threshold=config.ai_detail.context_change_similarity_threshold,
        length_delta=config.ai_detail.context_change_length_delta,
        length_ratio=config.ai_detail.context_change_length_ratio,
    )


def _ai_cache_metadata_matches(cached: dict, config: AppConfig) -> bool:
    return (
        cached.get("model") == config.ai_detail.model
        and cached.get("api_mode") == config.ai_detail.api_mode
        and cached.get("prompt_version") == PROMPT_VERSION
    )


def _ai_cache_matches(cached: dict, config: AppConfig, context: AIContext) -> bool:
    return (
        _ai_cache_metadata_matches(cached, config)
        and cached.get("context_hash") == context.context_hash
    )


def _load_cached_ai_detail_for_notification(
    repository: AppRepository,
    topic: TopicCandidate,
) -> tuple[AIDetail | None, str]:
    cached = repository.get_ai_insight_record(topic.id)
    if not cached:
        logger.info("通知阶段未找到 AI 洞察缓存: topic_id=%s title=%s", topic.id, topic.title)
        return None, "AI 洞察尚未生成"
    if cached["status"] == "success" and cached["detail"] is not None:
        logger.info("通知阶段读取 AI 洞察成功缓存: topic_id=%s title=%s", topic.id, topic.title)
        return cached["detail"], ""
    error_message = str(cached["error_message"] or "AI 洞察生成失败")
    logger.info(
        "通知阶段读取 AI 洞察失败缓存: topic_id=%s title=%s error=%s",
        topic.id,
        topic.title,
        error_message,
    )
    return None, error_message


def _fetch_business_topics(
    config: AppConfig,
    session: requests.Session,
    repository: AppRepository,
) -> FetchTopicsResult:
    sources = build_weibo_sources(
        config.weibo_source_order,
        session,
        config.fetch_timeout_seconds,
        weibo_official_timeout=config.weibo_official_timeout_seconds,
        weibo_official_visitor_timeout=config.weibo_official_visitor_timeout_seconds,
        weibo_official_realtime_timeout=config.weibo_official_realtime_timeout_seconds,
        weibo_official_max_retries=config.weibo_official_max_retries,
    )
    tagged_failures: list[str] = []
    untagged_successes: list[str] = []

    for source in sources:
        started_at = now_iso()
        logger.info(
            "数据源尝试开始: source=%s supports_tags=%s timeout_seconds=%s",
            source.id,
            source.supports_tags,
            source.timeout,
        )
        try:
            source_timer = time.perf_counter()
            result = source.fetch()
        except SourceError as exc:
            error_message = redact_sensitive_text(exc)
            logger.warning("数据源尝试失败: source=%s error=%s", source.id, error_message)
            repository.record_fetch_run(
                channel_id=WEIBO_CHANNEL_ID,
                source_id=source.id,
                started_at=started_at,
                finished_at=now_iso(),
                ok=False,
                message=error_message,
                topic_count=0,
                supports_tags=source.supports_tags,
            )
            if source.supports_tags:
                tagged_failures.append(f"{source.id}: {error_message}")
            continue

        tracked_topics = filter_track_topics(result.topics, config.track_tags)
        tracked_topics = _enrich_official_source_material(config, session, tracked_topics)
        tag_counts = Counter(topic.tag or "无标记" for topic in result.topics)
        tracked_tag_counts = Counter(topic.tag or "无标记" for topic in tracked_topics)
        saved_topics = repository.save_topics(tracked_topics, config.tag_recurrence_hours)
        repository.record_fetch_run(
            channel_id=WEIBO_CHANNEL_ID,
            source_id=result.source_id,
            started_at=started_at,
            finished_at=now_iso(),
            ok=True,
            message="ok",
            topic_count=len(result.topics),
            supports_tags=result.supports_tags,
        )
        logger.info(
            "数据源尝试成功: source=%s fetched=%s tracked=%s supports_tags=%s duration_ms=%.1f tag_counts=%s tracked_tag_counts=%s",
            result.source_id,
            len(result.topics),
            len(saved_topics),
            result.supports_tags,
            (time.perf_counter() - source_timer) * 1000,
            _format_counter(tag_counts),
            _format_counter(tracked_tag_counts),
        )

        if result.supports_tags and saved_topics:
            return FetchTopicsResult(saved_topics, result.source_id, "", len(result.topics))

        if result.supports_tags and result.topics:
            logger.info(
                "数据源 %s 获取成功，但没有命中 TRACK_TAGS=%s 的热点",
                result.source_id,
                ",".join(config.track_tags) if config.track_tags else "未配置",
            )
            return FetchTopicsResult([], result.source_id, "", len(result.topics))

        if result.supports_tags:
            tagged_failures.append(f"{result.source_id}: 返回 0 条")
        else:
            untagged_successes.append(f"{result.source_id}: {len(result.topics)} 条")

    if untagged_successes:
        health_message = (
            "所有带标记数据源不可用或为空；无标记源可用但不会触发推送。"
            f" 带标记源状态：{'; '.join(tagged_failures) or '无'}。"
            f" 无标记源：{'; '.join(untagged_successes)}。"
        )
        logger.warning("%s", health_message)
        return FetchTopicsResult([], None, "", 0)
    else:
        health_message = (
            "所有带标记数据源不可用或为空，且无标记兜底源也未成功。"
            f" 带标记源状态：{'; '.join(tagged_failures) or '无'}。"
        )
    logger.error("%s", health_message)
    return FetchTopicsResult([], None, health_message, 0)


def _enrich_official_source_material(
    config: AppConfig,
    session: requests.Session,
    topics: list[TopicCandidate],
) -> list[TopicCandidate]:
    if not topics:
        return topics
    timeout = max(1, min(config.weibo_official_timeout_seconds, config.fetch_timeout_seconds))
    mobile_timeout = max(1, min(config.weibo_mobile_timeout_seconds, config.fetch_timeout_seconds))
    enriched: list[TopicCandidate] = []
    enriched_count = 0
    excerpt_count = 0
    cover_count = 0
    official_post_count = 0
    mobile_enriched_count = 0
    mobile_post_count = 0
    started = time.perf_counter()
    for topic in topics:
        official_material = fetch_weibo_official_detail_material(session, topic.url, timeout)
        official_posts = official_material.realtime_posts
        mobile_material = (
            fetch_weibo_mobile_search_material(
                session,
                topic.title,
                mobile_timeout,
                max_posts=config.weibo_mobile_max_posts,
                max_retries=config.weibo_mobile_max_retries,
            )
            if config.weibo_mobile_enabled and not official_posts
            else None
        )
        mobile_excerpt = mobile_material.source_excerpt if mobile_material is not None else ""
        mobile_cover = mobile_material.cover_image_url if mobile_material is not None else ""
        mobile_posts = mobile_material.realtime_posts if mobile_material is not None else ()
        realtime_posts = official_posts or mobile_posts
        source_excerpt = official_material.source_excerpt or mobile_excerpt
        source_excerpt_origin = (
            "official" if official_material.source_excerpt or official_posts else "mobile" if mobile_excerpt else ""
        )
        cover_image_url = official_material.cover_image_url or mobile_cover

        if not source_excerpt and not cover_image_url and not realtime_posts:
            enriched.append(topic)
            continue
        enriched_count += 1
        if official_posts:
            official_post_count += len(official_posts)
        if mobile_excerpt or mobile_posts:
            mobile_enriched_count += 1
            mobile_post_count += len(mobile_posts)
        if source_excerpt:
            excerpt_count += 1
        if cover_image_url:
            cover_count += 1
        enriched.append(
            topic.with_source_material(
                source_excerpt=source_excerpt,
                cover_image_url=cover_image_url,
                realtime_posts=realtime_posts,
                source_excerpt_origin=source_excerpt_origin,
                official_context=official_material.source_excerpt,
                mobile_context=mobile_excerpt,
            )
        )
    logger.info(
        (
            "微博原始材料补充完成: topics=%s enriched=%s source_excerpt=%s cover_image=%s "
            "official_posts=%s mobile_enriched=%s mobile_posts=%s duration_ms=%.1f"
        ),
        len(topics),
        enriched_count,
        excerpt_count,
        cover_count,
        official_post_count,
        mobile_enriched_count,
        mobile_post_count,
        (time.perf_counter() - started) * 1000,
    )
    return enriched


def _send_health_alert_if_needed(
    config: AppConfig,
    repository: AppRepository,
    session: requests.Session,
    message: str,
) -> bool:
    if not config.wecom.health_alerts:
        logger.info("健康告警未启用，跳过发送")
        return False
    if not config.wecom.health_webhook_url:
        logger.info("企微机器人健康告警 webhook 未配置，跳过外部发送")
        return False
    alert_key = "tagged_sources_unavailable_alert"
    if not repository.should_send_health_alert(alert_key, config.health_alert_cooldown_minutes):
        logger.info("健康告警仍在冷却期内，跳过发送")
        return False
    result = send_wecom_robot_health_alert(
        webhook_url=config.wecom.health_webhook_url,
        message=message,
        timeout_seconds=config.wecom.health_webhook_timeout_seconds,
        session=session,
    )
    if result.ok:
        repository.mark_health_alert_sent(alert_key)
        logger.info("企微机器人健康告警发送成功")
        return True
    logger.warning("企微机器人健康告警发送失败: error=%s", result.error_message or "-")
    return False


def _format_counter(counter: Counter[str]) -> str:
    if not counter:
        return "无"
    return ",".join(f"{key}:{value}" for key, value in sorted(counter.items()))


def _format_delivery_targets(targets: list[tuple[str, str]]) -> str:
    return ",".join(f"{provider}:{mask_external_target(provider, target)}" for provider, target in targets) or "无"
