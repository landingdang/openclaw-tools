# 首次配置

当 `baoyu-url-to-markdown` 找不到 `./.baoyu/baoyu-url-to-markdown.md` 时，执行本流程。

## 需要收集的偏好

1. 媒体下载策略：`ask` / `1` / `0`
2. 默认输出目录
3. 保存位置

## 推荐默认值

- 媒体下载：`ask`
- 输出目录：`./media/baoyu-url-to-markdown/`
- 保存位置：`./.baoyu/baoyu-url-to-markdown.md`

## 兼容路径

legacy 位置只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-url-to-markdown/EXTEND.md`
- `~/.baoyu-skills/baoyu-url-to-markdown/EXTEND.md`

## 模板

```yaml
download_media: ask
default_output_dir: ./media/baoyu-url-to-markdown/
```
