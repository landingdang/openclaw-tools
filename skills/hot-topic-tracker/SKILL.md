---
name: hot-topic-tracker
description: Track fast-moving topics from a vague keyword or subject and turn them into source-grounded long-form content. Use when the user asks for 热点追踪、爆点话题挖掘、最新动态梳理、行业动态、人物资讯、事件追踪、新媒体长文, or wants recent authoritative sources, hot subtopics from the last 1-5 days, an 800-1500字 article, and fact checking before delivery. This skill must first resolve ambiguity with mandatory web search, then search sources, mine 3-5 fully relevant hot topics, deepen research on each topic, write the article, and fact-check key claims.
---

# 热点追踪专家

## Overview

把用户的模糊主题变成一篇有信源、有时效性、有观点的长文。

默认使用当前平台的网络搜索与网页访问工具完成检索和核查。在 Codex 中优先使用 `web.search_query` 和 `web.open`。

## Execution Order

- 严格按 `第一步 -> 第二步 -> 第三步 -> 第四步 -> 第五步 -> 第六步` 执行。
- 只有第四步允许并行；其余步骤必须串行。
- 第一步如果确认存在真实歧义，必须先向用户确认，再继续后续步骤。
- 所有时效性判断都看事件实际发生时间，不看报道发布时间。
- 输出和核查都使用绝对日期，不用“今天/昨天/最近”这种模糊表达。

## 第一步：理解输入

- 无论用户输入多短、多模糊、多具体，都先搜索原始关键词，了解它在现实世界里的指向。
- 判断搜索结果是否存在跨领域同名、缩写多义、人名重名、产品名重合等歧义。
- 如果有歧义，只给出简洁选项并等待用户确认。
- 如果没有歧义，提取：
  - 主题
  - 领域
  - 一句话简介
  - 用户可能关心的问题 3-5 个
  - 建议搜索关键词至少 3 个
  - 追踪参数建议：时间范围、内容类型、地域范围
- 需要确认时，使用 [references/output-formats.md](references/output-formats.md) 中的歧义确认模板。

## 第二步：搜索信源

- 基于第一步拆出的核心问题做多组关键词搜索，不要只搜一个词。
- 优先级依次为：官方渠道、权威媒体、行业垂直媒体、可交叉验证的社交平台内容。
- 对重要信息尽量找到原始公告、原始采访、原始数据或直接引语。
- 记录时间、人物、机构、事件、关键数据、原话、链接和可信度。
- 在进入第三步前，先整理出结构化信源报告。
- 信源报告模板见 [references/output-formats.md](references/output-formats.md)。

## 第三步：挖掘爆点话题

- 只从第二步的有效信源中挖掘 3-5 个爆点话题。
- 话题必须与用户主题完全相关，不能把背景介绍、历史回顾、外围花絮当成主话题。
- 时效性排序：
  - 1 天内：最高优先级
  - 3 天内：高优先级
  - 5 天内：可纳入
  - 超过 5 天：原则上排除，除非是仍在演进的重大事件
- 合并重复话题，只保留最有写作价值的角度。
- 每个话题都要写清：
  - 实际发生日期
  - 时效性评级
  - 与主题的直接关联
  - 核心看点
  - 对应信源
- 话题报告模板见 [references/output-formats.md](references/output-formats.md)。

## 第四步：深入搜索爆点话题

- 这是唯一可以并行的步骤。
- 对每个入选话题分别补足：
  - 更完整的事件背景
  - 多方观点
  - 关键数据
  - 可直接引用的人物发言
  - 与大众讨论不同的切入角度
- 所有话题的补充搜索完成后，才进入写作。

## 第五步：撰写长文

- 基于第三步和第四步的结果，写出 800-1500 字长文。
- 标题要求：
  - 20 字以内
  - 有网感
  - 不标题党
- 正文要求：
  - 保持信息密度
  - 章节标题要清晰、具体、有节奏
  - 重点信息用 `**加粗**`
  - 直接引语用 Markdown 引用格式 `>`
  - 明确写出时间、地点、人物、机构、金额、数量、产品名等关键事实
- 必须避免：
  - 说教式结尾
  - “首先、其次、最后”式机械连接
  - 空洞展望
  - 编造数据或引语
- 默认保存为当前工作目录下的 `article_[YYYYMMDD].md`，除非用户指定了其他路径。
- 文章骨架模板见 [references/output-formats.md](references/output-formats.md)。

## 第六步：事实核查

- 只抽取关键事实陈述进行核查，重点覆盖：
  - 时间
  - 金额、数量、比例、排名
  - 人物原话
  - 事件经过
  - 专有名词
- 优先用官方和一手信源核对；无法确认时标记“存疑”，不要硬判。
- 发现错误后先修正文稿，再输出最终结果。
- 事实核查报告模板见 [references/output-formats.md](references/output-formats.md)。

## Deliverables

最终交付默认包含 4 项：

1. 100 字内追踪摘要
2. 爆点话题列表
3. 已保存的 Markdown 长文路径与简短预览
4. 事实核查报告

如用户需要过程材料，再附上第二步的信源报告与第三步的话题挖掘报告。

## Recurring Runs

- 如果这是定时/周期性追踪任务且当前请求没有给出新主题，优先沿用上次追踪主题。
- 重点输出新增事件、已变化信息和需要更新的判断，不重复铺陈旧信息。

## Quality Bar

- 准确性优先于覆盖面。
- 任何带时间敏感性的事实都先搜再写。
- 不要把单一信源当成定论。
- 不要跳步，不要提前写稿，不要跳过核查。
- 第一步若有歧义，宁可暂停确认，也不要误追踪。
