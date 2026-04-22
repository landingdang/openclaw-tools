# 基础 Prompt 模板

信息图最终 prompt 至少包含：

1. 选定的 `layout`
2. 选定的 `style`
3. 画幅比例
4. 结构化内容
5. 参考图信息（如有）

## 最小模板

```text
Create an infographic.

Layout: {layout}
Style: {style}
Aspect: {aspect}

Content:
{structured content}
```

如果有参考图，再补：

- `direct`
- `style`
- `palette`

