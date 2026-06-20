# PrivacyTap Codex Responses 真实接入设计

日期：2026-06-20

## 1. 背景与目标

PrivacyTap 当前只支持非流式 `POST /v1/chat/completions`，无法直接服务使用
Responses API、SSE 流式响应和工具调用的 Codex CLI。

本次改造的目标是让真实 Codex CLI 使用 `OPENAI_API_KEY` 通过 PrivacyTap
访问 OpenAI，同时满足：

1. 原始隐私在请求离开本机前被替换。
2. OpenAI 和观测日志只接触脱敏内容。
3. Codex 收到恢复后的文本和工具参数。
4. API Key 只作为传输凭证使用，不进入归档。
5. 保留已有 Chat Completions Demo 与测试。

首期只保证 OpenAI Responses API 稳定接入。架构预留 Provider Adapter，
但不在本期实现 DeepSeek 的 Responses 协议转换。

## 2. 核心问题

传统 LLM 观测系统通常在请求完成后遮盖日志。这只能减少日志泄露，无法阻止
第三方模型服务接触 Prompt 中的原始隐私。简单的请求替换又会破坏 Codex
工具调用，因为模型生成的文件路径、命令参数或文件内容可能仍包含占位符。

本项目解决的问题是：

> 如何在第三方模型只看到匿名化数据的前提下，让 Codex 的流式输出和本地工具
> 调用仍能使用正确的原始数据，并保证观测链路不保存原文。

## 3. 方案选择

### 3.1 采用方案

实现 OpenAI Responses API 透明隐私代理：

```text
Codex CLI
  -> PrivacyTap /v1/responses
  -> 请求脱敏 + 请求级内存 Vault
  -> OpenAI Responses API
  -> 脱敏 SSE/JSON
  -> 本地流式恢复
  -> Codex CLI
```

### 3.2 未采用方案

- ChatGPT 登录态转发：用户明确要求使用 API Key。
- 仅支持 Chat Completions：Codex 当前使用 Responses 协议，无法满足真实接入。
- 首期同时转换 DeepSeek Chat Completions：协议转换和工具兼容范围过大，会降低
  课程 Demo 的稳定性。

## 4. Codex 配置

Provider 配置必须位于用户级 `~/.codex/config.toml`，不能放在项目级配置中：

```toml
[profiles.privacytap]
model = "gpt-5.4"
model_provider = "privacytap"

[model_providers.privacytap]
name = "PrivacyTap"
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"
env_key = "OPENAI_API_KEY"
```

运行方式：

```powershell
$env:OPENAI_API_KEY="sk-..."
privacytap start --provider openai
codex --profile privacytap
```

PrivacyTap 默认 OpenAI 上游为 `https://api.openai.com`，也允许通过
`--upstream-base-url` 覆盖，便于测试和私有网关部署。

## 5. 模块设计

### 5.1 `PrivacyProxyServer`

保留 `POST /v1/chat/completions`，新增：

- `POST /v1/responses`
- 可选健康检查 `GET /health`

该类只负责 HTTP 生命周期、请求大小限制、异常映射和响应写回，不直接承载
具体的 SSE 事件变换逻辑。

### 5.2 `OpenAIResponsesAdapter`

职责：

- 构建上游 `/v1/responses` URL。
- 转发必要 Header，移除 hop-by-hop Header。
- 不复制 `Authorization` 到日志或异常。
- 区分普通 JSON 响应和 `text/event-stream`。
- 保留上游业务状态码及安全响应。

Provider 接口保持独立，以便后续增加 DeepSeek Adapter，但本期不实现协议转换。

### 5.3 `StreamingRestorer`

Responses SSE 中的字符串可能在任意字节或事件边界被拆分。恢复器必须：

- 按请求持有 Vault，不使用全局共享状态。
- 解析完整 SSE frame，而不是对原始网络块做字符串替换。
- 对需要恢复的增量字段维护独立缓冲区。
- 保留可能是占位符前缀的尾部，匹配完整占位符后再输出。
- 正确处理 UTF-8 字符跨网络块拆分。
- 流结束时刷新安全尾部并销毁状态。

重点处理：

- `response.output_text.delta` 的 `delta`
- `response.function_call_arguments.delta` 的 `delta`
- 完整事件对象中其他字符串字段的占位符
- `response.completed` 中可能出现的完整 response 对象

不认识但结构合法的事件应透明转发；只有其中与 Vault 匹配的字符串才恢复。

### 5.4 `RequestVault`

- 每个请求创建独立 Vault。
- 同一原值在同一请求中映射到同一占位符。
- 请求结束、失败或客户端断开时释放引用。
- Vault 永不序列化、导出或进入日志。

### 5.5 `SafeTraceRecorder`

日志保存：

- 脱敏请求
- 上游脱敏响应或已重建的脱敏事件摘要
- 模型、Token、耗时、检测数量和请求结果

日志不保存：

- 原始请求
- Vault 映射
- `Authorization`、API Key或其他认证 Header
- 恢复后返回 Codex 的响应

日志失败不应导致模型调用失败。

## 6. 数据处理流程

### 6.1 请求

1. 校验 JSON 对象和请求大小。
2. 从 `Authorization: Bearer ...` 提取本次传输 Key，仅用于精确泄露检查。
3. 遍历 Responses 请求中的字符串内容。
4. 手机号、身份证、邮箱、银行卡和学号执行可逆替换。
5. Prompt 中若出现本次正在使用的真实 API Key，返回 HTTP 422。
6. 其他代码示例或测试凭证替换为 `[CREDENTIAL_n]`，不阻断代码分析。
7. 只向 OpenAI 发送脱敏后的请求。

Header 中合法携带的 API Key 不属于 Prompt 泄露，不被阻断。

### 6.2 非流式响应

1. 读取上游 JSON。
2. 将上游原始 JSON作为脱敏安全响应写入观测链路。
3. 使用请求 Vault 递归恢复 JSON 字符串。
4. 将恢复后的 JSON 返回 Codex。

### 6.3 流式响应

1. 持续解析上游 SSE frame。
2. 安全归档只接收上游脱敏事件。
3. 对文本增量和工具参数增量进行有状态恢复。
4. 重编码为合法 SSE 并立即发送给 Codex。
5. 客户端断开时取消上游请求并释放 Vault。

## 7. 工具调用

工具参数恢复是本项目区别于普通日志脱敏的关键。

例如模型看到：

```json
{"path":"students/[STUDENT_ID_1].json"}
```

PrivacyTap 返回 Codex 前恢复为：

```json
{"path":"students/2023123456.json"}
```

恢复发生在 `response.function_call_arguments.delta` 流中。由于参数 JSON
可能被多次切分，恢复器以 `call_id` 或输出项索引区分不同工具调用的缓冲状态，
不得把两个并行工具调用的字符混合。

## 8. API Key策略

- `OPENAI_API_KEY` 由 Codex 从环境变量读取并放入请求 Header。
- PrivacyTap只向配置的 OpenAI 上游转发认证 Header。
- 认证 Header 不进入事件、归档、Langfuse或异常消息。
- Prompt 中精确出现本次认证 Key时直接阻断。
- 其他看似凭证的代码内容执行可逆替换，以保证 Codex 可以审查包含示例 Key的代码。
- 日志及错误只记录凭证类型和数量，不记录内容或哈希。

## 9. 错误处理

| 情况 | 行为 |
|---|---|
| 非法 JSON 或非对象请求 | HTTP 400 |
| 请求体超限 | HTTP 413 |
| Prompt 包含当前认证 Key | HTTP 422 |
| 无法连接上游 | HTTP 502 |
| 上游超时 | HTTP 504 |
| 上游业务 4xx/5xx | 保留状态码，安全恢复响应 |
| SSE frame 无法解析 | 中止流，不转发未经处理的数据 |
| Codex 主动断开 | 取消上游请求，释放 Vault |
| 日志导出失败 | 记录警告，模型链路继续 |

任何错误消息都不得包含请求正文、认证 Header 或 Vault 内容。

## 10. 测试设计

### 10.1 单元测试

- Responses 请求脱敏和非流式响应恢复。
- 每类敏感信息的替换与恢复。
- 当前 API Key精确阻断。
- 其他测试凭证可逆替换。
- Header Key正常转发但不进入事件。
- SSE parser 支持 `\n`、`\r\n`、注释和多行 `data`。
- 占位符在每个字符边界拆分时均可恢复。
- UTF-8 字符跨网络块拆分。
- 多个并行工具调用独立恢复。

### 10.2 集成测试

使用本地测试上游模拟：

- `response.output_text.delta`
- `response.function_call_arguments.delta`
- `response.completed`
- 非流式 JSON
- 上游 4xx/5xx
- 超时、连接失败、异常 SSE
- 客户端提前断开

所有现有 Chat Completions 测试必须继续通过。

### 10.3 安全不变量

测试读取全部归档输出，并断言：

- 原始手机号、邮箱、身份证、银行卡、学号出现次数为 `0`。
- API Key出现次数为 `0`。
- Vault 占位符在安全日志中可见。
- 恢复后的客户端结果与原输入一致。

## 11. 真实 Codex 验收

使用真实 `OPENAI_API_KEY` 启动 PrivacyTap 和 Codex，执行：

```text
请记住：
学生邮箱为 test2026@example.com，
手机号为 13800138000。

在临时目录创建 contact.txt，写入上述信息，
然后读取文件并告诉我内容。
```

验收条件：

1. Codex 正常完成推理和文件工具调用。
2. 可控测试上游只接收到 `[EMAIL_1]`、`[PHONE_1]`。
3. Codex 工具参数和最终文件包含恢复后的真实值。
4. PrivacyTap 归档中不出现原值。
5. 请求结束后无可访问的 Vault 状态。

真实 OpenAI 无法直接提供用户可见的服务端原始请求证据，因此“上游只收到
脱敏值”由本地可控上游抓包测试证明；真实 OpenAI测试用于证明 Codex 协议和
工具链可运行。两类证据结合，避免仅凭客户端结果推断隐私保护成立。

## 12. 量化指标

| 指标 | 达标标准 |
|---|---:|
| 可控上游原始敏感信息泄露数 | 0 |
| 安全日志原始敏感信息泄露数 | 0 |
| API Key泄露数 | 0 |
| 替换后恢复正确率 | 100% |
| SSE 分片矩阵通过率 | 100% |
| Codex 真实任务成功率 | 至少 9/10 |
| 新增代码测试覆盖率 | 不低于 90% |
| 脱敏与恢复额外 P95 延迟 | 小于 20 ms |

## 13. CLI 与文档

目标命令：

```powershell
privacytap start `
  --provider openai `
  --upstream-base-url https://api.openai.com `
  --port 8080 `
  --archive-dir .\privacytap-traces
```

README 增加：

- Codex 用户级配置示例。
- `OPENAI_API_KEY` 环境变量说明。
- Mock、可控 SSE 和真实 Codex 三种演示方式。
- 不记录 API Key的安全说明。
- DeepSeek 尚未直接支持的边界说明。

## 14. 非目标

本期不实现：

- ChatGPT OAuth登录态转发。
- DeepSeek Chat Completions 与 Responses 的完整双向转换。
- Claude Code 协议。
- WebSocket Responses。
- 图片、音频和文件二进制内容的隐私识别。
- 跨请求持久化 Vault。
- 法律合规认证。

## 15. 完成定义

只有满足以下条件才能视为完成：

1. Codex 通过 `--profile privacytap` 使用真实 OpenAI API工作。
2. 文本流和工具参数都能正确恢复。
3. 现有功能无回归。
4. 自动化测试、覆盖率、安全不变量和性能指标达标。
5. README 提供可复制运行命令。
6. 可控上游测试与真实 Codex 演示均可复现。
