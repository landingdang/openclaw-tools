# `EXTEND.md` 配置结构

`baoyu-imagine` 的 `EXTEND.md` 只保存偏好，不保存密钥。

## 最小示例

```yaml
default_provider: openai
default_quality: 2k
default_aspect_ratio: 16:9
default_image_size: 2K
default_image_api_dialect: openai-native

default_model:
  openai: gpt-image-1.5
  google: gemini-3-pro-image-preview
  dashscope: qwen-image-2.0-pro
```

## 字段说明

| 字段 | 用途 |
|---|---|
| `default_provider` | 默认 provider |
| `default_quality` | 默认质量，例如 `normal` / `2k` |
| `default_aspect_ratio` | 默认宽高比 |
| `default_image_size` | 默认图像尺寸，主要给 Google/OpenRouter |
| `default_image_api_dialect` | OpenAI 兼容网关方言 |
| `default_model.<provider>` | 每个 provider 的默认模型 |
| `batch.max_workers` | batch 最大 worker 数 |
| `provider_limits.<provider>.concurrency` | provider 并发上限 |
| `provider_limits.<provider>.start_interval_ms` | provider 启动间隔 |

## 约束

- 没填的字段就按运行时默认值处理
- `default_model` 只配置你真正会用的 provider
- 不要把 API key 写进这个文件

## 密钥位置

密钥统一放：

- `process.env`
- 项目根 `.env`

不要写进 `EXTEND.md`。

