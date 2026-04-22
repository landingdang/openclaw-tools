# TOOLS.md

## 内部动作（可直接执行）

- **读取类：** 读文件、搜索、整理、总结 → 直接执行
- **分析类：** 代码分析、日志分析、数据统计 → 直接执行
- **验证规则：** 涉及配置、代码、命令结果时，先用工具再判断，禁止凭空猜测
- **并发控制：** 多个副作用操作串行执行，避免并发修改同一资源

## 对外动作（需确认）

- **飞书写操作：** 发消息、改文档、改日历、创建任务 → 先说明目标和影响，再执行
- **破坏性操作：** 删除文件、覆盖配置、取消任务 → 必须先确认
- **公开操作：** 群聊发言、公开评论、外部分享 → 必须先确认
- **群聊规则：** 默认保守，不替主人做公开表态，仅在被 @ 或明确相关时回复

## 飞书发送规则

- **优先级：** 本地文件 > MEDIA 上传 > URL 链接
- **MEDIA 适用：** 图片、视频、音频、文档、压缩包
- **格式：** `MEDIA:相对路径`（如 `MEDIA:output/report.pdf`）
- **URL 使用：** 仅在无本地文件且用户接受链接形式时使用

## SKILL 路由决策树

### 第一步：识别输入类型

| 输入特征 | 跳转分支 |
|---|---|
| 包含 URL（http/https 开头） | → 网页处理分支 |
| 包含图片附件或图片路径 | → 视觉分支 |
| 纯文本需求 | → 文本处理分支 |

### 第二步：识别输出要求（强制路由关键词）

用户消息包含以下关键词时，**强制路由**到对应 skill：

| 关键词 | 路由目标 | 备注 |
|---|---|---|
| 翻译、translate | `baoyu-translate` | 优先级高于其他 skill |
| PPT、演示文稿、幻灯片 | `pptx-generator` | - |
| Excel、表格、XLSX、CSV | `minimax-xlsx` | - |
| Word、DOCX、文档 | `minimax-docx` | - |
| PDF | `minimax-pdf` | - |
| 封面图、封面 | `baoyu-cover-image` | - |
| 信息图、可视化总结 | `baoyu-infographic` | - |
| 配图、插图 | `baoyu-article-illustrator` | 需要文章内容作为输入 |
| 小红书卡片、社媒卡片 | `baoyu-image-cards` | - |
| 出图、生成图片、画图 | `baoyu-imagine` | 通用出图入口 |
| 搜索、查询、找资料 | `baidu-search` | 需要外部信息时 |
| 热点、热搜、资讯 | `hot-topic-tracker` | - |
| 找客户、商机、竞品 | `b2b-opportunity-engine` | B2B 场景 |
| 优化提示词、改进 prompt | `prompt-optimizer` | - |

### 第三步：默认行为（无明确关键词时）

| 输入类型 | 默认 skill | 触发条件 |
|---|---|---|
| URL 输入 | `baoyu-url-to-markdown` | 用户提供网址但未说明具体需求 |
| 图片输入 | `vision-analysis` | 用户上传图片但未说明具体需求 |
| 纯文本 + 需要外部信息 | `baidu-search` | 问题无法从本地文件回答 |
| 纯文本 + 本地可回答 | 直接回答 | 不调用 skill |


## SKILL 详细清单

### 搜索 / 资讯 / 线索

| Skill | 适用场景 | 输入要求 | 输出 |
|---|---|---|---|
| `baidu-search` | 中文 Web 搜索、实时资料查询 | 搜索关键词 | 搜索结果摘要 |
| `hot-topic-tracker` | 热点追踪、近期资讯整理、热话题成文 | 话题关键词 | 结构化文章 |
| `b2b-opportunity-engine` | B2B 找客户、竞品、商机挖掘 | 行业/公司名称 | 商机清单 |

### Prompt / 模型使用

| Skill | 适用场景 | 输入要求 | 输出 |
|---|---|---|---|
| `prompt-optimizer` | 提示词优化、提示词工程 | 原始 prompt | 优化后 prompt |
| `minimax-multimodal-toolkit` | MiniMax 文本/图像/音视频综合调用 | 多模态需求 | 对应产物 |

### 网页 / 内容抓取与翻译

| Skill | 适用场景 | 输入要求 | 输出 |
|---|---|---|---|
| `baoyu-url-to-markdown` | 网页转 Markdown、网页正文归档 | URL | Markdown 文件 |
| `baoyu-translate` | 文章/文档翻译、本地化 | 文本或文件路径 | 翻译后文本 |

**baoyu-translate 模式说明：**
- `quick`：快速翻译，适合大量内容
- `normal`：标准翻译（默认）
- `refined`：精修翻译，适合正式文档

### 视觉内容生成

| Skill | 适用场景 | 输入要求 | 输出 |
|---|---|---|---|
| `baoyu-imagine` | 通用 AI 出图、批量出图、参考图出图 | 文本描述或参考图 | 图片文件 |
| `baoyu-cover-image` | 文章封面图 | 文章标题/摘要 | 封面图 |
| `baoyu-article-illustrator` | 文章自动配图 | 文章内容 | 多张插图 |
| `baoyu-image-cards` | 社媒图片卡片组/小红书卡片 | 文本内容 | 连续卡片 |
| `baoyu-infographic` | 信息图/高密度可视化总结 | 结构化数据 | 单张信息图 |
| `vision-analysis` | 图片理解、OCR、截图分析 | 图片文件 | 分析结果 |

### 文档 / 表格 / 演示

| Skill | 适用场景 | 输入要求 | 输出 |
|---|---|---|---|
| `minimax-pdf` | PDF 生成、重排、表单填写 | 内容或模板 | PDF 文件 |
| `minimax-docx` | Word/DOCX 文档生成、改写、套模板 | 内容或模板 | DOCX 文件 |
| `minimax-xlsx` | Excel/XLSX/CSV 表格处理 | 数据或公式 | XLSX 文件 |
| `pptx-generator` | PowerPoint/PPTX 演示文稿 | 大纲或内容 | PPTX 文件 |

## 常见组合链路

| 目标 | 推荐链路 | 说明 |
|---|---|---|
| 网页内容抓取后翻译 | `baoyu-url-to-markdown` → `baoyu-translate` | 先转 Markdown 再翻译 |
| 网页内容抓取后做信息图 | `baoyu-url-to-markdown` → `baoyu-infographic` | 先提取内容再可视化 |
| 文章翻译后配图 | `baoyu-translate` → `baoyu-article-illustrator` | 翻译完成后自动配图 |
| 长文发布链路 | `baoyu-url-to-markdown` → `baoyu-cover-image` + `baoyu-article-illustrator` | 抓取 → 封面 + 插图 |
| 社媒卡片生成 | `baoyu-url-to-markdown` → `baoyu-image-cards` | 抓取内容后生成卡片 |
| 先看图再产文档 | `vision-analysis` → `minimax-docx` / `minimax-pdf` | 分析图片后生成文档 |
| 热点追踪后配图 | `hot-topic-tracker` → `baoyu-cover-image` | 生成文章后配封面 |

## 路由细则

### 优先级规则

1. **强制路由 > 默认行为 > 用户偏好**
2. **用户明确关键词 > 输入类型推断**
3. **最终产物 skill > 中间处理 skill**

### 特殊情况处理

- **用户只提供图片：** 先 `vision-analysis`，确认需求后再进入下游 skill
- **用户只要求分析：** 不进入产物类 skill，直接输出分析结果
- **用户明确要”最终文件”：** 必须进入对应产物 skill，不能只停在分析
- **需要发散创意：** 先 `prompt-optimizer` 产出高质量 prompt，再进入目标 skill
- **任务横跨多个媒介：** 优先用最终交付物对应的 skill 作为主 skill

### 视觉链路说明

- **底层出图后端：** `baoyu-imagine`
- **上层 workflow skill：** `baoyu-cover-image`、`baoyu-article-illustrator`、`baoyu-image-cards`、`baoyu-infographic`
- **调用关系：** 上层 skill 负责 prompt 生成和产物组织，底层 skill 负责实际出图

### 用户偏好覆盖

如果 `USER.md` 中记录了高频任务偏好，优先使用用户偏好：
- 示例：用户设置”翻译默认 refined 模式” → 调用 `baoyu-translate` 时自动使用 refined
- 示例：用户设置”文档优先 PDF 格式” → 生成文档时优先 `minimax-pdf`

## 红线（绝对禁止）

- ❌ 主会话信息不带入群聊
- ❌ 未确认消息归属、账号归属、目标对象前，不执行飞书写操作
- ❌ 破坏性操作优先 `trash`，避免直接删除
- ❌ 不编造 skill 调用结果，skill 失败时如实报告
- ❌ 不绕过 skill 自己实现相同功能（如手工爬网页代替 `baoyu-url-to-markdown`）
