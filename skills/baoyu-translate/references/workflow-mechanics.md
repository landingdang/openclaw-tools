# 工作流细节

本文件只回答两个问题：

1. 源内容怎么物化
2. 输出目录怎么创建

## 物化源内容

| 输入类型 | 处理方式 |
|---|---|
| 文件 | 直接使用原文件 |
| inline text | 保存到 `media/baoyu-translate/{slug}.md` |
| URL | 先抓取，再保存到 `media/baoyu-translate/{slug}.md` |

`{slug}` 建议用 2-4 个词的 kebab-case。

## 输出目录

统一创建到：

```text
media/baoyu-translate/{source-basename}-{target-lang}/
```

示例：

- `posts/article.md` → `media/baoyu-translate/article-zh/`
- `media/baoyu-translate/ai-future.md` → `media/baoyu-translate/ai-future-zh/`

## 冲突处理

如果目标目录已存在：

- 先备份旧目录为 `{name}.backup-YYYYMMDD-HHMMSS/`
- 再创建新目录

不要直接覆盖。

