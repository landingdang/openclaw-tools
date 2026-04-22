# Prompt 构造规则

## 基本原则

每张插图都必须对应一个独立 prompt 文件。

## 文件格式

推荐结构：

```yaml
---
illustration_id: 01
type: infographic
style: blueprint
references:
  - ref_id: 01
    filename: 01-ref-diagram.png
    usage: direct
---
```

正文再写：

- 构图
- 关键元素
- 文字标签
- 配色
- 风格要求

## 参考图规则

只有参考图真的已经落盘时，才能写进 frontmatter 的 `references`。

否则：

- 不要写不存在的路径
- 可以把抽出来的 style / palette 文字直接写进 prompt 正文

## 所有 prompt 的默认要求

- 构图清晰
- 有足够留白
- 背景尽量简洁
- 重点信息突出
- 人物尽量使用简化表现，不走写实路线

