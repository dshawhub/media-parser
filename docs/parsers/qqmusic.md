# QQ 音乐解析指南

## 支持范围

- `c6.y.qq.com/base/fcgi-bin/u` 分享短链
- `i.y.qq.com/v8/playsong.html?songid=...` / `songmid=...` 移动端歌曲播放页
- `i2.y.qq.com/n3/other/pages/details/mv.html?vid=...` MV / 分享视频页
- `y.qq.com/n/ryqq/mv/{vid}` 桌面端 MV 地址
- `y.qq.com/n/ryqq/songDetail/{songmid}` 桌面端歌曲详情页
- 歌曲音频直链（`audio_url`）与带时间戳的 LRC 歌词（`subtitles`）
- 标题、800x800 高清封面、歌手头像及昵称信息
- MV 多档公开 MP4 地址，默认把最高可用清晰度作为 `video_url`

## 解析流程

1. 识别并提取分享链接中的媒体标识（`songid`、`songmid` 或 MV `vid`）。
2. 若为短链则跟随重定向并读取页面 `window.__ssrFirstPageData__` 补充元数据。
3. 调用 QQ 音乐 `musicu.fcg`（PC Web 协议）：
   - 歌曲：请求 `songinfo`、`playUrl`（`CgiGetVkey`）和 `lyric`（`PlayLyricInfo`），直接解析音频流、高清封面与 LRC 歌词。
   - MV：请求 `video.VideoDataServer` 与 `gosrf.Stream.MvUrlProxy` 获取多档 MP4。
4. API 返回时统一将 `http://` 媒体地址升级为 HTTPS。

## 返回字段

| 字段 | 适用类型 | 来源 |
| --- | --- | --- |
| `video_id` | 歌曲 / MV | 查询参数 `songid`/`songmid`/`vid` 或页面路径 |
| `title` | 歌曲 / MV | SSR 或接口中的 `name`/`title` |
| `cover_url` | 歌曲 / MV | 800x800 专辑封面图或 MV `cover_pic` |
| `author` | 歌曲 / MV | 歌手名与头像，或 MV 上传者 |
| `audio_url` | 歌曲 | `CgiGetVkey` 返回的音频流地址（`sip + purl`） |
| `subtitles` | 歌曲 | `PlayLyricInfo` 解码并解析出的带时间戳 LRC 歌词列表 |
| `video_url` | MV | 最高可用 MP4 档位 |
| `video_list` | MV | 两档及以上时返回全部可用清晰度 |

## 验证

```bash
python3 -m unittest tests.test_qqmusic_parser
python3 tests/manual_verify_parsers.py --platform "QQ音乐" --limit 2
```
