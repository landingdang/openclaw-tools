# 首次配置

当 `baoyu-article-illustrator` 找不到 `./.baoyu/baoyu-article-illustrator.md` 时，执行本流程。

## 需要收集的偏好

1. watermark
2. 默认 style
3. 默认 palette
4. 默认输出目录
5. 保存位置

## 推荐默认值

- 输出目录：`media/baoyu-article-illustrator/{topic-slug}/`
- 保存位置：`./.baoyu/baoyu-article-illustrator.md`

## 兼容路径

legacy 位置只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-article-illustrator/EXTEND.md`
- `~/.baoyu-skills/baoyu-article-illustrator/EXTEND.md`

## 模板

```yaml
watermark:
  enabled: false
  content: ""
preferred_style:
  name: null
preferred_palette: null
language: null
default_output_dir: independent
```
