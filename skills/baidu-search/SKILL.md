---
name: baidu-search
description: 使用百度 AI 搜索引擎进行网络搜索，获取实时信息、文档或研究主题
metadata: { "openclaw": { "emoji": "🔍︎",  "requires": { "bins": ["python3"] } } }
---

# 百度搜索

通过百度 AI 搜索 API 进行网络搜索，支持时间范围筛选和结果数量控制。

## 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | str | 是 | - | 搜索关键词 |
| count | int | 否 | 10 | 返回结果数量，范围 1-50 |
| freshness | str | 否 | 无 | 时间范围筛选<br>• 日期范围：`YYYY-MM-DDtoYYYY-MM-DD`<br>• 快捷方式：`pd`(24小时) `pw`(7天) `pm`(31天) `py`(365天) |

## 使用示例

```bash
# 基础搜索
python3 scripts/search.py '{"query":"人工智能"}'

# 指定日期范围
python3 scripts/search.py '{"query":"最新新闻","freshness":"2025-09-01to2025-09-08"}'

# 快捷时间范围（过去24小时）
python3 scripts/search.py '{"query":"最新新闻","freshness":"pd"}'

# 自定义结果数量
python3 scripts/search.py '{"query":"旅游景点","count":20}'
```
