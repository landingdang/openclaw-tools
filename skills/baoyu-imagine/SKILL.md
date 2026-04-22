---
name: baoyu-imagine
description: 使用 OpenAI、Azure OpenAI、Google、OpenRouter、DashScope、Z.AI、MiniMax、Jimeng、Seedream、Replicate 进行 AI 出图。支持文生图、参考图、宽高比控制和批量出图。Use when user asks to generate images, create illustrations, draw pictures, 文生图, 出图, 画图, 批量生成图片.
version: 1.57.0
metadata:
  openclaw:
    homepage: https://github.com/JimLiu/baoyu-skills#baoyu-imagine
    requires:
      anyBins:
        - bun
        - npx
---

# AI 出图

多模型 AI 出图，支持 OpenAI、Azure、Google、OpenRouter、DashScope、Z.AI、MiniMax、Jimeng、Seedream、Replicate。

## 执行准备

- `{baseDir}` = 当前 SKILL.md 所在目录
- 优先使用 `bun`
- 入口：`scripts/main.ts`、`scripts/build-batch.ts`

常用命令：

```bash
${BUN_X} {baseDir}/scripts/main.ts --prompt "A cat" --image cat.png
${BUN_X} {baseDir}/scripts/main.ts --promptfiles system.md content.md --image out.png
${BUN_X} {baseDir}/scripts/main.ts --prompt "A landscape" --image out.png --ar 16:9 --quality 2k
${BUN_X} {baseDir}/scripts/main.ts --prompt "Make blue" --image out.png --ref source.png
${BUN_X} {baseDir}/scripts/main.ts --batchfile batch.json --jobs 4
```

## 配置

配置文件：`{workspace}/.baoyu/baoyu-imagine.md`

支持配置：
- `default_provider` - 默认 provider
- `default_model` - 默认模型
- `default_quality` - 默认质量
- `default_output_dir` - 默认输出目录
- 默认宽高比

首次使用自动采集配置并保存。

## 密钥

密钥统一存放在项目根目录 `.env` 文件。

脚本会自动向上查找包含 `.env` 的目录（最多向上 10 层），找到的第一个 `.env` 文件即为密钥文件。

**需要的密钥：**
```bash
OPENAI_API_KEY=sk-xxx
GOOGLE_API_KEY=xxx
MINIMAX_API_KEY=xxx
DASHSCOPE_API_KEY=xxx
ZAI_API_KEY=xxx
REPLICATE_API_TOKEN=xxx
JIMENG_ACCESS_KEY_ID=xxx
JIMENG_SECRET_ACCESS_KEY=xxx
ARK_API_KEY=xxx
```

## 输出路径

默认输出到：`{workspace}/media/baoyu-imagine/{timestamp}-{task-slug}/`

**路径组成：**
- `{workspace}` - 智能体工作目录
- `media/` - 固定媒体目录
- `baoyu-imagine/` - skill 名称
- `{timestamp}` - 任务时间戳（格式：2026-04-22_10-30-45）
- `{task-slug}` - 任务标识（从 prompt 生成）

**自定义路径：**
- CLI 参数：`--image /custom/path` 或 `--image relative/path`
- 配置文件：设置 `default_output_dir`

**示例：**
```bash
# 使用默认路径
bun scripts/main.ts --prompt "Hero Image"
# 输出：{workspace}/media/baoyu-imagine/2026-04-22_10-30-45-hero-image/image.png

# 使用相对路径
bun scripts/main.ts --prompt "Hero" --image my-images/hero.png
# 输出：{workspace}/my-images/hero.png

# 使用绝对路径
bun scripts/main.ts --prompt "Hero" --image /tmp/hero.png
# 输出：/tmp/hero.png
```

## 常用参数

| 参数 | 说明 |
|---|---|
| `--prompt <text>` / `-p` | 直接传 prompt |
| `--promptfiles <files...>` | 从多个文件拼接 prompt |
| `--image <path>` | 单图输出路径，单图模式必填 |
| `--batchfile <path>` | 批量任务文件 |
| `--jobs <count>` | batch worker 数量 |
| `--provider <name>` | 指定 provider |
| `--model <id>` | 指定模型 |
| `--ar <ratio>` | 宽高比 |
| `--size <WxH>` | 显式尺寸 |
| `--quality normal|2k` | 质量档位 |
| `--imageSize 1K|2K|4K` | Google/OpenRouter 图像尺寸 |
| `--imageApiDialect openai-native|ratio-metadata` | OpenAI 兼容网关方言 |
| `--ref <files...>` | 参考图 |
| `--n <count>` | 生成张数 |
| `--json` | JSON 输出 |

## Provider 选择

自动选择规则：
1. 用户指定 `--provider` → 直接使用
2. 传了 `--ref` → 优先支持参考图的 provider
3. 只检测到一个 API key → 直接用
4. 多个可用 → 默认优先级：Google → OpenAI → Azure → OpenRouter → DashScope → Z.AI → MiniMax → Replicate → Jimeng → Seedream

每次生成前明确告知：`Using [provider] / [model]`

## 批量模式

适用场景：
- 多组 prompt 已准备好
- 已有 `outline.md` + `prompts/`
- 进入”纯生成”阶段

不适用场景：
- 每张图还在探索风格
- prompt 未稳定
- 还在”创意设计”阶段

## 执行约束

- 视觉类上游 skill 要求”先写 prompt 文件” → 必须遵守
- 单图模式必须有 `--image`
- provider 不支持 `--ref` → 不强行传参
- 缺 API key → 报错并提示写入 `.env`

## 完成输出

- 使用的 provider
- 使用的 model
- 输出文件路径
- 成功/失败数量（批量）
- 失败原因（如有）
