# 首次配置

当 `baoyu-cover-image` 找不到 `./.baoyu/baoyu-cover-image.md` 时，执行本流程。

## 需要收集的偏好

1. watermark
2. 默认 `type`
3. 默认 `palette`
4. 默认 `rendering`
5. 默认 `aspect`
6. 默认输出目录
7. 保存位置

## 推荐默认值

- 输出目录：`media/baoyu-cover-image/{topic-slug}/`
- 保存位置：`./.baoyu/baoyu-cover-image.md`

## 兼容路径

legacy 位置只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-cover-image/EXTEND.md`
- `~/.baoyu-skills/baoyu-cover-image/EXTEND.md`

## 模板

```yaml
watermark:
  enabled: false
  content: ""
preferred_type: null
preferred_palette: null
preferred_rendering: null
default_aspect: 16:9
default_output_dir: independent
quick_mode: false
```
