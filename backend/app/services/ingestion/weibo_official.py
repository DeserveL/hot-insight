from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from backend.app.core.logging import redact_sensitive_text
from backend.app.domain.models import SourceResult, TopicCandidate, now_iso, weibo_search_url
from backend.app.services.ingestion.weibo_sources import HotTopicSource, SourceError

logger = logging.getLogger(__name__)

WEIBO_TOP_URL = "https://s.weibo.com/top/summary?cate=realtimehot"
WEIBO_REALTIME_URL = "https://weibo.com/a/hot/realtime"
WEIBO_DETAIL_PREFIX = "https://weibo.com/a/hot/"

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


@dataclass(frozen=True)
class WeiboOfficialDetailMaterial:
    source_excerpt: str = ""
    cover_image_url: str = ""


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


def parse_weibo_official_detail_material(html: str, *, max_excerpt_chars: int = 1200) -> WeiboOfficialDetailMaterial:
    return WeiboOfficialDetailMaterial(
        source_excerpt=parse_weibo_official_detail_context(html, max_chars=max_excerpt_chars),
        cover_image_url=parse_weibo_official_cover_image_url(html),
    )


def parse_weibo_official_detail_context(html: str, *, max_chars: int = 1200) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []
    for selector in (".list_title_s", ".des_main"):
        for element in soup.select(selector):
            text = _normalize_space(element.get_text(" ", strip=True))
            if text and text not in parts:
                parts.append(text)
    if not parts:
        title = soup.find("title")
        if title is not None:
            parts.append(_normalize_space(title.get_text(" ", strip=True)))
    return _truncate_context("\n".join(parts), max_chars)


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
