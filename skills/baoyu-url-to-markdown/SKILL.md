---
name: baoyu-url-to-markdown
description: 抓取任意 URL 并转换为 Markdown，内建 X/Twitter、YouTube、Hacker News 和通用网页适配器。支持登录/CAPTCHA 等交互等待模式。Use when user wants to save webpage as markdown, 网页转 markdown, 保存网页, 抓网页正文, URL to markdown.
version: 1.60.0
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-url-to-markdown
    requires:
      anyBins:
        - bun
        - npx
---

# URL 转 Markdown

抓取网页并转换为 Markdown，支持 X/Twitter、YouTube、Hacker News 和通用网页。

## 执行准备

- `{baseDir}` = 当前 SKILL.md 所在目录
- 优先使用 `bun`
- 首次执行：`${BUN} install --cwd {baseDir}/scripts`
- `${READER}` = `{baseDir}/scripts/node_modules/.bin/baoyu-fetch`

## 配置

配置文件：`{workspace}/.baoyu/baoyu-url-to-markdown.md`

支持配置：
- `download_media` - 是否下载媒体
- `default_output_dir` - 默认输出目录

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-url-to-markdown/{timestamp}-{domain}-{slug}/`

**路径组成：**
- `{workspace}` - 智能体工作目录
- `media/` - 固定媒体目录
- `baoyu-url-to-markdown/` - skill 名称
- `{timestamp}` - 任务时间戳
- `{domain}` - 网站域名
- `{slug}` - URL 路径标识

**输出文件：**
```
{workspace}/media/baoyu-url-to-markdown/{timestamp}-{domain}-{slug}/
├── article.md             # 文章正文
├── imgs/                  # 图片（如启用 --download-media）
│   ├── image1.jpg
│   └── image2.png
└── videos/                # 视频（如启用 --download-media）
    └── video1.mp4
```

## 常用命令

```bash
${READER} <url>
${READER} <url> --output article.md
${READER} <url> --output article.md --download-media
${READER} <url> --wait-for interaction --output article.md
${READER} <url> --format json --output article.json
${READER} <url> --adapter youtube --output transcript.md
```

## 常用参数

| 参数 | 说明 |
|---|---|
| `<url>` | 要抓取的网址 |
| `--output <path>` | 输出文件路径 |
| `--format <type>` | `markdown` 或 `json` |
| `--json` | `--format json` 的快捷方式 |
| `--adapter <name>` | 强制指定适配器 |
| `--headless` | 强制 headless 模式 |
| `--wait-for <mode>` | 登录 / CAPTCHA 等待模式 |
| `--timeout <ms>` | 页面加载超时 |
| `--download-media` | 下载图片和视频到本地 |
| `--media-dir <dir>` | 媒体资源输出目录 |
| `--cdp-url <url>` | 复用已有 Chrome CDP 连接 |
| `--browser-path <path>` | 指定 Chrome/Chromium 路径 |
| `--chrome-profile-dir <path>` | 指定 Chrome profile |
| `--debug-dir <dir>` | 保存调试产物 |

## 输出路径

`./media/baoyu-url-to-markdown/{domain}/{slug}/{slug}.md`

启用 `--download-media` 时：
- 图片 → `imgs/`
- 视频 → `videos/`

## 质量检查

抓取后检查：
- 内容长度是否合理
- 是否只抓到导航/登录框
- 是否缺少正文

需要登录或验证码时使用 `--wait-for interaction`。

## 内建适配器

- X / Twitter
- YouTube  
- Hacker News
- 通用网页

## 执行规则

1. 用户未指定 `--output` 时自动构造路径
2. 需要登录时使用 `--wait-for interaction`
3. 抓取后检查质量
4. `download_media=ask` 时先保存正文再询问

## 完成输出

- 来源 URL
- 输出路径
- 是否下载媒体
- 使用的适配器
- 质量问题（如有）
