# 实验设计与指标

## 1. 数据集

`tests/fixtures/privacy_cases.json` 包含六类正例及容易误判的负例。期望标签由人工填写，不由检测器自动生成。

## 2. 检测指标

| 指标 | 公式 |
|---|---|
| Precision | TP / (TP + FP) |
| Recall | TP / (TP + FN) |
| F1 | 2 × Precision × Recall / (Precision + Recall) |

运行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

## 3. 链路安全指标

| 指标 | 采集方法 |
|---|---|
| 上游泄露率 | Mock 上游仍存在的原始敏感实体数 / 输入实体总数 |
| 观测泄露率 | 安全事件、文件、Langfuse 参数中的原始实体数 / 输入实体总数 |
| 恢复正确率 | 最终响应正确恢复数 / 应恢复占位符数 |
| API Key 阻断率 | 未到达上游的凭证请求数 / 凭证请求总数 |
| 并发隔离错误数 | 返回了其他请求敏感值的请求数量 |

目标：

- 上游泄露率：0；
- 观测泄露率：0；
- 恢复正确率：100%；
- API Key 阻断率：100%；
- 并发隔离错误数：0。

## 4. 性能指标

使用 `time.perf_counter()` 统计纯检测与替换耗时，不包括模型网络耗时。记录 P50、P95；4 KB 以内请求的目标 P95 小于 20 ms。

## 5. 对照实验

### 基线 TokenTap

原始 Prompt 直接发送并写入日志。

### PrivacyTap

PII 匿名化、API Key 阻断、安全观测、响应恢复。

对比项：

- 模型上游是否看到原值；
- 本地日志是否看到原值；
- 最终用户是否获得可用响应；
- 额外处理耗时。

## 6. 结果填写规则

报告只能填写当次命令的真实输出，不预先编造数据。完整测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```
