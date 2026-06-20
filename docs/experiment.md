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
| 当前 API Key 阻断率 | 未到达上游的当前认证 Key请求 / 该类请求 | 100% |
| 示例凭证匿名化率 | 被替换的代码凭证 / 检出的代码凭证 | 100% |
| 并发串线数 | 返回其他请求敏感值的请求 | 0 |
| SSE 分片恢复率 | 每个字符边界切分后正确恢复数 / 总切分数 | 100% |
| Transform P95 | 检测与替换阶段第 95 百分位 | < 20 ms |
| Streaming P95 | SSE 增量恢复阶段第 95 百分位 | < 20 ms |

## 3. 对照实验

### 无隐私代理

客户端原始 Prompt 直接发送给 Mock 上游并由应用日志记录。

### PrivacyTap

五类 PII 匿名化、当前认证 Key精确阻断、代码凭证匿名化、安全归档、
Responses SSE 和工具参数恢复。

对比：

- 上游能否看到原值；
- 日志能否看到原值；
- 最终响应是否保持可用；
- 额外处理耗时。

## 4. 两层证据设计

### 4.1 可控上游实验

启动 `examples/mock_responses_upstream.py`，记录 PrivacyTap 发出的实际 JSON
与 SSE 请求。该实验直接证明离开 PrivacyTap 的内容只有占位符，不能只根据
客户端最终显示结果进行推断。

采集：

- Mock 终端实际请求；
- `privacytap-traces` JSON/Markdown；
- 客户端恢复后 SSE；
- 原始实体在前两类材料中的出现次数。

### 4.2 真实 Codex 实验

使用真实 `OPENAI_API_KEY`、OpenAI Responses API 和：

```powershell
codex --profile privacytap
```

让 Codex 创建并读取包含邮箱、手机号的临时文件。该实验用于证明：

- Codex Responses 协议兼容；
- SSE 输出可以持续消费；
- 工具参数与文件内容能够本地恢复；
- 项目不是只对 Mock 客户端有效。

真实 OpenAI 不提供用户可直接下载的服务端原始 Prompt 证据，因此上游无泄露
由可控实验负责证明，真实实验负责证明兼容性。二者不能相互替代。

## 5. 十次真实任务记录

课程报告按真实运行结果填写：

| 次数 | Codex 是否完成 | 文件是否正确 | 日志泄露数 | 失败原因 |
|---:|---|---|---:|---|
| 1 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 2 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 3 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 4 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 5 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 6 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 7 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 8 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 9 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |
| 10 | 待实验填写 | 待实验填写 | 待实验填写 | 待实验填写 |

成功率计算为：成功完成次数 / 10。目标不少于 9/10。不得预先填写成功数据。

## 6. 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

实验报告只填写命令的真实输出，不预先编造数据。
