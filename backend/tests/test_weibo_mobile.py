import unittest

from backend.app.domain.models import weibo_mobile_search_url
from backend.app.services.ingestion.weibo_official import parse_weibo_mobile_search_cards


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


if __name__ == "__main__":
    unittest.main()
