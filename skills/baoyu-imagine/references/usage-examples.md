# 用法示例

只在下面几种场景需要打开本文件：

- 用户要求指定 `provider`
- 用户要做 batch
- 用户要使用 `--ref`
- 用户要显式控制尺寸 / 宽高比 / 模型

## 单图

```bash
${BUN_X} {baseDir}/scripts/main.ts --prompt "A cat" --image out.png
${BUN_X} {baseDir}/scripts/main.ts --prompt "A landscape" --image out.png --ar 16:9 --quality 2k
${BUN_X} {baseDir}/scripts/main.ts --promptfiles system.md content.md --image out.png
```

## 参考图

```bash
${BUN_X} {baseDir}/scripts/main.ts --prompt "Make blue" --image out.png --ref source.png
```

适用前提：

- 当前 provider 支持 `--ref`
- 参考图路径已经真实存在

## 指定 provider / model

```bash
${BUN_X} {baseDir}/scripts/main.ts --prompt "A cat" --image out.png --provider dashscope --model qwen-image-2.0-pro
${BUN_X} {baseDir}/scripts/main.ts --prompt "A diagram" --image out.png --provider openai --model gpt-image-1.5
```

## Batch

```bash
${BUN_X} {baseDir}/scripts/main.ts --batchfile batch.json --jobs 4
```

适合：

- prompt 已经稳定
- 任务进入“批量执行”阶段

不适合：

- 每张图仍需单独探索风格
- prompt 还没落盘

## 上游 skill 的典型配合

如果上游 skill 已经生成了 `outline.md` 和 `prompts/`：

1. 先用 `scripts/build-batch.ts` 组装任务
2. 再把输出的 batch payload 交给 `scripts/main.ts --batchfile`

## 选择建议

- 普通出图：单图模式
- 多张稳定 prompt：batch
- 有参考图：先确认 provider 支持 `--ref`
- 有模型兼容问题：先看对应 provider 文档

