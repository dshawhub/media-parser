from src.parser_factory import register_parser
import random
import re

import requests

from configs.general_constants import USER_AGENT_PC
from configs.logging_config import get_logger
from src.parsers.base_parser import BaseParser

logger = get_logger(__name__)


@register_parser("哔哩哔哩")
class BilibiliParser(BaseParser):
    """通过 B 站官方 API 获取可直接播放的单文件 MP4 地址及动态内容。"""

    API_VIEW = "https://api.bilibili.com/x/web-interface/view"
    API_PLAYURL = "https://api.bilibili.com/x/player/playurl"
    API_DYNAMIC_DETAIL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"

    def __init__(self, real_url):
        super().__init__(real_url)
        self.headers = {
            "User-Agent": random.choice(USER_AGENT_PC),
            "Referer": "https://www.bilibili.com/",
        }
        self.bvid = self._extract_bvid(real_url)
        self.dynamic_id = None if self.bvid else self._extract_dynamic_id(real_url)
        self.dynamic_info = {}

        if not self.bvid and self.dynamic_id:
            self.dynamic_info = self._fetch_dynamic_info(self.dynamic_id)
            if bvid := self._extract_bvid_from_dynamic(self.dynamic_info):
                self.bvid = bvid

        self.video_info = self._fetch_video_info() if self.bvid else {}
        self._play_info_by_cid = {}

    @staticmethod
    def _extract_bvid(url):
        """从 URL 中提取 BV 号，例如 ``BV1df421v7xm``。"""
        match = re.search(r"(BV[a-zA-Z0-9]+)", url or "")
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_dynamic_id(url):
        """从 URL 中提取动态/Opus ID。"""
        match = re.search(r"(?:t\.bilibili\.com/|opus/|dynamic_id=)(\d{17,20})", url or "")
        if match:
            return match.group(1)
        logger.error("无法从 URL 中提取 BV 号或动态 ID: %s", url)
        return None

    def _fetch_dynamic_info(self, dynamic_id):
        """通过动态 API 获取动态详情。"""
        if not dynamic_id:
            return {}
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://t.bilibili.com/",
            }
            response = self.session.get(
                self.API_DYNAMIC_DETAIL,
                params={"id": dynamic_id},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.error("B站动态 API 请求失败: %s", error)
            return {}

        if result.get("code") == 0:
            return result.get("data", {}).get("item") or {}
        logger.error(
            "B站动态 API 返回错误: code=%s, message=%s",
            result.get("code"),
            result.get("message"),
        )
        return {}

    @staticmethod
    def _extract_bvid_from_dynamic(dynamic_info):
        """从动态详情数据中提取关联的视频 BV 号。"""
        major = (
            dynamic_info.get("modules", {})
            .get("module_dynamic", {})
            .get("major", {})
        )
        if major.get("type") == "MAJOR_TYPE_ARCHIVE":
            return major.get("archive", {}).get("bvid")
        return None

    def _fetch_video_info(self):
        if not self.bvid:
            return {}
        try:
            response = self.session.get(
                self.API_VIEW,
                params={"bvid": self.bvid},
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.error("B站 API 视频信息请求失败: %s", error)
            return {}

        if result.get("code") == 0:
            return result.get("data") or {}
        logger.error(
            "B站 API 返回错误: code=%s, message=%s",
            result.get("code"),
            result.get("message"),
        )
        return {}

    def _fetch_play_info(self, cid):
        """获取包含音视频的 durl 单文件流，不下载或转封装媒体。"""
        if not self.bvid or not cid:
            return {}
        if cid in self._play_info_by_cid:
            return self._play_info_by_cid[cid]

        try:
            response = self.session.get(
                self.API_PLAYURL,
                params={
                    "otype": "json",
                    "fnver": 0,
                    "fnval": 3,
                    "player": 3,
                    "qn": 112,
                    "bvid": self.bvid,
                    "cid": cid,
                    "platform": "html5",
                    "high_quality": 1,
                },
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.error("B站 API 播放地址请求失败: %s", error)
            return {}

        if result.get("code") != 0:
            logger.error(
                "B站 API playurl 返回错误: code=%s, message=%s",
                result.get("code"),
                result.get("message"),
            )
            return {}

        play_info = result.get("data") or {}
        self._play_info_by_cid[cid] = play_info
        return play_info

    @staticmethod
    def _get_durl(play_info):
        durls = play_info.get("durl") or []
        if not durls:
            return None
        return durls[0].get("url")

    def _get_pages(self):
        return self.video_info.get("pages") or []

    def _get_dynamic_pics(self):
        if not self.dynamic_info:
            return []
        major = (
            self.dynamic_info.get("modules", {})
            .get("module_dynamic", {})
            .get("major", {})
        )
        pics = []
        if opus := major.get("opus"):
            for pic in opus.get("pics") or []:
                if url := pic.get("url"):
                    pics.append(url)
        elif draw := major.get("draw"):
            for item in draw.get("items") or []:
                if url := item.get("src"):
                    pics.append(url)
        return pics

    def get_title_content(self):
        if self.video_info:
            return self.video_info.get("title") or None
        if self.dynamic_info:
            modules = self.dynamic_info.get("modules", {})
            dynamic_mod = modules.get("module_dynamic", {})
            major = dynamic_mod.get("major", {})
            if opus := major.get("opus"):
                return opus.get("title") or None
        return None

    def get_description(self):
        if self.video_info:
            return self.video_info.get("desc") or None
        if self.dynamic_info:
            dynamic_mod = self.dynamic_info.get("modules", {}).get("module_dynamic", {})
            major = dynamic_mod.get("major", {})
            if opus := major.get("opus"):
                return opus.get("summary", {}).get("text") or dynamic_mod.get("desc", {}).get("text") or None
            return dynamic_mod.get("desc", {}).get("text") or None
        return None

    def get_cover_photo_url(self):
        if self.video_info:
            return self.video_info.get("pic", "")
        if self.dynamic_info:
            pics = self._get_dynamic_pics()
            if pics:
                return pics[0]
        return ""

    def get_author_info(self):
        if self.video_info:
            owner = self.video_info.get("owner") or {}
            avatar = owner.get("face", "")
            if avatar.startswith("//"):
                avatar = "https:" + avatar
            return {
                "nickname": owner.get("name", ""),
                "author_id": str(owner.get("mid", "")),
                "avatar": avatar,
            }
        if self.dynamic_info:
            author = (
                self.dynamic_info.get("modules", {})
                .get("module_author", {})
            )
            avatar = author.get("face", "")
            if avatar.startswith("//"):
                avatar = "https:" + avatar
            return {
                "nickname": author.get("name", ""),
                "author_id": str(author.get("mid", "")),
                "avatar": avatar,
            }
        return {"nickname": "", "author_id": "", "avatar": ""}

    def get_real_video_url(self):
        """返回首个分 P 的 B 站 CDN MP4 直链；该文件已包含音轨。"""
        pages = self._get_pages()
        if not pages:
            return None
        return self._get_durl(self._fetch_play_info(pages[0].get("cid")))

    def get_video_list(self):
        """返回多分 P 视频的 CDN MP4 直链，单分 P 保持旧响应结构。"""
        if self.video_info:
            pages = self._get_pages()
            if len(pages) <= 1:
                return []
            return [
                url
                for page in pages
                if (url := self._get_durl(self._fetch_play_info(page.get("cid"))))
            ]
        return []

    def get_image_list(self):
        """返回动态或 Opus 帖中的原始图片列表。"""
        return self._get_dynamic_pics()

    def get_audio_url(self):
        """durl 单文件已内嵌音轨，无需再下载 DASH 音频或调用 FFmpeg。"""
        return None
