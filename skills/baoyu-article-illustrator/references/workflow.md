# 详细工作流

## 目标

把“文章配图”拆成稳定的 6 步：

1. 读取偏好
2. 分析文章
3. 生成配图大纲
4. 生成 prompt 文件
5. 批量或逐张出图
6. 回写文章

## 第 1 步：读取偏好

优先读取当前工作区的 `./.baoyu/baoyu-article-illustrator.md`。

如果没有：

- 走 `config/first-time-setup.md`
- 只问偏好，不提前问正文内容

## 第 2 步：分析文章

分析时重点关注：

- 哪些段落理解门槛高
- 哪些段落适合图解而不是文字
- 哪些位置需要流程图 / 对比图 / 场景图

输出：

- `analysis.md` 或等价分析摘要

## 第 3 步：大纲

输出 `outline.md`，记录：

- 序号
- 插图位置
- 作用
- 文件名

## 第 4 步：写 prompt

每张图都要先有文件：

```text
prompts/NN-{type}-{slug}.md
```

如果使用参考图：

- 先落盘到 `references/`
- 再在 prompt 中声明用途

## 第 5 步：出图

默认优先 `baoyu-imagine`。

如果 prompt 已经都稳定：

- 优先 batch

如果 prompt 还在快速迭代：

- 逐张生成

## 第 6 步：回写

图片生成后，把相对路径插回文章。

## 默认输出目录

```text
media/baoyu-article-illustrator/{topic-slug}/
```
