---
name: baoyu-cover-image
description: 为文章、专题页和内容卡片生成封面图。支持 type、palette、rendering、text、mood、font、aspect 等维度控制，并可结合参考图。Use when user asks to generate cover image, create article cover, make cover, 生成封面图, 做文章封面.
version: 1.56.1
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-cover-image
---

# 封面图生成

为文章、专题、报告生成统一风格的封面图。

## 图像后端

默认 `baoyu-imagine`。

执行约束：
- 生成前必须先写 prompt 到 `prompts/`
- 不直接内联 prompt

## 常用参数

| 参数 | 说明 |
|---|---|
| `--type <name>` | 封面类型，例如 `hero`、`conceptual`、`typography` |
| `--palette <name>` | 色板 |
| `--rendering <name>` | 渲染风格 |
| `--style <name>` | 风格预设 |
| `--text <level>` | 文字强度 |
| `--mood <level>` | 情绪强度 |
| `--font <name>` | 标题字风格 |
| `--aspect <ratio>` | 宽高比 |
| `--lang <code>` | 标题语言 |
| `--no-title` | 不上标题 |
| `--quick` | 跳过确认，自动选择 |
| `--ref <files...>` | 参考图 |

## 主要维度

| 维度 | 用途 |
|---|---|
| `type` | 决定封面的构图类型 |
| `palette` | 决定颜色方向 |
| `rendering` | 决定绘制质感 |
| `text` | 决定是否展示标题、副标题 |
| `mood` | 决定对比度和视觉力度 |
| `font` | 决定标题字形风格 |

## 配置

配置文件：`{workspace}/.baoyu/baoyu-cover-image.md`

支持配置：
- watermark
- preferred type / palette / rendering / text / mood / font
- default aspect
- default output dir
- quick mode
- language

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-cover-image/{timestamp}-{topic-slug}/`

**输出文件：**
```
{workspace}/media/baoyu-cover-image/{timestamp}-{topic-slug}/
├── prompts/
│   └── cover-prompt.md    # 封面 prompt
├── refs/                  # 参考图（如有）
│   └── ref.png
└── cover.png              # 封面图
```

## 输出目录

默认输出到：

```text
media/baoyu-cover-image/{topic-slug}/
```

典型结构：

```text
media/baoyu-cover-image/{topic-slug}/
├── source-{slug}.{ext}
├── refs/
├── prompts/
│   └── 01-cover-{slug}.md
└── cover.png
```

## 工作流

1. **读取配置** - 用户传 `--quick` 时优先使用偏好
2. **分析内容** - 主题、语气、标题信息量、视觉隐喻、是否需要参考图
3. **确认方案** - type、palette、rendering、text、mood、font、aspect
4. **写 prompt** - 保存到 `prompts/01-cover-{slug}.md`
5. **调用后端** - 默认 `baoyu-imagine`
6. **返回结果** - 输出路径、维度组合、是否使用参考图、是否启用水印

## 完成输出

- `cover.png` 已生成
- `prompts/` 中有最终 prompt 文件
- 输出目录在 `media/baoyu-cover-image/{topic-slug}/`
- 说明采用的维度组合
