# 西瓜视频 (Xigua) 逆向解析指南

本篇详细记录字节跳动旗下 **西瓜视频** 中长视频的解析与继承机制。

---

## 1. 平台特征与支持能力

* **平台标识**：`西瓜视频`
* **支持媒体类型**：高清视频 (MP4，最高 1080P/720P) / 封面图 / 视频标题与作者
* **常见链接形态**：
  * 西瓜短链/网页：`https://v.douyin.com/Nid-fFF_sdI/`、`https://www.ixigua.com/7676450021063735414`
* **Cookie 依赖**：🟢 免配置，无需任何 Cookie 即可直接匿名解析。

---

## 2. 核心架构与多级容灾流程

西瓜视频底层与抖音生态体系协同。[XiguaParser](file:///Users/leo/Projects/media-parser/src/parsers/xigua_parser.py) 采用分层多级容灾策略：

1. **第一优先级：移动端 SSR + ByteDance VOD 调度链路**：
   * 请求移动端落地页提取 `<script id="RENDER_DATA">` 内的 `articleInfo` 或 `videoInfo`；
   * 通过 `playAuthTokenV2` 解析出 `GetPlayInfoToken`，调用 `https://vod.bytedanceapi.com/?{query}` 获取多档清晰度 MP4 直链。
2. **第二优先级：抖音移动 Feed 核心接口**：
   * 针对与抖音联通的分发视频，免签名请求 `api5-normal-c-hl.amemv.com/aweme/v1/feed/`。
3. **第三优先级：抖音 Web a_bogus 签名 API 与 PC SSR 兜底**。

```python
from src.parser_factory import register_parser
from src.parsers.douyin_parser import DouyinParser

@register_parser("西瓜视频")
class XiguaParser(DouyinParser):
    """西瓜视频分享解析器，支持移动端 SSR + ByteDance VOD 及抖音链路兜底。"""
```

---

## 3. 测试与验证

* **单元测试**：[tests/test_xigua_parser.py](file:///Users/leo/Projects/media-parser/tests/test_xigua_parser.py)
* **执行命令**：`python3 -m unittest tests/test_xigua_parser.py`
