import unittest

import requests

from backend.app.services.ingestion.weibo_official import (
    WeiboOfficialHotTopicSource,
    build_weibo_document_headers,
    extract_official_detail_map,
    initialize_weibo_visitor,
    normalize_official_detail_url,
    parse_weibo_official_cover_image_url,
    parse_weibo_official_detail_context,
    parse_weibo_official_detail_material,
    parse_weibo_official_top_html,
)
from backend.app.services.ingestion.weibo_sources import (
    NsuuuHotTopicSource,
    XkHotTopicSource,
    XunjinluHotTopicSource,
)


class SourceParsingTests(unittest.TestCase):
    def test_xk_source_parses_tagged_topics(self) -> None:
        source = XkHotTopicSource(requests.Session(), timeout=1)
        topics = source.parse_payload(
            {
                "code": 200,
                "data": [
                    {"title": "热点 A", "hotnum": 120000, "tag": "爆"},
                    {"title": "热点 B", "hotnum": 90000, "tag": "新"},
                ],
            },
            "2026-06-09T18:00:00+08:00",
        )

        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0].tag, "爆")
        self.assertEqual(topics[0].rank, 1)
        self.assertEqual(topics[0].score, 120000)
        self.assertIn("s.weibo.com", topics[0].url)

    def test_xunjinlu_source_normalizes_zero_based_rank(self) -> None:
        source = XunjinluHotTopicSource(requests.Session(), timeout=1)
        topics = source.parse_payload(
            {
                "code": 200,
                "data": {
                    "list": [
                        {
                            "rank": 0,
                            "title": "热点 A",
                            "hot" "_value": 120000,
                            "label": "热",
                            "url": "https://s.weibo.com/weibo?q=A",
                        }
                    ]
                },
            },
            "2026-06-09T18:00:00+08:00",
        )

        self.assertEqual(topics[0].rank, 1)
        self.assertEqual(topics[0].tag, "热")

    def test_untagged_source_keeps_tag_empty(self) -> None:
        source = NsuuuHotTopicSource(requests.Session(), timeout=1)
        topics = source.parse_payload(
            {
                "code": 200,
                "data": [
                    {
                        "index": 1,
                        "title": "普通热搜",
                        "hot": "190万",
                        "url": "https://s.weibo.com/weibo?q=test",
                    }
                ],
            },
            "2026-06-09T18:00:00+08:00",
        )

        self.assertFalse(source.supports_tags)
        self.assertEqual(topics[0].tag, "")
        self.assertEqual(topics[0].score, 1900000)

    def test_official_source_keeps_numeric_rank_and_skips_pinned_or_ads(self) -> None:
        html = """
        <table>
          <tr>
            <td class="td-01 ranktop"></td>
            <td class="td-02"><a href="/weibo?q=pinned">置顶热点</a><span>1000</span></td>
            <td class="td-03"><i>热</i></td>
          </tr>
          <tr>
            <td class="td-01 ranktop ranktop1">1</td>
            <td class="td-02"><a href="/weibo?q=a">热点 A</a><span>1103106</span></td>
            <td class="td-03"><i>爆</i></td>
          </tr>
          <tr>
            <td class="td-01">2</td>
            <td class="td-02"><a href="javascript:void(0)">广告位</a><span>123</span></td>
            <td class="td-03"><i>热</i></td>
          </tr>
          <tr>
            <td class="td-01">3</td>
            <td class="td-02"><a href="/weibo?q=b">热点 B</a> 99万</td>
            <td class="td-03"><i>热</i></td>
          </tr>
        </table>
        """

        topics = parse_weibo_official_top_html(
            html,
            "2026-06-09T18:00:00+08:00",
            detail_map={"热点 A": "https://weibo.com/a/hot/abc_0.html?type=grab"},
        )

        self.assertEqual([topic.title for topic in topics], ["热点 A", "热点 B"])
        self.assertEqual(topics[0].rank, 1)
        self.assertEqual(topics[0].score, 1103106)
        self.assertEqual(topics[0].tag, "爆")
        self.assertEqual(topics[0].url, "https://weibo.com/a/hot/abc_0.html?type=grab")
        self.assertEqual(topics[1].rank, 3)
        self.assertEqual(topics[1].score, 990000)
        self.assertEqual(topics[1].tag, "热")
        self.assertIn("s.weibo.com/weibo", topics[1].url)

    def test_official_detail_map_normalizes_relative_urls(self) -> None:
        html = """
        <a href="0e135fc1d10403f5_0.html?type=grab"><span class="list_title_s">热点 A</span></a>
        <a href="/a/hot/c39e81822ef8700d_0.html?type=grab"><span class="list_title_s">热点 B</span></a>
        <a href="/a/hot/hashtag_0.html?type=grab"><span class="list_title_s">#热点 C#</span></a>
        <a href="/a/hot/realtime/c39e81822ef8700d_0.html?type=grab"><span class="list_title_s">错误链接</span></a>
        """

        detail_map = extract_official_detail_map(html)

        self.assertEqual(
            detail_map["热点 A"],
            "https://weibo.com/a/hot/0e135fc1d10403f5_0.html?type=grab",
        )
        self.assertEqual(
            detail_map["热点 B"],
            "https://weibo.com/a/hot/c39e81822ef8700d_0.html?type=grab",
        )
        self.assertEqual(
            detail_map["热点 C"],
            "https://weibo.com/a/hot/hashtag_0.html?type=grab",
        )
        self.assertNotIn("错误链接", detail_map)
        self.assertEqual(
            normalize_official_detail_url("0e135fc1d10403f5_0.html?type=grab"),
            "https://weibo.com/a/hot/0e135fc1d10403f5_0.html?type=grab",
        )

    def test_official_visitor_cookie_initialization_does_not_hardcode_cookie_header(self) -> None:
        session = FakeWeiboSession()

        initialize_weibo_visitor(
            session,
            "https://s.weibo.com/top/summary?cate=realtimehot",
            'var request_id = "req-1";',
            "https://passport.weibo.com/visitor/visitor",
            5,
        )

        self.assertEqual(session.posts[0]["url"], "https://passport.weibo.com/visitor/genvisitor2")
        self.assertEqual(session.posts[0]["data"]["request_id"], "req-1")
        self.assertEqual(session.gets[0]["url"].split("?")[0], "https://login.sina.com.cn/visitor/visitor")
        headers = build_weibo_document_headers(
            "https://s.weibo.com/top/summary?cate=realtimehot",
            referer="https://s.weibo.com/top/summary?cate=realtimehot",
        )
        self.assertNotIn("Cookie", headers)

    def test_official_detail_context_extracts_public_page_snippets(self) -> None:
        html = """
        <html><head><title>热点 A_微博</title></head>
        <body>
          <div class="list_title_s">热点 A</div>
          <div class="des_main">官方详情摘要内容</div>
        </body></html>
        """

        context = parse_weibo_official_detail_context(html)

        self.assertIn("热点 A", context)
        self.assertIn("官方详情摘要内容", context)
        self.assertIn("\n\n", context)

    def test_official_detail_context_keeps_paragraphs_and_deduplicates(self) -> None:
        html = """
        <html><body>
          <div class="list_title_s">热点 A</div>
          <div class="des_main">
            <p>第一段事实。</p>
            <p>第二段背景。</p>
            <p>第二段背景。</p>
          </div>
          <div class="des_main">展开</div>
        </body></html>
        """

        context = parse_weibo_official_detail_context(html)

        self.assertEqual(context.count("第二段背景。"), 1)
        self.assertEqual(context.split("\n\n"), ["热点 A", "第一段事实。", "第二段背景。"])

    def test_official_detail_context_truncates_long_excerpt(self) -> None:
        html = f"""
        <html><body>
          <div class="des_main"><p>{"长内容" * 100}</p></div>
        </body></html>
        """

        context = parse_weibo_official_detail_context(html, max_chars=80)

        self.assertLessEqual(len(context), 80)
        self.assertTrue(context.endswith("…"))

    def test_official_detail_material_extracts_cover_image(self) -> None:
        html = """
        <html><body>
          <div id="pl_unlogin_home_focuspic">
            <div><div><div class="pic W_piccut_v">
              <img src="//wx2.sinaimg.cn/orj480/example.jpg" />
            </div></div></div>
          </div>
          <div class="list_title_s">热点 A</div>
          <div class="des_main">官方详情摘要内容</div>
        </body></html>
        """

        material = parse_weibo_official_detail_material(html)

        self.assertEqual(material.cover_image_url, "https://wx2.sinaimg.cn/orj480/example.jpg")
        self.assertIn("官方详情摘要内容", material.source_excerpt)
        self.assertEqual(parse_weibo_official_cover_image_url(html), material.cover_image_url)

    def test_official_source_retries_top_page_once(self) -> None:
        session = FakeOfficialFetchSession(
            [
                requests.Timeout("passport read timeout"),
                FakeOfficialResponse(_official_top_html("热点 A", "爆")),
                FakeOfficialResponse(
                    '<a href="abc_0.html?type=grab"><span class="list_title_s">热点 A</span></a>',
                    url="https://weibo.com/a/hot/realtime",
                ),
            ]
        )
        source = WeiboOfficialHotTopicSource(
            session,
            timeout=5,
            visitor_timeout=4,
            realtime_timeout=3,
            max_retries=2,
        )

        result = source.fetch()

        self.assertEqual(result.source_id, "weibo_official")
        self.assertEqual(result.topics[0].title, "热点 A")
        self.assertEqual(result.topics[0].url, "https://weibo.com/a/hot/abc_0.html?type=grab")
        self.assertEqual([call["timeout"] for call in session.gets], [5, 5, 3])

    def test_official_source_keeps_top_page_when_realtime_detail_map_fails(self) -> None:
        session = FakeOfficialFetchSession(
            [
                FakeOfficialResponse(_official_top_html("热点 A", "爆")),
                requests.Timeout("realtime timeout"),
            ]
        )
        source = WeiboOfficialHotTopicSource(session, timeout=5, realtime_timeout=3, max_retries=1)

        result = source.fetch()

        self.assertEqual(len(result.topics), 1)
        self.assertEqual(result.topics[0].title, "热点 A")
        self.assertIn("https://s.weibo.com/weibo", result.topics[0].url)

class FakeWeiboResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.url = "https://login.sina.com.cn/visitor/visitor"

    def raise_for_status(self) -> None:
        return None


class FakeWeiboSession:
    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append({"url": url, "data": data, "timeout": timeout, "headers": headers})
        return FakeWeiboResponse(
            'window.visitor_gray_callback && visitor_gray_callback({"retcode":20000000,'
            '"data":{"sub":"sub-value","subp":"subp-value"}})'
        )

    def get(self, url, timeout=None, headers=None, allow_redirects=None):
        self.gets.append(
            {"url": url, "timeout": timeout, "headers": headers, "allow_redirects": allow_redirects}
        )
        return FakeWeiboResponse("")


class FakeOfficialResponse:
    def __init__(self, text: str, *, url: str = "https://s.weibo.com/top/summary?cate=realtimehot") -> None:
        self.text = text
        self.url = url
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


class FakeOfficialFetchSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.gets: list[dict] = []

    def get(self, url, timeout=None, headers=None, allow_redirects=None):
        self.gets.append(
            {"url": url, "timeout": timeout, "headers": headers, "allow_redirects": allow_redirects}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _official_top_html(title: str, tag: str) -> str:
    return f"""
    <table>
      <tr>
        <td class="td-01">1</td>
        <td class="td-02"><a href="/weibo?q={title}">{title}</a><span>100万</span></td>
        <td class="td-03"><i>{tag}</i></td>
      </tr>
    </table>
    """


if __name__ == "__main__":
    unittest.main()
