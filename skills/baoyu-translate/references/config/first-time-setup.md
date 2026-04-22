# 首次配置

当 `baoyu-translate` 找不到 `./.baoyu/baoyu-translate.md` 时，执行本流程。

## 目的

收集翻译偏好并写入当前工作区的 `./.baoyu/baoyu-translate.md`。

## 推荐一次问清的内容

1. 默认目标语言
2. 默认模式：`quick` / `normal` / `refined`
3. 默认受众
4. 默认风格
5. 保存位置

## 推荐保存位置

- `./.baoyu/baoyu-translate.md`

legacy 路径只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-translate/EXTEND.md`
- `$HOME/.baoyu-skills/baoyu-translate/EXTEND.md`

## 结果

完成后：

1. 写入 `./.baoyu/baoyu-translate.md`
2. 明确告诉用户保存路径
3. 继续原翻译任务

## 模板

```yaml
target_language: zh-CN
default_mode: normal
audience: general
style: storytelling
chunk_threshold: 4000
chunk_max_words: 5000
```
