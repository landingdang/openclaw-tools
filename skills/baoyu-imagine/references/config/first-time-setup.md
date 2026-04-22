# 首次配置

当 `baoyu-imagine` 找不到 `./.baoyu/baoyu-imagine.md`，或者当前 provider 没有默认模型时，执行本流程。

## 目标

收集下面几类偏好：

- 默认 provider
- 默认模型
- 默认质量
- 默认宽高比
- 保存位置

最终把配置写入当前工作区的 `./.baoyu/baoyu-imagine.md`。

## 完整首配

在没有 `EXTEND.md` 时，一次性询问：

1. 默认 provider
2. 对应 provider 的默认模型
3. 默认质量
4. 保存位置

推荐保存位置：

- `./.baoyu/baoyu-imagine.md`

legacy 位置只作为兼容：

- `./EXTEND.md`
- `.baoyu-skills/baoyu-imagine/EXTEND.md`
- `$HOME/.baoyu-skills/baoyu-imagine/EXTEND.md`

## 只补模型

如果已经有 `EXTEND.md`，但当前 provider 的 `default_model` 为空：

- 只问模型
- 不重复问其它偏好
- 直接更新已有 `EXTEND.md`

## 推荐默认值

### Provider

- `openai`
- `google`
- `openrouter`
- `dashscope`
- `zai`
- `minimax`
- `replicate`
- `azure`

### 质量

- `2k`：推荐默认
- `normal`：快速预览

## 产出要求

配置完成后：

1. 写入 `./.baoyu/baoyu-imagine.md`
2. 明确告诉用户保存路径
3. 继续原任务，不要停在配置阶段
