---
name: baoyu-translate
description: 文章与文档翻译技能，支持 quick、normal、refined 三种模式，并支持术语表、一致性控制和长文分块翻译。Use when user asks to translate, 翻译, 精翻, 本地化, convert to Chinese, convert to English, localize article, translate document.
version: 1.59.0
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-translate
    requires:
      anyBins:
        - bun
        - npx
---

# 文档翻译

翻译文章、网页和 Markdown 文档，支持 quick、normal、refined 三种模式。

## 执行准备

- `{baseDir}` = 当前 SKILL.md 所在目录
- 优先使用 `bun`
- 入口：`scripts/main.ts`

## 配置

配置文件：`{workspace}/.baoyu/baoyu-translate.md`

支持配置：
- `target_language` - 目标语言
- `default_mode` - 默认模式
- `audience` - 受众
- `style` - 风格
- `chunk_threshold` - 分块阈值
- `chunk_max_words` - 分块最大字数
- `glossary` - 术语表
- `glossary_files` - 术语表文件
- `default_output_dir` - 默认输出目录

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-translate/{timestamp}-{source-slug}-{target-lang}/`

**路径组成：**
- `{workspace}` - 智能体工作目录
- `media/` - 固定媒体目录
- `baoyu-translate/` - skill 名称
- `{timestamp}` - 任务时间戳
- `{source-slug}` - 源文件名
- `{target-lang}` - 目标语言

**输出文件：**
```
{workspace}/media/baoyu-translate/{timestamp}-{source-slug}-{target-lang}/
├── translation.md          # 最终翻译
├── 01-analysis.md         # 分析（normal/refined）
├── 02-prompt.md           # prompt（normal/refined）
├── 03-draft.md            # 初稿（refined）
├── 04-critique.md         # 批评（refined）
├── 05-revision.md         # 修订（refined）
└── chunks/                # 分块文件（如有）
```

## 三种模式

| 模式 | 适合场景 | 过程 |
|---|---|---|
| `quick` | 短文本、快速任务 | 直接翻译 |
| `normal` | 普通文章、博客、说明文 | 分析 → 翻译 |
| `refined` | 重要稿件、对外发布、精修内容 | 分析 → 初稿 → 批评审阅 → 修订 → 润色 |

默认模式是 `normal`。

## 工作流

1. **读取配置和术语表**
2. **物化源内容** - 统一保存到 `media/baoyu-translate/`
3. **判断分块** - 超过阈值时分块处理
4. **按模式执行**
5. **长文分块协作** - 支持并行翻译

## 输出目录

`media/baoyu-translate/{source-basename}-{target-lang}/`

包含：
- `translation.md` - 最终翻译
- `01-analysis.md` - 分析（normal/refined）
- `02-prompt.md` - prompt（normal/refined）
- `03-draft.md` - 初稿（refined）
- `04-critique.md` - 批评（refined）
- `05-revision.md` - 修订（refined）
- `chunks/` - 分块文件（如有）

## 常用参数

| 参数 | 说明 |
|---|---|
| `--to` | 目标语言 |
| `--from` | 源语言 |
| `--mode` | `quick` / `normal` / `refined` |
| `--audience` | 受众 |
| `--style` | 翻译风格 |
| `--glossary` | 额外术语表 |

## 完成输出

- 源语言 / 目标语言
- 使用模式
- 输出目录
- 最终文件：`translation.md`
- 是否分块
- 图片文字处理（如有）
