---
name: baoyu-infographic
description: 生成信息图，支持 layout × style 组合、参考图、结构化内容整理和发布级出图。适合高密度信息总结、流程图式信息图、教程型可视化和视觉摘要。Use when user asks to create infographic, 信息图, visual summary, 高密度信息大图, 可视化总结.
version: 1.56.1
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-infographic
---

# 信息图生成

把复杂内容整理成结构清晰、风格统一的信息图。

## 图像后端

默认 `baoyu-imagine`。

执行约束：
- 生成前必须先保存 prompt 文件
- 不能在没有结构化内容时直接出图

## 两个核心维度

| 维度 | 作用 |
|---|---|
| `layout` | 决定信息结构，比如线性、对比、层级、仪表盘、dense modules |
| `style` | 决定视觉风格，比如手作、技术蓝图、复古、教育风 |

常见补充维度：

- `aspect`
- `lang`
- `ref`

## 配置

配置文件：`{workspace}/.baoyu/baoyu-infographic.md`

支持配置：
- preferred layout
- preferred style
- preferred aspect
- language
- custom styles
- default output dir

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层）。

## 输出路径

默认输出到：`{workspace}/media/baoyu-infographic/{timestamp}-{topic-slug}/`

**输出文件：**
```
{workspace}/media/baoyu-infographic/{timestamp}-{topic-slug}/
├── source.md              # 源内容
├── analysis.md            # 内容分析
├── structured-content.md  # 结构化内容
├── prompts/
│   └── infographic.md     # 信息图 prompt
├── refs/                  # 参考图（如有）
└── infographic.png        # 信息图
```

## 输出目录

默认输出到：

```text
media/baoyu-infographic/{topic-slug}/
```

典型结构：

```text
media/baoyu-infographic/{topic-slug}/
├── source-{slug}.{ext}
├── analysis.md
├── structured-content.md
├── prompts/infographic.md
└── infographic.png
```

## 工作流

1. **读取配置和参考图** - 判断参考图用途（direct/style/palette）
2. **分析内容** - 输出 `analysis.md`（内容类型、信息密度、目标读者、适合的 layout/style）
3. **结构化整理** - 输出 `structured-content.md`（标题、核心结论、分区内容、标签文本、可视化元素建议）
4. **推荐组合** - 给出 3-5 套 `layout × style` 组合并说明理由
5. **确认方案** - layout、style、aspect、language
6. **写 prompt** - 保存到 `prompts/infographic.md`
7. **生成图片** - 默认 `baoyu-imagine`

## 执行约束

- 没完成结构化整理前不出图
- 信息图文本必须和源数据一致
- 参考图必须先落盘
- 内容更适合多张卡片时提示用 `baoyu-image-cards`

## 完成输出

- `analysis.md` 已生成
- `structured-content.md` 已生成
- `prompts/infographic.md` 已生成
- `infographic.png` 已输出到 `media/baoyu-infographic/{topic-slug}/`
- 说明采用的 `layout × style` 组合
