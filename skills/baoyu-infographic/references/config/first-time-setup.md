# 首次配置

当 `baoyu-infographic` 找不到 `./.baoyu/baoyu-infographic.md` 时，执行本流程。

## 需要收集的偏好

1. 默认 `layout`
2. 默认 `style`
3. 默认 `aspect`
4. 默认语言
5. 保存位置

## 推荐默认值

- `layout`: `bento-grid`
- `style`: `craft-handmade`
- 保存位置：`./.baoyu/baoyu-infographic.md`

## 兼容路径

legacy 位置只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-infographic/EXTEND.md`
- `~/.baoyu-skills/baoyu-infographic/EXTEND.md`

## 模板

```yaml
preferred_layout: bento-grid
preferred_style: craft-handmade
preferred_aspect: landscape
language: null
custom_styles: []
```
