# 适配器与媒体处理

本文件只在下面场景需要打开：

- 需要强制指定 adapter
- 需要决定是否下载媒体
- 需要查看 JSON 输出字段

## 内建 adapter

| adapter | 适用网址 | 说明 |
|---|---|---|
| `x` | x.com / twitter.com | 推文、线程、X Articles |
| `youtube` | youtube.com / youtu.be | 字幕、章节、封面、元信息 |
| `hn` | news.ycombinator.com | Hacker News 讨论串 |
| `generic` | 任意普通网页 | 通用正文抓取 |

默认会自动根据 URL 选择。

## 媒体下载规则

由 `EXTEND.md` 的 `download_media` 决定：

| 值 | 行为 |
|---|---|
| `1` | 总是下载媒体 |
| `0` | 从不下载媒体 |
| `ask` | 先保存正文，再询问是否下载媒体 |

### `ask` 模式

1. 先不带 `--download-media` 执行
2. 检查输出 markdown 是否包含远程图片 / 视频链接
3. 如果没有，就结束
4. 如果有，就询问用户是否下载
5. 如果用户同意，再用同一路径重跑一次并带上 `--download-media`

## 下载后目录结构

如果启用 `--download-media`：

- 图片写到 `imgs/`
- 视频写到 `videos/`
- markdown 中的链接会被改写为相对路径

## JSON 输出

`--format json` 时，重点字段包括：

- `adapter`
- `status`
- `login`
- `interaction`
- `document`
- `media`
- `markdown`
- `downloads`

如果 `status = "needs_interaction"`，说明需要转入交互模式。

