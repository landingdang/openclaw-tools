# 使用说明

## 输入场景

| 输入类型 | 处理方式 |
|---|---|
| 文章文件 | 基于文件内容分析并回写图片链接 |
| 粘贴文本 | 先物化为 source 文件，再继续 |

## 默认输出目录

```text
media/baoyu-article-illustrator/{topic-slug}/
```

## 推荐参数

- `--type`
- `--style`
- `--palette`
- `--preset`
- `--density`
- `--ref`

## 建议

- 没有明确风格时，先用 preset
- 技术文优先 `infographic` / `framework`
- 教程文优先 `flowchart`

