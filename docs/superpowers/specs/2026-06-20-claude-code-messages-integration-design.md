# PrivacyTap Claude Code Messages 真实接入设计

日期：2026-06-20

## 1. 背景与目标

PrivacyTap 当前支持 OpenAI Responses API，可供 Codex CLI 使用，但尚未实现
Claude Code 使用的 Anthropic Messages 协议。

本次扩展目标：

1. 让 Claude Code 2.1.177 通过 `ANTHROPIC_BASE_URL` 接入 PrivacyTap。
2. 使用 `ANTHROPIC_API_KEY` 访问 Anthropic 官方 API。
3. 支持 `/v1/messages` 的普通 JSON 与 SSE 流式响应。
4. 支持 `/v1/messages/count_tokens`。
5. 恢复 Claude 文本输出和 `tool_use` 工具参数。
6. Anthropic、归档和 Langfuse 只接触脱敏数据。
7. 保持现有 Codex Responses 和 Chat Completions 功能兼容。

## 2. 核心问题

Claude Code 通过 Anthropic Messages API 发送系统提示、仓库内容、工具结果和用户
输入。若这些数据含敏感信息，直接调用会将原值发送给第三方模型。

仅替换请求内容还不够：Claude 的工具调用参数通过
`content_block_delta.delta.partial_json` 分片返回。若占位符未在本机恢复，
Claude Code 将使用占位符执行文件读写、Shell 命令或其他工具。

本项目解决：

> 如何在 Anthropic 上游只看到匿名化数据的同时，让 Claude Code 的文本响应和
> 工具调用继续使用原始值，并保证 API Key和原始隐私不进入观测链路。

## 3. 方案选择

采用原生 Anthropic Messages 透明适配：

```text
Claude Code
  -> PrivacyTap /v1/messages
  -> 请求脱敏 + RequestVault
  -> Anthropic /v1/messages
  -> 脱敏 JSON / SSE
  -> 本地文本和工具参数恢复
  -> Claude Code
```

不采用：

- Anthropic Messages 与 OpenAI Responses 双向转换：工具、thinking、签名和
  缓存字段转换风险过高。
- 首期使用 DeepSeek 作为 Claude Code 主上游：缺少足够稳定的官方 Messages
  全协议兼容证据。
- Claude 订阅 OAuth转发：本期只保证标准 Anthropic API Key。

## 4. Claude Code 配置

PowerShell：

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
$env:ANTHROPIC_API_KEY="sk-ant-..."
claude
```

非交互验证：

```powershell
claude --bare -p "Reply with exactly OK"
```

`--bare` 模式只使用 `ANTHROPIC_API_KEY` 或显式设置的 key helper，不读取 OAuth
或系统 Keychain，更适合作为可复现验证。

## 5. HTTP 接口

新增：

- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

保留：

- `POST /v1/responses`
- `POST /v1/chat/completions`

默认请求体上限仍为 2 MiB。

## 6. 模块边界

### 6.1 `AnthropicMessagesAdapter`

职责：

- 构建 Anthropic `/v1/messages` 和 `/v1/messages/count_tokens` URL。
- 转发 Anthropic 所需 Header。
- 移除 hop-by-hop Header。
- 区分 JSON 与 `text/event-stream`。
- 关闭上游响应和 ClientSession。

### 6.2 `AnthropicEventRestorer`

职责：

- 解析 Anthropic SSE 事件 JSON。
- 恢复 `text_delta.text`。
- 恢复 `input_json_delta.partial_json`。
- 按 content block index 维护独立缓冲。
- 在 `content_block_stop`、`message_stop` 或流结束时安全刷新尾部。
- 保留未知字段和未知事件。

### 6.3 共享组件

继续复用：

- `sanitize_payload`
- `RequestVault`
- `StreamingRestorer`
- `SSEParser`
- `encode_sse`
- 安全归档和 Langfuse Exporter

Anthropic 与 OpenAI 的事件结构不同，事件恢复器不得互相复用协议判断代码。

## 7. Header 与认证

必须转发但不得归档：

- `x-api-key`
- `authorization`
- `anthropic-version`
- `anthropic-beta`
- `X-Claude-Code-Session-Id`
- Claude Code 的 Agent/版本标识 Header

仍移除：

- `host`
- `content-length`
- `content-encoding`
- `connection`
- `transfer-encoding`
- 其他 hop-by-hop Header

当前请求认证凭证来源：

1. `x-api-key`
2. `Authorization: Bearer ...`

如果请求正文精确包含当前凭证，返回 HTTP 422，且不调用上游。代码中的其他
API Key样例使用 `[CREDENTIAL_n]` 可逆替换。

## 8. 请求处理

### 8.1 `/v1/messages`

递归处理全部字符串字段，包括：

- `system`
- `messages[].content`
- 文本 block
- `tool_result` 内容
- tool schema 描述
- metadata 中的字符串

字段名称、数字、布尔值、数组和对象结构保持不变。

### 8.2 `/v1/messages/count_tokens`

请求使用相同脱敏策略后发送上游。响应只包含 Token 计数，不需要 Vault 恢复，
但必须：

- 保留上游状态码；
- 不记录认证 Header；
- 记录脱敏请求和安全响应；
- 超时与连接失败使用统一错误映射。

## 9. 非流式 Messages 响应

上游 JSON先作为脱敏安全响应记录，再递归恢复：

- `content[].text`
- `content[].input`
- 其他包含占位符的字符串

恢复后 JSON 返回 Claude Code。

Token 用量：

```text
input_tokens + output_tokens
```

如 Anthropic 响应包含 cache creation/read token，可另外记录，但不改变
`tokens` 的基础口径。

## 10. Anthropic SSE 恢复

重点事件：

- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`
- `ping`
- `error`

重点增量：

```json
{
  "type": "content_block_delta",
  "index": 0,
  "delta": {
    "type": "text_delta",
    "text": "[PHONE_1]"
  }
}
```

```json
{
  "type": "content_block_delta",
  "index": 1,
  "delta": {
    "type": "input_json_delta",
    "partial_json": "{\"path\":\"[EMAIL_1]\"}"
  }
}
```

流标识：

- 文本：`text:<index>`
- 工具参数：`tool:<index>`

`content_block_stop` 到达前先刷新该 index 的待处理尾部。`message_stop` 和网络流
结束时刷新全部剩余缓冲。

Anthropic SSE 没有 OpenAI Responses 的 `sequence_number` 约束，因此新增尾部
事件时只需保留正确事件类型、index 和 delta 结构。

## 11. Thinking 与签名字段

Claude 可能返回 thinking block、`thinking_delta` 或 `signature_delta`。

本期策略：

- 不修改签名字段。
- 不对 thinking 文本执行占位符恢复，除非其中确实包含本请求 Vault 的完整
  占位符；完整 JSON事件的递归恢复不得改变签名。
- 不删除、不重排 content block。
- 未识别事件透明转发。

原因：签名内容按字节级不变原则处理，PrivacyTap 不得破坏 Anthropic 校验语义。

## 12. 安全归档

Provider 名称：

- `anthropic-messages`
- `anthropic-count-tokens`

归档保存：

- 脱敏请求；
- 上游脱敏 JSON或 SSE 事件；
- 模型；
- Token 用量；
- 检测数量；
- 处理耗时；
- HTTP 结果。

不得保存：

- 原始正文；
- Vault；
- `x-api-key`；
- `Authorization`；
- 恢复后响应。

## 13. 错误处理

| 情况 | 行为 |
|---|---|
| 非法 JSON或请求不是对象 | HTTP 400 |
| 请求体超过限制 | HTTP 413 |
| Prompt 包含当前 Anthropic Key | HTTP 422 |
| Anthropic 连接失败 | HTTP 502 |
| Anthropic 超时 | HTTP 504 |
| 上游 JSON非法 | HTTP 502 |
| 上游业务 4xx/5xx | 保留状态码和安全响应 |
| SSE 事件 JSON非法 | 停止转发未处理数据，安全结束客户端流 |
| Claude Code断开 | 取消上游读取并释放 Vault |
| Exporter 失败 | 记录警告，不影响模型链路 |

错误消息不得包含 URL Query、Header、正文或第三方异常原文。

## 14. CLI

目标命令：

```powershell
privacytap start `
  --provider anthropic `
  --upstream-base-url https://api.anthropic.com `
  --port 8080
```

Provider 默认上游：

- `openai` → `https://api.openai.com`
- `anthropic` → `https://api.anthropic.com`

若用户显式提供 `--upstream-base-url`，覆盖默认值。

启动提示列出实际启用端点。单个服务实例仍注册全部协议端点，但 Provider决定
默认上游和启动说明。

## 15. 测试

### 15.1 单元测试

- Anthropic Header过滤与转发。
- `text_delta` 每个占位符字符边界拆分。
- `input_json_delta` 每个占位符字符边界拆分。
- 多个 content block index 隔离。
- `content_block_stop` 刷新尾部。
- `message_stop` 刷新全部尾部。
- thinking/signature 结构保持。
- 未知事件透明转发。

### 15.2 集成测试

本地 Anthropic Mock覆盖：

- `/v1/messages` 非流式 JSON。
- `/v1/messages` SSE。
- `/v1/messages/count_tokens`。
- Header 转发。
- 当前 API Key阻断。
- 上游 4xx/5xx。
- 超时与连接失败。
- 非法 JSON与非法 SSE。
- Exporter 失败。

### 15.3 安全不变量

- 50 个并发 Claude 请求 Vault互不串线。
- 上游捕获数据中原始隐私出现次数为 0。
- 归档中原始隐私出现次数为 0。
- 归档中 API Key出现次数为 0。
- Claude 客户端收到的恢复结果正确率为 100%。

## 16. 验证

### 16.1 自动化

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

### 16.2 离线真实 Claude CLI 协议验证

启动 Mock Anthropic和 PrivacyTap，设置：

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
$env:ANTHROPIC_API_KEY="sk-ant-local-test-key"
claude --bare -p "Reply with exactly OK"
```

Claude CLI必须真实发起 `/v1/messages` 或相关 Anthropic请求。Mock 捕获内容只含
占位符，Claude CLI 能正常消费响应。

该验证使用真实安装的 Claude Code 二进制，但上游为可控 Mock。

### 16.3 真实 Anthropic云端验证

若环境存在有效 `ANTHROPIC_API_KEY`：

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
claude --bare -p "Reply with exactly OK"
```

再执行包含邮箱、手机号和文件工具调用的任务。

若无有效 Key，明确记录云端验证为外部阻塞，不伪造成功。离线 Claude CLI
协议验证、Mock 上游证据和自动化测试仍必须通过。

## 17. 文档交付

更新：

- `README.md`：同时提供 Codex 与 Claude Code配置和运行方式。
- `docs/experiment.md`：增加 Claude Messages 双证据实验。
- `.env.example`：增加 Anthropic 环境变量。

新增：

- `examples/mock_anthropic_upstream.py`
- Claude Code适配规格和实施计划。

## 18. 非目标

- Claude 订阅 OAuth或 Keychain 凭证转发。
- Bedrock、Vertex AI、Microsoft Foundry。
- DeepSeek Anthropic 协议保证。
- Anthropic Batch、Files、Admin、Models 等其他 API。
- WebSocket。
- 图片、音频和二进制隐私识别。

## 19. 完成定义

只有以下条件全部成立才视为完成：

1. `/v1/messages` JSON 与 SSE通过自动化测试。
2. `/v1/messages/count_tokens` 通过自动化测试。
3. 文本和工具参数流式恢复正确。
4. 当前 Anthropic Key泄露请求被阻断。
5. 上游与日志原始隐私和 API Key计数均为 0。
6. 现有 Codex 和 Chat Completions 测试无回归。
7. 总覆盖率不低于 90%。
8. Wheel 构建包含 Anthropic 模块和 Mock。
9. README 和实验文档包含可复制命令。
10. 本机 Claude Code 2.1.177 完成离线协议验证。
11. 有真实 Anthropic Key时完成云端验证；无 Key时明确记录外部阻塞。
