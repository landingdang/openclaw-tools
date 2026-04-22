# Subagent 提示模板

当长文需要分块翻译时，主 agent 负责：

- 统一分析
- 统一术语
- 统一风格
- 统一收尾

subagent 只负责翻译分块。

## 共享上下文文件

主 agent 先生成：

```text
02-prompt.md
```

里面应包含：

- 目标语言
- 受众
- 风格
- 内容背景
- 术语表
- 翻译难点

## 分块 subagent 提示

适用于 `chunk-NN.md`：

```text
Read translation instructions from: {output_dir}/02-prompt.md

Translate chunk {NN} of {total_chunks}.
1. Read {output_dir}/chunks/chunk-{NN}.md
2. Translate following 02-prompt.md
3. Save to {output_dir}/chunks/chunk-{NN}-draft.md
```

## 非分块模式

如果整篇内容不需要 chunk，可直接用：

```text
Read translation instructions from: {output_dir}/02-prompt.md

Translate:
1. Read {source_file_path}
2. Save to {output_path}
```

## 约束

- subagent 不负责终稿定稿
- subagent 不负责最终润色
- subagent 不应自行改术语表

