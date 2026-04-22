---
name: baoyu-article-illustrator
description: 为文章自动规划配图位置并生成插图。支持 type、style、palette、density、preset、参考图与批量生成。适合长文配图、教程插图、概念图和技术说明图。Use when user asks to illustrate article, add images to article, 为文章配图, 给文章加插图, generate illustrations for article.
version: 1.57.0
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-article-illustrator
---

# 文章配图

分析文章结构，规划配图位置并生成风格统一的插图。

## 图像后端

默认 `baoyu-imagine`。

执行约束：
- 每张图必须先写 prompt 文件
- 不直接内联 prompt
- 执行现成 prompt 时优先 batch

## 三个核心维度

| 维度 | 作用 |
|---|---|
| `type` | 插图结构类型，例如 `infographic`、`scene`、`flowchart` |
| `style` | 绘制风格 |
| `palette` | 配色覆盖 |

还可以补充：

- `preset`
- `density`
- `ref`

## 配置

配置文件：`{workspace}/.baoyu/baoyu-article-illustrator.md`

支持配置：
- watermark
- preferred style / palette
- language
- default output dir

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-article-illustrator/{timestamp}-{article-slug}/`

**输出文件：**
```
{workspace}/media/baoyu-article-illustrator/{timestamp}-{article-slug}/
├── source-article.md      # 源文章
├── outline.md             # 配图大纲
├── prompts/               # 插图 prompts
│   ├── 01-illustration.md
│   └── 02-illustration.md
├── refs/                  # 参考图（如有）
├── 01-illustration.png    # 插图
└── 02-illustration.png
```

## 输出目录

默认输出到：

```text
media/baoyu-article-illustrator/{topic-slug}/
```

典型结构：

```text
media/baoyu-article-illustrator/{topic-slug}/
├── source-{slug}.{ext}
├── outline.md
├── references/
├── prompts/
│   └── NN-{type}-{slug}.md
└── NN-{type}-{slug}.png
```

如果源文章是文件，插回 Markdown 时使用相对路径引用这些图片。  
如果源内容是粘贴文本，则整组结果都保存在这个目录里。

## 工作流

1. **预检查** - 读取配置、参考图、判断输入类型
2. **分析文章** - 判断哪些段落需要图、每张图的作用
3. **确认方案** - preset、数量、density、type、style、palette、参考图
4. **生成大纲** - `outline.md`（编号、位置、目的、描述、文件名）
5. **写 prompt** - 每张图对应一个 prompt 文件
6. **生成图片** - 默认 `baoyu-imagine`，prompt 稳定时优先 batch
7. **回写文章** - 插入图片引用

## 执行约束

- 先有 `outline.md` → 再有 `prompts/` → 最后生成图片
- 不凭感觉一次性出图
- 图只是重复正文无新增价值 → 不生成
- 参考图必须先落盘

## 完成输出

- `outline.md` 已生成
- `prompts/` 已齐全
- 图片已保存到 `media/baoyu-article-illustrator/{topic-slug}/`
- 源文章是文件时已插入相对路径引用
