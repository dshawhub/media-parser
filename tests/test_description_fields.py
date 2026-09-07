import unittest

from src.parsers.douyin_parser import DouyinParser
from src.parsers.xiaohongshu_parser import XiaohongshuParser


class DescriptionFieldsTest(unittest.TestCase):
    @staticmethod
    def douyin_parser(data):
        parser = DouyinParser.__new__(DouyinParser)
        parser.data = data
        parser.is_music = False
        parser.is_collection = False
        parser.is_lvdetail = False
        return parser

    def test_xiaohongshu_separates_title_and_description(self):
        parser = XiaohongshuParser.__new__(XiaohongshuParser)
        parser.note_data = {"title": "小红书标题", "desc": "小红书正文"}

        self.assertEqual(parser.get_title_content(), "小红书标题")
        self.assertEqual(parser.get_description(), "小红书正文")

    def test_xiaohongshu_does_not_use_description_as_title_fallback(self):
        parser = XiaohongshuParser.__new__(XiaohongshuParser)
        parser.note_data = {"title": "", "desc": "只有正文"}

        self.assertIsNone(parser.get_title_content())
        self.assertEqual(parser.get_description(), "只有正文")

    def test_douyin_exposes_caption_as_description(self):
        parser = self.douyin_parser({"aweme_detail": {"desc": "抖音作品文案"}})

        self.assertEqual(parser.get_description(), "抖音作品文案")
        self.assertIsNone(parser.get_title_content())

    def test_douyin_discards_title_that_duplicates_caption(self):
        parser = self.douyin_parser({"aweme_detail": {"itemTitle": "重复内容", "desc": "重复内容"}})

        self.assertIsNone(parser.get_title_content())
        self.assertEqual(parser.get_description(), "重复内容")

    def test_douyin_keeps_title_only_when_it_differs_from_caption(self):
        parser = self.douyin_parser({"aweme_detail": {"itemTitle": "独立标题", "desc": "作品正文"}})

        self.assertEqual(parser.get_title_content(), "独立标题")
        self.assertEqual(parser.get_description(), "作品正文")

    def test_douyin_returns_none_without_caption(self):
        parser = self.douyin_parser({})

        self.assertIsNone(parser.get_description())


if __name__ == "__main__":
    unittest.main()
