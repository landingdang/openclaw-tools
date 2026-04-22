---
name: baoyu-image-cards
description: 生成社交媒体图片卡片组，适合小红书、微信图文、知识卡片和内容拆条。支持 style、layout、palette、preset、参考图和多张卡片连续生成。Use when user asks for image cards, 小红书图片, 图片卡片, 微信图文配图, social media card series, infographic cards.
version: 1.56.1
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-image-cards
---

# 图片卡片组

把内容拆成多张连续图片卡片，适合社交媒体传播和知识点总结。

## 图像后端

默认 `baoyu-imagine`。

执行约束：
- 生成前必须先写 prompt 到 `prompts/`
- 不直接内联 prompt

## 常用参数

| 参数 | 说明 |
|---|---|
| `--style <name>` | 视觉风格 |
| `--layout <name>` | 信息布局 |
| `--palette <name>` | 颜色覆盖 |
| `--preset <name>` | 风格 + 布局快捷组合 |
| `--ref <files...>` | 参考图，通常作用于首图或整组风格锚点 |
| `--yes` | 非交互模式，跳过确认，按偏好或默认值执行 |

## 三个核心维度

| 维度 | 作用 |
|---|---|
| `style` | 决定视觉语言、笔触、质感、装饰元素 |
| `layout` | 决定信息组织方式，例如稀疏、平衡、对比、流程、脑图 |
| `palette` | 只改颜色，不改布局和渲染规则 |

如果用户没指定，优先根据内容推荐 `preset`，再退回到单独选择 `style` / `layout` / `palette`。

## 配置

配置文件：`{workspace}/.baoyu/baoyu-image-cards.md`

支持配置：
- watermark
- preferred_style
- preferred_layout
- preferred_palette
- language
- custom styles
- default output dir

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-image-cards/{timestamp}-{topic-slug}/`

**输出文件：**
```
{workspace}/media/baoyu-image-cards/{timestamp}-{topic-slug}/
├── source.md              # 源内容
├── outline.md             # 卡片大纲
├── prompts/               # 卡片 prompts
│   ├── 01-card.md
│   └── 02-card.md
├── refs/                  # 参考图（如有）
├── 01-card.png            # 卡片图
└── 02-card.png
```

## 输出目录

默认输出到当前工作区：

```text
media/baoyu-image-cards/{topic-slug}/
```

典型结构：

```text
media/baoyu-image-cards/{topic-slug}/
├── source-{slug}.{ext}
├── outline.md
├── refs/
├── prompts/
│   └── NN-{type}-{slug}.md
├── 01-cover-{slug}.png
├── 02-content-{slug}.png
└── ...
```

## 工作流

1. **读取配置** - 用户传 `--yes` 时优先使用偏好
2. **分析内容** - 判断内容类型、拆成几张卡、每张卡的信息任务（封面、核心观点、步骤/清单、对比、总结）
3. **确认方案** - preset 或 style+layout、数量、palette、参考图
4. **生成大纲** - `outline.md`（序号、目标、文本、文件名）
5. **写 prompt** - 每张图对应一个 prompt 文件
6. **调用后端** - 默认 `baoyu-imagine`，一组卡片风格保持一致，支持 session/batch
7. **输出结果** - 卡片总数、输出目录、风格组合、是否使用参考图、是否启用水印

## 完成输出

- `outline.md` 已生成
- `prompts/` 下每张卡对应的 prompt 文件齐全
- 最终图片已保存到 `media/baoyu-image-cards/{topic-slug}/`
- 说明推荐方案或实际采用方案
