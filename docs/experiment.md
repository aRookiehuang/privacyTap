# PrivacyTap 实验设计

## 1. 检测数据集

`tests/fixtures/privacy_cases.json` 为人工标注数据，包含六类正例以及容易误判的普通数字、错误校验值、短 Token 和不完整邮箱。

| 指标 | 公式 |
|---|---|
| Precision | TP / (TP + FP) |
| Recall | TP / (TP + FN) |
| F1 | 2PR / (P + R) |

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

## 2. 全链路指标

| 指标 | 采集方法 | 目标 |
|---|---|---:|
| 上游泄露率 | Mock 上游中的原始实体 / 输入实体 | 0 |
| 归档泄露率 | JSON/Markdown 中的原始实体 / 输入实体 | 0 |
| 恢复正确率 | 正确恢复的占位符 / 应恢复占位符 | 100% |
| API Key 阻断率 | 未到达上游的凭证请求 / 凭证请求 | 100% |
| 并发串线数 | 返回其他请求敏感值的请求 | 0 |
| Transform P95 | 检测与替换阶段第 95 百分位 | < 20 ms |

## 3. 对照实验

### 无隐私代理

客户端原始 Prompt 直接发送给 Mock 上游并由应用日志记录。

### PrivacyTap

五类 PII 匿名化、API Key 阻断、安全归档、响应恢复。

对比：

- 上游能否看到原值；
- 日志能否看到原值；
- 最终响应是否保持可用；
- 额外处理耗时。

## 4. 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

实验报告只填写命令的真实输出，不预先编造数据。
