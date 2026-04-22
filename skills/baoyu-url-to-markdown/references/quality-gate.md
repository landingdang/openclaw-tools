# 抓取质量门槛

网页抓取成功不等于内容可用。  
即使 CLI 返回 `0`，也可能只抓到壳页面、登录框或空内容。

## 最低检查项

每次抓取后至少检查：

1. 标题是否正确
2. 正文是否真的存在
3. 内容是否明显过短
4. 是否抓到了登录框、订阅墙、验证码页
5. 是否只是导航、页脚、框架壳

## 常见失败信号

- `Application error`
- `This page could not be found`
- login / signup / subscribe 壳页面
- 明显过短的 markdown
- 大量框架 payload、脚本碎片、站点模板文本

## 恢复策略

如果抓取结果不可信：

1. 先切到 `--wait-for interaction`
2. 如果仍不够，再用 `--wait-for force`
3. 必要时提示用户完成：
   - 登录
   - 过验证码
   - 等页面完全展开

## 何时自动切交互

如果 JSON 输出里：

```text
status = "needs_interaction"
```

就应自动转交互模式，而不是把低质量结果直接交付。

