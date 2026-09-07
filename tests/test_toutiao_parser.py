import json
import unittest
import urllib.parse
from unittest.mock import patch

from src.parsers.douyin_parser import DouyinParser
from src.parsers.toutiao_parser import ToutiaoParser


class ToutiaoParserTest(unittest.TestCase):
    def test_reuses_douyin_parser(self):
        self.assertTrue(issubclass(ToutiaoParser, DouyinParser))

    @patch("src.parsers.douyin_parser.DouyinParser.fetch_html_data")
    def test_toutiao_mobile_ssr_parsing(self, mock_douyin_fetch):
        mock_douyin_fetch.return_value = None

        sample_article_info = {
            "title": "测试今日头条视频",
            "posterUrl": "https://p3.toutiaoimg.com/test_cover.jpg",
            "mediaUser": {
                "screenName": "测试创作者",
                "avatarUrl": "https://sf1.toutiaostatic.com/avatar.jpg"
            },
            "playAuthTokenV2": "eyJHZXRQbGF5SW5mb1Rva2VuIjoiQWN0aW9uPUdldFBsYXlJbmZvJnZpZGVvX2lkPXYwMjAifQ=="
        }

        vod_response_data = {
            "ResponseMetadata": {"Action": "GetPlayInfo"},
            "Result": {
                "Data": {
                    "CoverUrl": "https://p3.toutiaoimg.com/test_cover.jpg",
                    "PlayInfoList": [
                        {
                            "Definition": "720p",
                            "Bitrate": 1000000,
                            "MainPlayUrl": "https://v26.toutiaovod.com/video_720p.mp4"
                        },
                        {
                            "Definition": "360p",
                            "Bitrate": 500000,
                            "MainPlayUrl": "https://v26.toutiaovod.com/video_360p.mp4"
                        }
                    ]
                }
            }
        }

        with patch.object(ToutiaoParser, "_fetch_toutiao_mobile_ssr") as mock_ssr:
            mock_ssr.return_value = {
                "toutiao_article_info": sample_article_info,
                "vod_data": vod_response_data["Result"]["Data"]
            }
            parser = ToutiaoParser("https://www.toutiao.com/video/7680960670263493172")

            self.assertEqual(parser.get_title_content(), "测试今日头条视频")
            self.assertEqual(parser.get_cover_photo_url(), "https://p3.toutiaoimg.com/test_cover.jpg")
            self.assertEqual(parser.get_author_info(), {
                "author": "测试创作者",
                "avatar": "https://sf1.toutiaostatic.com/avatar.jpg"
            })
            self.assertEqual(parser.get_real_video_url(), "https://v26.toutiaovod.com/video_720p.mp4")
            self.assertEqual(parser.get_video_list(), ["https://v26.toutiaovod.com/video_720p.mp4"])


if __name__ == "__main__":
    unittest.main()
