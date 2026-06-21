from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import SourceResult, TopicCandidate, WeiboRealtimePost, now_iso, weibo_search_url
from backend.app.services.ingestion.weibo_sources import HotTopicSource, SourceError

logger = logging.getLogger(__name__)

WEIBO_TOP_URL = "https://s.weibo.com/top/summary?cate=realtimehot"
WEIBO_REALTIME_URL = "https://weibo.com/a/hot/realtime"
WEIBO_DETAIL_PREFIX = "https://weibo.com/a/hot/"
WEIBO_MOBILE_HOME_URL = "https://m.weibo.cn/"
WEIBO_MOBILE_SEARCH_API = "https://m.weibo.cn/api/container/getIndex"
WEIBO_MOBILE_VISITOR_URL = "https://visitor.passport.weibo.cn/visitor/genvisitor2"
WEIBO_MOBILE_CONTAINER_TEMPLATE = "100103type=1&q={keyword}"
WEIBO_MOBILE_FRESHNESS_DAYS = 7

VISITOR_URL = "https://passport.weibo.com/visitor/genvisitor2"
CROSSDOMAIN_URL = "https://login.sina.com.cn/visitor/visitor"
VISITOR_CALLBACK = "visitor_gray_callback"

WEIBO_BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
    "Priority": "u=0, i",
    "Sec-CH-UA": '"Microsoft Edge";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
    ),
}

WEIBO_MOBILE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "MWeibo-Pwa": "1",
    "Referer": "https://m.weibo.cn/",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(frozen=True)
class WeiboOfficialDetailMaterial:
    source_excerpt: str = ""
    cover_image_url: str = ""


@dataclass(frozen=True)
class WeiboMobileSearchMaterial:
    source_excerpt: str = ""
    cover_image_url: str = ""
    realtime_posts: tuple[WeiboRealtimePost, ...] = ()


@dataclass(frozen=True)
class WeiboMobileSearchMetrics:
    ok: object = ""
    cards: int = 0
    mblogs: int = 0
    text_posts: int = 0
    keyword_match: int = 0
    fresh_posts: int = 0


class WeiboOfficialHotTopicSource(HotTopicSource):
    id = "weibo_official"
    url = WEIBO_TOP_URL
    supports_tags = True

    def __init__(
        self,
        session: requests.Session,
        timeout: int,
        *,
        visitor_timeout: int | None = None,
        realtime_timeout: int | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(session, timeout)
        self.visitor_timeout = visitor_timeout or timeout
        self.realtime_timeout = realtime_timeout or timeout
        self.max_retries = max(max_retries, 1)

    def fetch(self) -> SourceResult:
        started = time.perf_counter()
        fetched_at = now_iso()
        try:
            html = self._fetch_top_html()
        except Exception as exc:
            raise SourceError(f"{self.id} 请求失败: {redact_sensitive_text(exc)}") from exc

        detail_map: dict[str, str] = {}
        realtime_started = time.perf_counter()
        try:
            realtime_html = fetch_weibo_document(
                self.session,
                WEIBO_REALTIME_URL,
                self.realtime_timeout,
                referer=self.url,
                visitor_timeout=self.visitor_timeout,
                stage="realtime_detail_map",
            )
            detail_map = extract_official_detail_map(realtime_html)
            logger.info(
                "微博官方详情链接页解析完成: matched_titles=%s duration_ms=%.1f",
                len(detail_map),
                (time.perf_counter() - realtime_started) * 1000,
            )
        except Exception as exc:
            logger.warning("微博官方详情链接页获取失败，本轮仅使用搜索页链接: %s", redact_sensitive_text(exc))

        topics = parse_weibo_official_top_html(html, fetched_at, detail_map=detail_map)
        if not topics:
            raise SourceError(f"{self.id} 未解析到带数字排名的热搜")
        detail_matched_count = sum(1 for topic in topics if is_weibo_official_detail_url(topic.url))
        logger.info(
            "微博官方热榜解析完成: topics=%s detail_url_matched=%s search_url_fallback=%s duration_ms=%.1f",
            len(topics),
            detail_matched_count,
            len(topics) - detail_matched_count,
            (time.perf_counter() - started) * 1000,
        )
        return SourceResult(
            source_id=self.id,
            topics=topics,
            supports_tags=self.supports_tags,
            fetched_at=fetched_at,
        )

    def _fetch_top_html(self) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            started = time.perf_counter()
            try:
                html = fetch_weibo_document(
                    self.session,
                    self.url,
                    self.timeout,
                    referer=self.url,
                    visitor_timeout=self.visitor_timeout,
                    stage=f"top_attempt_{attempt}",
                )
                logger.info(
                    "微博官方热榜页面获取成功: attempt=%s/%s duration_ms=%.1f chars=%s",
                    attempt,
                    self.max_retries,
                    (time.perf_counter() - started) * 1000,
                    len(html),
                )
                return html
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "微博官方热榜页面获取失败: attempt=%s/%s duration_ms=%.1f error=%s",
                    attempt,
                    self.max_retries,
                    (time.perf_counter() - started) * 1000,
                    redact_sensitive_text(exc),
                )
        raise last_error or SourceError("微博官方热榜页面获取失败")

    def parse_payload(self, payload: dict, fetched_at: str) -> list[TopicCandidate]:
        raise NotImplementedError("weibo_official 使用 HTML 页面，不支持 JSON payload")


def fetch_weibo_document(
    session: requests.Session,
    url: str,
    timeout: int,
    *,
    referer: str = "",
    visitor_timeout: int | None = None,
    stage: str = "document",
) -> str:
    started = time.perf_counter()
    response = session.get(
        url,
        timeout=timeout,
        headers=build_weibo_document_headers(url, referer=referer or url),
        allow_redirects=True,
    )
    response.raise_for_status()
    logger.info(
        "微博官方页面请求完成: stage=%s step=initial_get status=%s final_host=%s visitor=%s duration_ms=%.1f chars=%s",
        stage,
        getattr(response, "status_code", "-"),
        urlparse(str(response.url)).netloc,
        _is_visitor_page(response),
        (time.perf_counter() - started) * 1000,
        len(response.text or ""),
    )
    if _is_visitor_page(response):
        logger.info("微博官方页面返回访客系统，开始初始化游客 Cookie: stage=%s", stage)
        initialize_weibo_visitor(session, url, response.text, str(response.url), visitor_timeout or timeout, stage=stage)
        retry_started = time.perf_counter()
        response = session.get(
            url,
            timeout=timeout,
            headers=build_weibo_document_headers(url, referer=referer or url),
            allow_redirects=True,
        )
        response.raise_for_status()
        logger.info(
            "微博官方页面请求完成: stage=%s step=retry_after_visitor status=%s final_host=%s visitor=%s duration_ms=%.1f chars=%s",
            stage,
            getattr(response, "status_code", "-"),
            urlparse(str(response.url)).netloc,
            _is_visitor_page(response),
            (time.perf_counter() - retry_started) * 1000,
            len(response.text or ""),
        )

    if _is_visitor_page(response):
        raise SourceError("微博游客 Cookie 初始化后仍返回访客系统")
    return response.text


def initialize_weibo_visitor(
    session: requests.Session,
    target_url: str,
    visitor_html: str,
    visitor_page_url: str,
    timeout: int,
    *,
    stage: str = "document",
) -> None:
    request_id = _extract_request_id(visitor_html)
    payload = {
        "cb": VISITOR_CALLBACK,
        "ver": "20250916",
        "request_id": request_id,
        "tid": "",
        "from": "weibo",
        "webdriver": "false",
        "rid": str(int(time.time() * 1000)),
        "return_url": target_url,
    }
    visitor_started = time.perf_counter()
    response = session.post(
        VISITOR_URL,
        data=payload,
        timeout=timeout,
        headers=build_weibo_document_headers(VISITOR_URL, referer=visitor_page_url),
    )
    response.raise_for_status()
    logger.info(
        "微博游客 Cookie 初始化步骤完成: stage=%s step=genvisitor2 status=%s duration_ms=%.1f chars=%s",
        stage,
        getattr(response, "status_code", "-"),
        (time.perf_counter() - visitor_started) * 1000,
        len(response.text or ""),
    )
    data = _parse_visitor_jsonp(response.text)
    if str(data.get("retcode")) != "20000000":
        raise SourceError(f"微博游客 Cookie 初始化失败: retcode={data.get('retcode')}")
    visitor_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    sub = str(visitor_data.get("sub") or "")
    subp = str(visitor_data.get("subp") or "")
    if not sub or not subp:
        raise SourceError("微博游客 Cookie 初始化失败: 缺少 sub/subp")

    crossdomain_params = {
        "a": "crossdomain",
        "s": sub,
        "sp": subp,
        "from": "weibo",
        "_rand": str(time.time()),
        "entry": "miniblog",
        "url": target_url,
    }
    crossdomain_url = f"{CROSSDOMAIN_URL}?{urlencode(crossdomain_params)}"
    crossdomain_started = time.perf_counter()
    crossdomain_response = session.get(
        crossdomain_url,
        timeout=timeout,
        headers=build_weibo_document_headers(CROSSDOMAIN_URL, referer="https://passport.weibo.com/"),
        allow_redirects=False,
    )
    crossdomain_response.raise_for_status()
    logger.info(
        "微博游客 Cookie 初始化完成: stage=%s step=crossdomain status=%s duration_ms=%.1f",
        stage,
        getattr(crossdomain_response, "status_code", "-"),
        (time.perf_counter() - crossdomain_started) * 1000,
    )


def build_weibo_document_headers(url: str, *, referer: str = "") -> dict[str, str]:
    headers = dict(WEIBO_BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    headers["Sec-Fetch-Site"] = _sec_fetch_site(url, referer)
    return headers


def build_weibo_mobile_api_headers(
    referer: str,
    session: requests.Session | None = None,
) -> dict[str, str]:
    headers = dict(WEIBO_MOBILE_HEADERS)
    headers["Referer"] = referer
    headers["Sec-Fetch-Dest"] = "empty"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = "same-origin"
    xsrf_token = _session_cookie(session, "XSRF-TOKEN", host="m.weibo.cn") if session is not None else ""
    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token
    return headers


def build_weibo_mobile_visitor_headers(referer: str) -> dict[str, str]:
    headers = dict(WEIBO_BROWSER_HEADERS)
    headers["Accept"] = "*/*"
    headers["Referer"] = referer
    headers["Sec-Fetch-Dest"] = "empty"
    headers["Sec-Fetch-Mode"] = "cors"
    headers["Sec-Fetch-Site"] = _sec_fetch_site(WEIBO_MOBILE_VISITOR_URL, referer)
    return headers


def parse_weibo_official_top_html(
    html: str,
    fetched_at: str,
    *,
    detail_map: dict[str, str] | None = None,
) -> list[TopicCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    detail_map = detail_map or {}
    topics: list[TopicCandidate] = []

    for row in soup.select("tr"):
        rank_cell = _find_cell_by_class(row, "td-01")
        title_cell = _find_cell_by_class(row, "td-02")
        if rank_cell is None or title_cell is None:
            continue

        rank = _parse_numeric_rank(rank_cell.get_text(" ", strip=True))
        if rank is None:
            continue

        title_anchor = title_cell.find("a", href=True)
        if not isinstance(title_anchor, Tag):
            continue
        href = str(title_anchor.get("href") or "").strip()
        if not href or href.startswith("javascript:"):
            continue

        title = _normalize_topic_title(title_anchor.get_text(" ", strip=True))
        if not title:
            continue

        tag_cell = _find_cell_by_class(row, "td-03")
        tag = _normalize_tag(tag_cell.get_text("", strip=True) if tag_cell is not None else "")
        score = _extract_score(title_cell.get_text(" ", strip=True), title)
        detail_url = detail_map.get(title)
        fallback_url = _normalize_search_url(href, title)

        topics.append(
            TopicCandidate.from_raw(
                title=title,
                rank=rank,
                score=score,
                tag=tag,
                url=detail_url or fallback_url,
                source_id=WeiboOfficialHotTopicSource.id,
                fetched_at=fetched_at,
            )
        )

    return topics


def extract_official_detail_map(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        detail_url = normalize_official_detail_url(str(anchor.get("href") or ""))
        if not detail_url:
            continue
        title = _extract_detail_title(anchor)
        if not title:
            continue
        mapping.setdefault(title, detail_url)
    return mapping


def normalize_official_detail_url(href: str) -> str:
    href = unescape(href).strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    if href.startswith("/a/hot/"):
        href = urljoin("https://weibo.com", href)
    elif re.fullmatch(r"[^/?#]+\.html(?:\?type=grab)?", href):
        href = f"{WEIBO_DETAIL_PREFIX}{href}"
    elif href.startswith("http"):
        href = href
    else:
        return ""

    parsed = urlparse(href)
    if parsed.netloc != "weibo.com":
        return ""
    path = parsed.path
    if not path.startswith("/a/hot/") or path.startswith("/a/hot/realtime/"):
        return ""
    if not path.endswith(".html"):
        return ""
    query = parsed.query or "type=grab"
    return f"https://weibo.com{path}?{query}"


def is_weibo_official_detail_url(url: str) -> bool:
    return bool(normalize_official_detail_url(url) == url)


def fetch_weibo_official_detail_context(
    session: requests.Session,
    url: str,
    timeout: int,
    *,
    max_chars: int = 1200,
) -> str:
    if not is_weibo_official_detail_url(url):
        return ""
    try:
        html = fetch_weibo_document(session, url, timeout, referer=WEIBO_REALTIME_URL)
    except Exception as exc:
        logger.info("微博官方详情页上下文获取失败: %s", exc)
        return ""
    return parse_weibo_official_detail_context(html, max_chars=max_chars)


def fetch_weibo_official_detail_material(
    session: requests.Session,
    url: str,
    timeout: int,
    *,
    max_excerpt_chars: int = 1200,
) -> WeiboOfficialDetailMaterial:
    if not is_weibo_official_detail_url(url):
        return WeiboOfficialDetailMaterial()
    try:
        html = fetch_weibo_document(session, url, timeout, referer=WEIBO_REALTIME_URL, stage="official_detail_material")
    except Exception as exc:
        logger.info("微博官方详情页原始材料获取失败: url=%s error=%s", url, redact_sensitive_text(exc))
        return WeiboOfficialDetailMaterial()
    return parse_weibo_official_detail_material(html, max_excerpt_chars=max_excerpt_chars)


def fetch_weibo_mobile_search_material(
    session: requests.Session,
    title: str,
    timeout: int,
    *,
    max_posts: int = 3,
    max_excerpt_chars: int = 1200,
    max_retries: int = 2,
) -> WeiboMobileSearchMaterial:
    keyword = _normalize_topic_title(title)
    if not keyword or max_posts <= 0:
        return WeiboMobileSearchMaterial()

    container_id = WEIBO_MOBILE_CONTAINER_TEMPLATE.format(keyword=keyword)
    search_url = _mobile_search_page_url(keyword)
    params = {"containerid": container_id, "page_type": "searchall"}
    ensure_weibo_mobile_visitor(session, search_url, timeout, title=title)
    login_retry_initialized = False
    max_attempts = max(max_retries, 1)
    attempt = 1
    while attempt <= max_attempts:
        try:
            response = session.get(
                WEIBO_MOBILE_SEARCH_API,
                params=params,
                timeout=timeout,
                headers=build_weibo_mobile_api_headers(search_url, session),
            )
            if _is_mobile_login_required_response(response):
                logger.info(
                    (
                        "微博移动端词页解析完成: title=%s attempt=%s/%s status=%s ok=%s "
                        "cards=%s mblogs=%s text_posts=%s keyword_match=%s fresh_posts=%s reason=login_required_retry"
                    ),
                    title,
                    attempt,
                    max_attempts,
                    getattr(response, "status_code", "-"),
                    "-",
                    0,
                    0,
                    0,
                    0,
                    0,
                )
                if not login_retry_initialized:
                    login_retry_initialized = ensure_weibo_mobile_visitor(
                        session,
                        search_url,
                        timeout,
                        title=title,
                        force=True,
                    )
                    if login_retry_initialized:
                        if attempt >= max_attempts:
                            max_attempts += 1
                        attempt += 1
                        continue
                attempt += 1
                continue
            response.raise_for_status()
            payload = response.json()
            metrics = inspect_weibo_mobile_search_payload(payload, keyword=keyword)
            if _is_mobile_login_required_payload(payload):
                logger.info(
                    (
                        "微博移动端词页解析完成: title=%s attempt=%s/%s status=%s ok=%s "
                        "cards=%s mblogs=%s text_posts=%s keyword_match=%s fresh_posts=%s reason=login_required_retry"
                    ),
                    title,
                    attempt,
                    max_attempts,
                    getattr(response, "status_code", "-"),
                    metrics.ok,
                    metrics.cards,
                    metrics.mblogs,
                    metrics.text_posts,
                    metrics.keyword_match,
                    metrics.fresh_posts,
                )
                if not login_retry_initialized:
                    login_retry_initialized = ensure_weibo_mobile_visitor(
                        session,
                        search_url,
                        timeout,
                        title=title,
                        force=True,
                    )
                    if login_retry_initialized:
                        if attempt >= max_attempts:
                            max_attempts += 1
                        attempt += 1
                        continue
                attempt += 1
                continue
            material = parse_weibo_mobile_search_cards(
                payload,
                keyword=keyword,
                max_posts=max_posts,
                max_excerpt_chars=max_excerpt_chars,
            )
            logger.info(
                (
                    "微博移动端词页解析完成: title=%s attempt=%s/%s status=%s ok=%s "
                    "cards=%s mblogs=%s text_posts=%s keyword_match=%s fresh_posts=%s reason=%s"
                ),
                title,
                attempt,
                max_attempts,
                getattr(response, "status_code", "-"),
                metrics.ok,
                metrics.cards,
                metrics.mblogs,
                metrics.text_posts,
                metrics.keyword_match,
                metrics.fresh_posts,
                _mobile_material_reason(material, metrics, keyword),
            )
            if material.source_excerpt or material.realtime_posts or material.cover_image_url:
                return material
        except Exception as exc:
            logger.info(
                "微博移动端词页获取失败: title=%s attempt=%s/%s error=%s",
                title,
                attempt,
                max_attempts,
                redact_sensitive_text(exc),
            )
        attempt += 1
    return WeiboMobileSearchMaterial()


def ensure_weibo_mobile_visitor(
    session: requests.Session,
    search_url: str,
    timeout: int,
    *,
    title: str = "",
    force: bool = False,
) -> bool:
    if not force and _has_weibo_mobile_visitor_cookie(session):
        logger.info("微博移动端游客 Cookie 复用: title=%s reason=visitor_reused", title or "-")
        return True
    try:
        initialize_weibo_mobile_visitor(session, search_url, timeout)
    except Exception as exc:
        logger.info(
            "微博移动端游客 Cookie 初始化失败，继续降级: title=%s reason=visitor_failed error=%s",
            title or "-",
            redact_sensitive_text(exc),
        )
        return False
    logger.info("微博移动端游客 Cookie 初始化成功: title=%s reason=visitor_initialized", title or "-")
    return True


def initialize_weibo_mobile_visitor(
    session: requests.Session,
    search_url: str,
    timeout: int,
    *,
    stage: str = "mobile_search",
) -> None:
    page_started = time.perf_counter()
    page_response = session.get(
        search_url,
        timeout=timeout,
        headers=build_weibo_document_headers(search_url, referer=search_url),
        allow_redirects=True,
    )
    page_response.raise_for_status()
    visitor_page_url = str(getattr(page_response, "url", search_url) or search_url)
    logger.info(
        (
            "微博移动端游客页请求完成: stage=%s status=%s final_host=%s visitor=%s "
            "duration_ms=%.1f chars=%s"
        ),
        stage,
        getattr(page_response, "status_code", "-"),
        urlparse(visitor_page_url).netloc,
        _is_visitor_page(page_response),
        (time.perf_counter() - page_started) * 1000,
        len(page_response.text or ""),
    )

    request_id = _extract_request_id(page_response.text)
    return_url = _extract_js_string_var(page_response.text, "return_url") or search_url
    payload = {
        "cb": VISITOR_CALLBACK,
        "ver": "20250916",
        "request_id": request_id,
        "tid": "",
        "from": "weibo",
        "webdriver": "false",
        "rid": str(int(time.time() * 1000)),
        "return_url": return_url,
    }

    visitor_started = time.perf_counter()
    visitor_response = session.post(
        WEIBO_MOBILE_VISITOR_URL,
        data=payload,
        timeout=timeout,
        headers=build_weibo_mobile_visitor_headers(visitor_page_url),
    )
    visitor_response.raise_for_status()
    logger.info(
        "微博移动端游客 Cookie 初始化步骤完成: stage=%s step=genvisitor2 status=%s duration_ms=%.1f chars=%s",
        stage,
        getattr(visitor_response, "status_code", "-"),
        (time.perf_counter() - visitor_started) * 1000,
        len(visitor_response.text or ""),
    )
    data = _parse_visitor_jsonp(visitor_response.text)
    if str(data.get("retcode")) != "20000000":
        raise SourceError(f"微博移动端游客 Cookie 初始化失败: retcode={data.get('retcode')}")
    visitor_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    if not str(visitor_data.get("sub") or "") or not str(visitor_data.get("subp") or ""):
        raise SourceError("微博移动端游客 Cookie 初始化失败: 缺少 sub/subp")

    back_started = time.perf_counter()
    back_response = session.get(
        return_url or search_url,
        timeout=timeout,
        headers=build_weibo_document_headers(return_url or search_url, referer=visitor_page_url),
        allow_redirects=True,
    )
    back_response.raise_for_status()
    logger.info(
        "微博移动端游客 Cookie 初始化完成: stage=%s step=return_search status=%s final_host=%s duration_ms=%.1f chars=%s",
        stage,
        getattr(back_response, "status_code", "-"),
        urlparse(str(getattr(back_response, "url", return_url or search_url))).netloc,
        (time.perf_counter() - back_started) * 1000,
        len(back_response.text or ""),
    )


def parse_weibo_mobile_search_cards(
    payload: dict,
    *,
    keyword: str = "",
    max_posts: int = 3,
    max_excerpt_chars: int = 1200,
) -> WeiboMobileSearchMaterial:
    if not isinstance(payload, dict) or payload.get("ok") != 1:
        return WeiboMobileSearchMaterial()
    cards = payload.get("data", {}).get("cards") if isinstance(payload.get("data"), dict) else None
    if not isinstance(cards, list):
        return WeiboMobileSearchMaterial()

    raw_posts = [_post_from_mblog(mblog) for mblog in _iter_mobile_mblogs(cards)]
    posts = [post for post in raw_posts if post.text]
    if keyword:
        keyword_key = _normalize_mobile_keyword(keyword)
        posts = [post for post in posts if _mobile_post_matches_keyword(post, keyword_key)]
    posts = [post for post in posts if _is_fresh_mobile_created_at(post.created_at)]
    posts = _dedupe_mobile_posts(posts)[: max(max_posts, 0)]

    parts: list[str] = []
    for post in posts:
        prefix = f"{post.author}：" if post.author else ""
        _append_unique_context_part(parts, f"{prefix}{post.text}")

    cover_image_url = _first_mobile_cover_url(cards)
    return WeiboMobileSearchMaterial(
        source_excerpt=_truncate_context("\n\n".join(parts), max_excerpt_chars),
        cover_image_url=cover_image_url,
        realtime_posts=tuple(posts),
    )


def inspect_weibo_mobile_search_payload(
    payload: dict,
    *,
    keyword: str = "",
) -> WeiboMobileSearchMetrics:
    if not isinstance(payload, dict):
        return WeiboMobileSearchMetrics(ok="-")
    ok = payload.get("ok")
    cards = payload.get("data", {}).get("cards") if isinstance(payload.get("data"), dict) else None
    if not isinstance(cards, list):
        return WeiboMobileSearchMetrics(ok=ok)

    mblogs = _iter_mobile_mblogs(cards)
    raw_posts = [_post_from_mblog(mblog) for mblog in mblogs]
    text_posts = [post for post in raw_posts if post.text]
    if keyword:
        keyword_key = _normalize_mobile_keyword(keyword)
        matched_posts = [post for post in text_posts if _mobile_post_matches_keyword(post, keyword_key)]
    else:
        matched_posts = text_posts
    fresh_posts = [post for post in matched_posts if _is_fresh_mobile_created_at(post.created_at)]
    return WeiboMobileSearchMetrics(
        ok=ok,
        cards=len(cards),
        mblogs=len(mblogs),
        text_posts=len(text_posts),
        keyword_match=len(matched_posts),
        fresh_posts=len(fresh_posts),
    )


def parse_weibo_official_detail_material(html: str, *, max_excerpt_chars: int = 1200) -> WeiboOfficialDetailMaterial:
    return WeiboOfficialDetailMaterial(
        source_excerpt=parse_weibo_official_detail_context(html, max_chars=max_excerpt_chars),
        cover_image_url=parse_weibo_official_cover_image_url(html),
    )


def parse_weibo_official_detail_context(html: str, *, max_chars: int = 1200) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    for element in soup.select(".list_title_s"):
        _append_unique_context_part(parts, element.get_text(" ", strip=True))

    for element in soup.select(".des_main"):
        for text in _extract_detail_paragraphs(element):
            _append_unique_context_part(parts, text)

    if not parts:
        title = soup.find("title")
        if title is not None:
            _append_unique_context_part(parts, title.get_text(" ", strip=True))
    return _truncate_context("\n\n".join(parts[:8]), max_chars)


def parse_weibo_official_cover_image_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    selectors = (
        "#pl_unlogin_home_focuspic div.pic.W_piccut_v img",
        "#pl_unlogin_home_focuspic img",
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
    )
    for selector in selectors:
        for element in soup.select(selector):
            if not isinstance(element, Tag):
                continue
            url = ""
            if element.name == "meta":
                url = str(element.get("content") or "")
            else:
                url = str(
                    element.get("src")
                    or element.get("data-src")
                    or element.get("data-original")
                    or ""
                )
            normalized = _normalize_image_url(url)
            if normalized:
                return normalized
    return ""


def _is_visitor_page(response: requests.Response) -> bool:
    text = response.text or ""
    response_url = str(getattr(response, "url", ""))
    return "Sina Visitor System" in text or "passport.weibo.com/visitor/visitor" in response_url


def _extract_request_id(html: str) -> str:
    match = re.search(r'var\s+request_id\s*=\s*"([^"]+)"', html)
    if not match:
        raise SourceError("微博游客页缺少 request_id")
    return match.group(1)


def _extract_js_string_var(html: str, name: str) -> str:
    match = re.search(rf'var\s+{re.escape(name)}\s*=\s*"([^"]*)"', html)
    return unescape(match.group(1)).strip() if match else ""


def _parse_visitor_jsonp(text: str) -> dict:
    match = re.search(rf"{VISITOR_CALLBACK}\((\{{.*\}})\)", text, re.DOTALL)
    if not match:
        raise SourceError("微博游客 Cookie 初始化响应不是有效 JSONP")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceError("微博游客 Cookie 初始化 JSON 解析失败") from exc
    if not isinstance(payload, dict):
        raise SourceError("微博游客 Cookie 初始化响应格式异常")
    return payload


def _sec_fetch_site(url: str, referer: str) -> str:
    if not referer:
        return "none"
    url_host = urlparse(url).netloc
    referer_host = urlparse(referer).netloc
    if url_host == referer_host:
        return "same-origin"
    if url_host.endswith("weibo.com") and referer_host.endswith("weibo.com"):
        return "same-site"
    if url_host.endswith("sina.com.cn") and (
        referer_host.endswith("weibo.com") or referer_host.endswith("sina.com.cn")
    ):
        return "same-site"
    return "cross-site"


def _find_cell_by_class(row: Tag, class_name: str) -> Tag | None:
    found = row.find(class_=lambda value: _class_contains(value, class_name))
    return found if isinstance(found, Tag) else None


def _class_contains(value: object, class_name: str) -> bool:
    if isinstance(value, str):
        return class_name in value.split()
    if isinstance(value, list):
        return class_name in value
    return False


def _parse_numeric_rank(text: str) -> int | None:
    text = _normalize_space(text)
    if not re.fullmatch(r"\d+", text):
        return None
    return int(text)


def _normalize_topic_title(title: str) -> str:
    normalized = _normalize_space(unescape(title))
    if len(normalized) > 2 and normalized.startswith("#") and normalized.endswith("#"):
        return normalized[1:-1].strip()
    return normalized


def _normalize_tag(tag: str) -> str:
    tag = _normalize_space(tag)
    return tag[:1] if tag else ""


def _extract_score(text: str, title: str) -> str:
    text = _normalize_space(text)
    if title and text.startswith(title):
        text = text[len(title) :].strip()
    matches = re.findall(r"(\d+(?:\.\d+)?万?)", text)
    return matches[-1] if matches else ""


def _normalize_search_url(href: str, title: str) -> str:
    if href.startswith("/"):
        return urljoin("https://s.weibo.com", href)
    if href.startswith("http"):
        return href
    return f"https://s.weibo.com/weibo?q={quote(title)}"


def _mobile_search_page_url(keyword: str) -> str:
    container_id = WEIBO_MOBILE_CONTAINER_TEMPLATE.format(keyword=keyword)
    return f"https://m.weibo.cn/search?containerid={quote(container_id, safe='')}"


def _normalize_image_url(url: str) -> str:
    url = unescape(url).strip()
    if not url or url.startswith("data:"):
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _is_mobile_login_required_response(response: requests.Response) -> bool:
    status_code = getattr(response, "status_code", 200)
    try:
        if int(status_code) == 432:
            return True
    except (TypeError, ValueError):
        pass
    response_url = str(getattr(response, "url", "") or "")
    return "passport.weibo.com/sso/signin" in response_url


def _is_mobile_login_required_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    url = str(payload.get("url") or "")
    return str(payload.get("ok")) == "-100" or "passport.weibo.com/sso/signin" in url


def _mobile_material_reason(
    material: WeiboMobileSearchMaterial,
    metrics: WeiboMobileSearchMetrics,
    keyword: str,
) -> str:
    if material.source_excerpt or material.realtime_posts or material.cover_image_url:
        return "material_ready"
    if str(metrics.ok) != "1":
        return "payload_not_ok"
    if metrics.cards <= 0:
        return "empty_cards"
    if metrics.mblogs <= 0:
        return "empty_mblogs"
    if metrics.text_posts <= 0:
        return "filtered_empty"
    if keyword and metrics.keyword_match <= 0:
        return "filtered_empty"
    if metrics.fresh_posts <= 0:
        return "filtered_empty"
    return "filtered_empty"


def _has_weibo_mobile_visitor_cookie(session: requests.Session | None) -> bool:
    return bool(
        _session_cookie(session, "SUB", host="m.weibo.cn")
        and _session_cookie(session, "SUBP", host="m.weibo.cn")
    )


def _session_cookie(session: requests.Session | None, name: str, *, host: str = "") -> str:
    cookies = getattr(session, "cookies", None)
    if host:
        try:
            for cookie in cookies or ():
                if getattr(cookie, "name", "") != name:
                    continue
                if _cookie_matches_host(str(getattr(cookie, "domain", "") or ""), host):
                    return str(getattr(cookie, "value", "") or "")
        except Exception:
            return ""
    getter = getattr(cookies, "get", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(name) or "")
    except Exception:
        return ""


def _cookie_matches_host(cookie_domain: str, host: str) -> bool:
    domain = cookie_domain.lstrip(".").lower()
    host = host.lower()
    return not domain or host == domain or host.endswith(f".{domain}")


def _ensure_mobile_guest_cookie(session: requests.Session, timeout: int) -> None:
    try:
        response = session.get(WEIBO_MOBILE_HOME_URL, timeout=timeout, headers=WEIBO_MOBILE_HEADERS)
        response.raise_for_status()
        logger.info("微博移动端游客 Cookie 探测完成: chars=%s", len(response.text or ""))
    except Exception as exc:
        logger.info("微博移动端游客 Cookie 探测失败，继续降级: %s", redact_sensitive_text(exc))


def _iter_mobile_mblogs(cards: list) -> list[dict]:
    result: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        mblog = card.get("mblog")
        if isinstance(mblog, dict):
            result.append(mblog)
        card_group = card.get("card_group")
        if isinstance(card_group, list):
            result.extend(_iter_mobile_mblogs(card_group))
    return result


def _post_from_mblog(mblog: dict) -> WeiboRealtimePost:
    user = mblog.get("user") if isinstance(mblog.get("user"), dict) else {}
    text = _clean_mobile_text(str(mblog.get("text") or ""))
    post_url = _mobile_status_url(mblog)
    return WeiboRealtimePost(
        author=str(user.get("screen_name") or "").strip(),
        created_at=str(mblog.get("created_at") or "").strip(),
        text=text,
        reposts=_mobile_count(mblog.get("reposts_count")),
        comments=_mobile_count(mblog.get("comments_count")),
        attitudes=_mobile_count(mblog.get("attitudes_count")),
        url=post_url,
    )


def _mobile_status_url(mblog: dict) -> str:
    scheme = str(mblog.get("scheme") or "").strip()
    if scheme.startswith("http"):
        return scheme
    bid = str(mblog.get("bid") or mblog.get("id") or "").strip()
    return f"https://m.weibo.cn/status/{quote(bid)}" if bid else ""


def _clean_mobile_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text(" ", strip=True)
    return _normalize_space(unescape(text))


def _mobile_count(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    if text in {"转发", "评论", "赞"}:
        return None
    if text.endswith("万"):
        try:
            return int(float(text[:-1]) * 10000)
        except ValueError:
            return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _dedupe_mobile_posts(posts: list[WeiboRealtimePost]) -> list[WeiboRealtimePost]:
    seen: set[str] = set()
    result: list[WeiboRealtimePost] = []
    for post in posts:
        key = post.url or post.text
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(post)
    return result


def _mobile_post_matches_keyword(post: WeiboRealtimePost, keyword_key: str) -> bool:
    if not keyword_key:
        return True
    haystack = _normalize_mobile_keyword(f"{post.author} {post.text}")
    return keyword_key in haystack


def _is_fresh_mobile_created_at(value: str) -> bool:
    text = _normalize_space(str(value or ""))
    if not text:
        return True
    if any(marker in text for marker in ("刚刚", "分钟前", "小时前", "今天", "昨天")):
        return True

    day_match = re.search(r"(\d+)\s*天前", text)
    if day_match:
        return int(day_match.group(1)) <= WEIBO_MOBILE_FRESHNESS_DAYS
    week_match = re.search(r"(\d+)\s*周前", text)
    if week_match:
        return int(week_match.group(1)) * 7 <= WEIBO_MOBILE_FRESHNESS_DAYS
    if "月前" in text or "年前" in text:
        return False

    parsed_date = _parse_mobile_created_date(text)
    if parsed_date is None:
        return True
    today = date.today()
    if parsed_date > today:
        parsed_date = parsed_date.replace(year=parsed_date.year - 1)
    return today - parsed_date <= timedelta(days=WEIBO_MOBILE_FRESHNESS_DAYS)


def _parse_mobile_created_date(value: str) -> date | None:
    match = re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", value)
    if match:
        normalized = match.group(0).replace("年", "-").replace("月", "-").replace("日", "")
        normalized = normalized.replace("/", "-")
        try:
            return datetime.strptime(normalized, "%Y-%m-%d").date()
        except ValueError:
            return None

    match = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)", value)
    if not match:
        return None
    try:
        return date(date.today().year, int(match.group(1)), int(match.group(2)))
    except ValueError:
        return None


def _first_mobile_cover_url(cards: list) -> str:
    for card in cards:
        if not isinstance(card, dict):
            continue
        mblog = card.get("mblog")
        if isinstance(mblog, dict):
            url = _cover_from_mblog(mblog)
            if url:
                return url
        card_group = card.get("card_group")
        if isinstance(card_group, list):
            url = _first_mobile_cover_url(card_group)
            if url:
                return url
    return ""


def _cover_from_mblog(mblog: dict) -> str:
    page_info = mblog.get("page_info") if isinstance(mblog.get("page_info"), dict) else {}
    for key in ("page_pic", "page_url"):
        normalized = _normalize_image_url(str(page_info.get(key) or ""))
        if normalized:
            return normalized
    pics = mblog.get("pics")
    if isinstance(pics, list):
        for pic in pics:
            if not isinstance(pic, dict):
                continue
            candidates = [
                pic.get("url"),
                pic.get("large", {}).get("url") if isinstance(pic.get("large"), dict) else "",
                pic.get("geo", {}).get("url") if isinstance(pic.get("geo"), dict) else "",
            ]
            for candidate in candidates:
                normalized = _normalize_image_url(str(candidate or ""))
                if normalized:
                    return normalized
    return ""


def _normalize_mobile_keyword(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_topic_title(value)).lower()


def _extract_detail_title(anchor: Tag) -> str:
    title_node = anchor.select_one(".list_title_s") or anchor.select_one(".card-title") or anchor
    title = _normalize_topic_title(title_node.get_text(" ", strip=True))
    if title:
        return title
    parent = anchor.parent
    if isinstance(parent, Tag):
        title_node = parent.select_one(".list_title_s") or parent.select_one(".card-title")
        if title_node is not None:
            return _normalize_topic_title(title_node.get_text(" ", strip=True))
    return ""


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_context(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 1, 0)] + "…"


def _extract_detail_paragraphs(element: Tag) -> list[str]:
    paragraphs: list[str] = []

    for node in element.find_all(["p", "li"], recursive=True):
        _append_unique_context_part(paragraphs, node.get_text(" ", strip=True))

    if not paragraphs:
        for node in element.find_all("div", recursive=True):
            if node.find(["div", "p", "li"]):
                continue
            _append_unique_context_part(paragraphs, node.get_text(" ", strip=True))

    if not paragraphs:
        text = element.get_text("\n", strip=True)
        for line in text.splitlines():
            _append_unique_context_part(paragraphs, line)

    return paragraphs


def _append_unique_context_part(parts: list[str], text: str) -> None:
    normalized = _normalize_context_part(text)
    if not normalized or _is_context_noise(normalized):
        return
    if any(normalized == part or normalized in part for part in parts):
        return
    for index, part in enumerate(parts):
        if part in normalized:
            parts[index] = normalized
            return
    parts.append(normalized)


def _normalize_context_part(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(展开|收起|查看全文)$", "", text).strip()
    return text


def _is_context_noise(text: str) -> bool:
    if text in {"展开", "收起", "查看全文", "更多", "加载中"}:
        return True
    if len(text) <= 1:
        return True
    return False
