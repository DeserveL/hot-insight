import unittest

import requests

from backend.app.domain.models import weibo_mobile_search_url
from backend.app.services.ingestion.weibo_official import (
    WEIBO_MOBILE_SEARCH_API,
    WEIBO_MOBILE_VISITOR_URL,
    fetch_weibo_mobile_search_material,
    inspect_weibo_mobile_search_payload,
    parse_weibo_mobile_search_cards,
)


class WeiboMobileTests(unittest.TestCase):
    def test_mobile_search_url_encodes_container_id(self) -> None:
        url = weibo_mobile_search_url("科内重伤")

        self.assertEqual(
            url,
            "https://m.weibo.cn/search?containerid=100103type%3D1%26q%3D%E7%A7%91%E5%86%85%E9%87%8D%E4%BC%A4",
        )

    def test_parse_mobile_search_cards_extracts_posts_in_return_order(self) -> None:
        material = parse_weibo_mobile_search_cards(
            {
                "ok": 1,
                "data": {
                    "cards": [
                        {
                            "card_group": [
                                {
                                    "mblog": {
                                        "id": "1",
                                        "bid": "A1",
                                        "created_at": "刚刚",
                                        "text": "<span>科内重伤</span> 第一条 <a>全文</a>",
                                        "reposts_count": 11,
                                        "comments_count": 22,
                                        "attitudes_count": 33,
                                        "user": {"screen_name": "用户A"},
                                        "pics": [{"url": "//wx1.sinaimg.cn/orj480/a.jpg"}],
                                    }
                                },
                                {
                                    "mblog": {
                                        "id": "2",
                                        "bid": "A2",
                                        "created_at": "5分钟前",
                                        "text": "科内重伤 第二条",
                                        "user": {"screen_name": "用户B"},
                                    }
                                },
                                {
                                    "mblog": {
                                        "id": "3",
                                        "bid": "A3",
                                        "created_at": "刚刚",
                                        "text": "另一条不相关内容",
                                        "user": {"screen_name": "用户C"},
                                    }
                                },
                                {
                                    "mblog": {
                                        "id": "4",
                                        "bid": "A4",
                                        "created_at": "2024-01-01",
                                        "text": "科内重伤 旧内容",
                                        "user": {"screen_name": "用户D"},
                                    }
                                },
                            ]
                        }
                    ]
                },
            },
            keyword="科内重伤",
            max_posts=2,
        )

        self.assertEqual(len(material.realtime_posts), 2)
        self.assertEqual(material.realtime_posts[0].author, "用户A")
        self.assertEqual(material.realtime_posts[0].text, "科内重伤 第一条 全文")
        self.assertEqual(material.realtime_posts[0].reposts, 11)
        self.assertEqual(material.realtime_posts[0].url, "https://m.weibo.cn/status/A1")
        self.assertEqual(material.cover_image_url, "https://wx1.sinaimg.cn/orj480/a.jpg")
        self.assertIn("用户A：科内重伤 第一条 全文", material.source_excerpt)

    def test_parse_mobile_search_cards_returns_empty_for_failed_payload(self) -> None:
        material = parse_weibo_mobile_search_cards({"ok": -100, "msg": "blocked"})

        self.assertEqual(material.source_excerpt, "")
        self.assertEqual(material.realtime_posts, ())

    def test_mobile_payload_metrics_explain_filtering(self) -> None:
        metrics = inspect_weibo_mobile_search_payload(
            {
                "ok": 1,
                "data": {
                    "cards": [
                        {
                            "card_group": [
                                {
                                    "mblog": {
                                        "bid": "A1",
                                        "created_at": "刚刚",
                                        "text": "科内重伤 第一条",
                                        "user": {"screen_name": "用户A"},
                                    }
                                },
                                {
                                    "mblog": {
                                        "bid": "A2",
                                        "created_at": "2020-01-01",
                                        "text": "科内重伤 旧内容",
                                        "user": {"screen_name": "用户B"},
                                    }
                                },
                                {
                                    "mblog": {
                                        "bid": "A3",
                                        "created_at": "刚刚",
                                        "text": "其他内容",
                                        "user": {"screen_name": "用户C"},
                                    }
                                },
                            ]
                        }
                    ]
                },
            },
            keyword="科内重伤",
        )

        self.assertEqual(metrics.ok, 1)
        self.assertEqual(metrics.cards, 1)
        self.assertEqual(metrics.mblogs, 3)
        self.assertEqual(metrics.text_posts, 3)
        self.assertEqual(metrics.keyword_match, 2)
        self.assertEqual(metrics.fresh_posts, 1)

    def test_mobile_fetch_initializes_visitor_before_getindex(self) -> None:
        search_url = weibo_mobile_search_url("杨天真复胖")
        session = FakeMobileSession(
            get_responses=[
                FakeMobileResponse(text=_mobile_visitor_html(search_url), url="https://visitor.passport.weibo.cn/visitor/visitor"),
                FakeMobileResponse(text="<html>search</html>", url=search_url),
                FakeMobileResponse(payload=_mobile_success_payload("杨天真复胖"), url=WEIBO_MOBILE_SEARCH_API),
            ],
            post_responses=[FakeMobileResponse(text=_mobile_visitor_jsonp())],
        )

        with self.assertLogs("backend.app.services.ingestion.weibo_official", level="INFO") as logs:
            material = fetch_weibo_mobile_search_material(session, "杨天真复胖", 10, max_posts=3, max_retries=1)

        self.assertEqual(len(material.realtime_posts), 1)
        self.assertIn("杨天真复胖", material.source_excerpt)
        self.assertEqual(session.gets[0]["url"], search_url)
        self.assertEqual(session.gets[0]["params"], {})
        self.assertEqual(session.gets[2]["url"], WEIBO_MOBILE_SEARCH_API)
        self.assertEqual(session.gets[2]["params"]["page_type"], "searchall")
        self.assertEqual(session.gets[2]["headers"]["Referer"], search_url)
        self.assertEqual(session.posts[0]["url"], WEIBO_MOBILE_VISITOR_URL)
        self.assertEqual(session.posts[0]["data"]["request_id"], "mobile-req")
        self.assertNotIn("Cookie", session.posts[0]["headers"])
        joined_logs = "\n".join(logs.output)
        self.assertIn("reason=visitor_initialized", joined_logs)
        self.assertNotIn("reason=login_required_retry", joined_logs)

    def test_mobile_fetch_returns_empty_when_visitor_initialization_fails(self) -> None:
        session = FakeMobileSession(
            get_responses=[
                FakeMobileResponse(text="<html>missing request id</html>", url="https://visitor.passport.weibo.cn/visitor/visitor"),
                FakeMobileResponse(
                    payload={"ok": -100, "url": "https://passport.weibo.com/sso/signin"},
                    url=WEIBO_MOBILE_SEARCH_API,
                ),
                FakeMobileResponse(text="<html>missing request id</html>", url="https://visitor.passport.weibo.cn/visitor/visitor"),
            ]
        )

        with self.assertLogs("backend.app.services.ingestion.weibo_official", level="INFO") as logs:
            material = fetch_weibo_mobile_search_material(session, "杨天真复胖", 10, max_posts=3, max_retries=1)

        self.assertEqual(material.realtime_posts, ())
        joined_logs = "\n".join(logs.output)
        self.assertIn("reason=visitor_failed", joined_logs)
        self.assertIn("reason=login_required_retry", joined_logs)

    def test_mobile_fetch_reuses_existing_mobile_visitor_cookie(self) -> None:
        session = FakeMobileSession(
            get_responses=[FakeMobileResponse(payload=_mobile_success_payload("杨天真复胖"), url=WEIBO_MOBILE_SEARCH_API)],
            cookies={"SUB": "sub-value", "SUBP": "subp-value", "XSRF-TOKEN": "xsrf-test"},
        )

        with self.assertLogs("backend.app.services.ingestion.weibo_official", level="INFO") as logs:
            material = fetch_weibo_mobile_search_material(session, "杨天真复胖", 10, max_posts=3, max_retries=1)

        self.assertEqual(len(material.realtime_posts), 1)
        self.assertEqual(session.gets[0]["params"]["page_type"], "searchall")
        self.assertEqual(session.gets[0]["headers"]["Referer"], weibo_mobile_search_url("杨天真复胖"))
        self.assertEqual(session.gets[0]["headers"]["X-XSRF-TOKEN"], "xsrf-test")
        self.assertNotIn("Cookie", session.gets[0]["headers"])
        self.assertEqual(session.posts, [])
        self.assertIn("reason=visitor_reused", "\n".join(logs.output))

    def test_mobile_fetch_reinitializes_when_reused_cookie_is_rejected(self) -> None:
        search_url = weibo_mobile_search_url("杨天真复胖")
        session = FakeMobileSession(
            get_responses=[
                FakeMobileResponse(
                    payload={"ok": -100, "url": "https://passport.weibo.com/sso/signin"},
                    url=WEIBO_MOBILE_SEARCH_API,
                ),
                FakeMobileResponse(text=_mobile_visitor_html(search_url), url="https://visitor.passport.weibo.cn/visitor/visitor"),
                FakeMobileResponse(text="<html>search</html>", url=search_url),
                FakeMobileResponse(payload=_mobile_success_payload("杨天真复胖"), url=WEIBO_MOBILE_SEARCH_API),
            ],
            post_responses=[FakeMobileResponse(text=_mobile_visitor_jsonp())],
            cookies={"SUB": "old-sub", "SUBP": "old-subp"},
        )

        with self.assertLogs("backend.app.services.ingestion.weibo_official", level="INFO") as logs:
            material = fetch_weibo_mobile_search_material(session, "杨天真复胖", 10, max_posts=3, max_retries=1)

        self.assertEqual(len(material.realtime_posts), 1)
        self.assertEqual(session.gets[0]["url"], WEIBO_MOBILE_SEARCH_API)
        self.assertEqual(session.gets[1]["url"], search_url)
        self.assertEqual(session.gets[3]["url"], WEIBO_MOBILE_SEARCH_API)
        self.assertEqual(session.posts[0]["url"], WEIBO_MOBILE_VISITOR_URL)
        joined_logs = "\n".join(logs.output)
        self.assertIn("reason=visitor_reused", joined_logs)
        self.assertIn("reason=login_required_retry", joined_logs)
        self.assertIn("reason=visitor_initialized", joined_logs)


class FakeMobileResponse:
    def __init__(
        self,
        *,
        payload: dict | None = None,
        text: str = "",
        status_code: int = 200,
        url: str = "https://m.weibo.cn/",
    ) -> None:
        self.payload = payload
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self) -> dict:
        if self.payload is None:
            raise ValueError("no json payload")
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeMobileSession:
    def __init__(
        self,
        get_responses: list[FakeMobileResponse],
        post_responses: list[FakeMobileResponse] | None = None,
        *,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.get_responses = get_responses
        self.post_responses = post_responses or []
        self.gets: list[dict] = []
        self.posts: list[dict] = []
        self.cookies = requests.cookies.RequestsCookieJar()
        for name, value in (cookies or {}).items():
            self.cookies.set(name, value)

    def get(self, url, params=None, timeout=None, headers=None, allow_redirects=None):
        self.gets.append(
            {
                "url": url,
                "params": params or {},
                "timeout": timeout,
                "headers": headers or {},
                "allow_redirects": allow_redirects,
            }
        )
        return self.get_responses.pop(0)

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append({"url": url, "data": data or {}, "timeout": timeout, "headers": headers or {}})
        return self.post_responses.pop(0)


def _mobile_success_payload(keyword: str) -> dict:
    return {
        "ok": 1,
        "data": {
            "cards": [
                {
                    "card_group": [
                        {
                            "mblog": {
                                "bid": "M1",
                                "created_at": "刚刚",
                                "text": f"{keyword} 实时讨论",
                                "user": {"screen_name": "用户A"},
                            }
                        }
                    ]
                }
            ]
        },
    }


def _mobile_visitor_html(return_url: str) -> str:
    return f'var request_id = "mobile-req"; var return_url = "{return_url}";'


def _mobile_visitor_jsonp() -> str:
    return (
        'window.visitor_gray_callback && visitor_gray_callback({"retcode":20000000,'
        '"data":{"sub":"sub-value","subp":"subp-value"}});'
    )


if __name__ == "__main__":
    unittest.main()
