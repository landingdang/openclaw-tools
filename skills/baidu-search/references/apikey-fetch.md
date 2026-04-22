# 百度 API 密钥配置指南

## 配置步骤

### 1. 获取 API 密钥
访问：**https://console.bce.baidu.com/ai-search/qianfan/ais/console/apiKey**

- 登录百度云账号
- 创建应用或查看已有的 API 密钥
- 复制 **API Key**

### 2. 保存到项目根目录的 `.env` 文件

在项目根目录创建或编辑 `.env` 文件，添加：

```bash
BAIDU_API_KEY=your_actual_api_key_here
```

### 3. 验证配置
```bash
cat .env
```

### 4. 测试搜索功能
```bash
python3 skills/baidu-search/scripts/search.py '{"query":"测试搜索"}'
```

## 常见问题

- **密钥无效**：确认 `.env` 文件存在且 API 密钥正确
- **服务未激活**：登录百度云控制台确认 AI 搜索服务已开通
- **余额不足**：检查百度云账户余额
- **格式错误**：避免在 `.env` 文件中使用多余的引号或尾随空格
