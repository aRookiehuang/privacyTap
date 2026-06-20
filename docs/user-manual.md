# PrivacyTap 完整使用手册

## 1. 项目用途

PrivacyTap 是运行在本机的 AI 隐私中间件，部署在 Codex、Claude Code 或普通
HTTP 客户端与云端模型 API 之间。

它解决的不是“日志里不要显示敏感信息”这一单点问题，而是：

> 在原始敏感信息离开本机之前进行可逆匿名化，同时保证流式响应和 Agent
> 工具调用仍然能够使用原始值。

例如客户端发送：

```text
把邮箱 test2026@example.com 和手机号 13800138000 写入 contact.txt
```

上游模型和安全归档看到：

```text
把邮箱 [EMAIL_1] 和手机号 [PHONE_1] 写入 contact.txt
```

模型返回的文本或工具参数经过 PrivacyTap 后，本地客户端重新得到原始邮箱和
手机号。

## 2. 工作原理

```mermaid
flowchart LR
    A["Codex / Claude Code / HTTP 客户端"] --> B["PrivacyTap 本地网关"]
    B --> C["检测敏感实体"]
    C --> D["请求级内存 Vault"]
    D --> E["使用占位符替换"]
    E --> F["OpenAI / Anthropic / 兼容上游"]
    F --> G["脱敏 JSON 或 SSE"]
    G --> H["安全归档 / 可选 Langfuse"]
    G --> I["本地增量恢复"]
    I --> A
```

支持的主要接口：

| 本地接口 | 用途 | 返回形式 |
|---|---|---|
| `POST /v1/responses` | OpenAI Responses、Codex | JSON、SSE |
| `POST /v1/messages` | Anthropic Messages、Claude Code | JSON、SSE |
| `POST /v1/messages/count_tokens` | Claude Code Token 计数 | JSON |
| `POST /v1/chat/completions` | 兼容客户端和基础演示 | 非流式 JSON |

支持手机号、中国居民身份证号、邮箱、银行卡号、带上下文的学号和代码凭证。
当前 HTTP 请求正在使用的真实认证 Key 如果出现在 Prompt 中，将返回
HTTP 422，避免把可用密钥发送给模型。

## 3. 环境要求

- Windows 10/11；
- Python 3.10 及以上；
- Git；
- 使用真实模型时准备 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY`；
- 使用 Codex 或 Claude Code 时，需预先安装对应 CLI。

检查环境：

```powershell
python --version
git --version
codex --version
claude --version
```

Codex 与 Claude Code 只需安装实际要演示的一个。

## 4. 安装

```powershell
git clone https://github.com/aRookiehuang/privacyTap.git
Set-Location privacyTap

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

确认安装：

```powershell
.\.venv\Scripts\privacytap.exe --help
.\.venv\Scripts\python.exe -m pytest -q
```

## 5. 最推荐的无 Key 离线演示

离线演示不调用云模型，但使用真实 PrivacyTap 网络链路。Mock 上游会直接打印
它实际收到的请求，因此能作为“原始敏感值没有离开代理”的直接证据。

### 5.1 OpenAI Responses 流式演示

打开三个 PowerShell 终端，均进入项目目录。

**终端 1：启动可控上游**

```powershell
.\.venv\Scripts\python.exe examples\mock_responses_upstream.py
```

**终端 2：启动 PrivacyTap**

```powershell
.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url http://127.0.0.1:18080 `
  --archive-dir .\privacytap-traces
```

**终端 3：发送 SSE 请求**

```powershell
$body = @{
  model = "mock-model"
  stream = $true
  input = "联系 test2026@example.com，电话 13800138000"
} | ConvertTo-Json

curl.exe -N http://127.0.0.1:8080/v1/responses `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer sk-local-demo-key" `
  -d $body
```

检查三类结果：

1. Mock 上游只出现 `[EMAIL_1]` 和 `[PHONE_1]`；
2. 终端 3 的 SSE 恢复为真实邮箱和手机号；
3. `privacytap-traces` 中没有原始敏感值和认证 Key。

### 5.2 真实 Claude Code 二进制 + Mock 上游

**终端 1：**

```powershell
.\.venv\Scripts\python.exe examples\mock_anthropic_upstream.py
```

**终端 2：**

```powershell
.\.venv\Scripts\privacytap.exe start `
  --provider anthropic `
  --upstream-base-url http://127.0.0.1:18082 `
  --archive-dir .\privacytap-traces
```

**终端 3：**

```powershell
$settings = @{
  env = @{
    ANTHROPIC_BASE_URL = "http://127.0.0.1:8080"
    ANTHROPIC_API_KEY = "sk-ant-local-test-key-123456"
  }
} | ConvertTo-Json -Depth 3

$settings | Set-Content .\claude-privacytap-settings.json

claude --bare --settings .\claude-privacytap-settings.json `
  -p --no-session-persistence "Reply with exactly OK"

Remove-Item .\claude-privacytap-settings.json
```

这里运行的是实际安装的 Claude Code CLI，而不是自写客户端；模型上游使用
Mock，便于直接检查 `/v1/messages` 和 `/v1/messages/count_tokens`。

## 6. 使用 OpenAI API Key 接入 Codex

### 6.1 配置 Codex Provider

编辑用户级配置：

```text
$HOME\.codex\config.toml
```

加入：

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

Provider 必须放在用户级配置中，不能只写在项目级 `.codex/config.toml`。
模型名可按账号实际可用模型调整。

### 6.2 启动网关

```powershell
$env:OPENAI_API_KEY="sk-你的真实Key"

.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url https://api.openai.com `
  --archive-dir .\privacytap-traces
```

API Key 只通过 `Authorization` Header 转发，不写入安全归档和 Langfuse。
网关默认只监听 `127.0.0.1:8080`。

### 6.3 启动 Codex

```powershell
codex --profile privacytap
```

推荐测试任务：

```text
请记住邮箱 test2026@example.com 和手机号 13800138000。
在当前目录创建 contact.txt，写入上述信息，然后读取并报告文件内容。
```

预期：

- Codex 可以完成文件工具调用；
- `contact.txt` 和 Codex 界面显示原始值；
- 上游侧可控实验和本地归档只显示占位符；
- 归档中不存在 `OPENAI_API_KEY`。

## 7. 使用 Anthropic API Key 接入 Claude Code

### 7.1 启动网关

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-你的真实Key"

.\.venv\Scripts\privacytap.exe start `
  --provider anthropic `
  --upstream-base-url https://api.anthropic.com `
  --archive-dir .\privacytap-traces
```

### 7.2 配置并运行 Claude Code

新开终端：

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
$env:ANTHROPIC_API_KEY="sk-ant-你的真实Key"

claude --bare -p "Reply with exactly OK"
```

进入交互模式：

```powershell
claude
```

如果用户级或管理设置覆盖环境变量，使用不提交到 Git 的临时设置文件：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8080",
    "ANTHROPIC_API_KEY": "sk-ant-你的真实Key"
  }
}
```

```powershell
claude --bare --settings .\claude-privacytap-settings.json `
  -p --no-session-persistence "Reply with exactly OK"
```

验证后立即删除设置文件。

## 8. DeepSeek API 的使用边界

DeepSeek 官方 API 提供 OpenAI/Anthropic 兼容格式，但 PrivacyTap 当前对
DeepSeek 最稳妥的接入方式是非流式 `Chat Completions`，不应把它写成已经
支持 Codex 所需的 OpenAI Responses 协议。

```powershell
$env:DEEPSEEK_API_KEY="你的DeepSeek Key"

.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url https://api.deepseek.com `
  --archive-dir .\privacytap-traces
```

然后向本地 `POST /v1/chat/completions` 发送请求，并在
`Authorization: Bearer <DEEPSEEK_API_KEY>` 中携带 Key。模型名应以运行时
DeepSeek 账号实际提供的模型为准。

注意：

- 此路径适合普通聊天 Demo；
- 当前 PrivacyTap 的该接口为非流式；
- 不等于 Codex Responses 或 Claude Code Messages 已通过 DeepSeek 验证；
- 课程主实验建议使用 Mock 上游证明安全性，用真实 Codex/Claude Code证明
  客户端兼容性。

DeepSeek 官方说明：[API Quick Start](https://api-docs.deepseek.com/)。

## 9. Langfuse 可选接入

安装扩展：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[langfuse]"
```

设置环境变量：

```powershell
$env:LANGFUSE_PUBLIC_KEY="pk-lf-..."
$env:LANGFUSE_SECRET_KEY="sk-lf-..."
$env:LANGFUSE_BASE_URL="http://127.0.0.1:3000"
```

启动：

```powershell
.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --exporter langfuse `
  --archive-dir .\privacytap-traces
```

Langfuse 只接收脱敏安全事件，不参与原始值恢复。Langfuse 初始化或导出失败
时，PrivacyTap 回退到本地安全归档，不应中断模型调用。

## 10. 启动参数

```powershell
.\.venv\Scripts\privacytap.exe start --help
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--port` | `8080` | 本地监听端口 |
| `--provider` | `openai` | `openai` 或 `anthropic` |
| `--upstream-base-url` | Provider 官方地址 | 上游根地址，不带接口路径 |
| `--upstream-timeout` | `300` 秒 | 上游超时 |
| `--archive-dir` | `./privacytap-traces` | 安全归档目录 |
| `--exporter` | `file` | `file` 或 `langfuse` |

也可使用：

```powershell
$env:PRIVACYTAP_UPSTREAM_BASE_URL="http://127.0.0.1:18080"
$env:PRIVACYTAP_UPSTREAM_TIMEOUT="300"
```

停止服务：在运行 PrivacyTap 的终端按 `Ctrl+C`。

## 11. 如何检查证据

### 11.1 上游证据

Mock 终端打印的是 PrivacyTap 实际发出的 HTTP 请求。搜索原始邮箱、手机号或
Key，结果应为 0；搜索 `[EMAIL_1]`、`[PHONE_1]` 应能命中。

### 11.2 本地归档

```powershell
Get-ChildItem .\privacytap-traces -Recurse -File

Get-ChildItem .\privacytap-traces -Recurse -File |
  Select-String -SimpleMatch "test2026@example.com"

Get-ChildItem .\privacytap-traces -Recurse -File |
  Select-String -SimpleMatch "[EMAIL_1]"
```

第一条敏感值搜索应无结果，第二条占位符搜索应有结果。

### 11.3 客户端恢复

客户端最终文本、文件内容或工具参数应包含原始值。只有“客户端显示原值”不能
证明安全，因为它无法说明上游收到的内容；必须和上游证据组合使用。

## 12. 测试和量化

```powershell
.\.venv\Scripts\python.exe -m pytest -q

.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q

.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

完整实验方法见
[课程实验计划](course-experiment-plan.md)。

## 13. 常见故障

### 端口 8080 被占用

```powershell
Get-NetTCPConnection -LocalPort 8080
```

换端口启动，并同步修改 Codex 的 `base_url` 或 Claude Code 的
`ANTHROPIC_BASE_URL`：

```powershell
.\.venv\Scripts\privacytap.exe start --port 8081
```

### 返回 401 或 403

- 确认 API Key 在启动客户端和网关所需的终端中存在；
- OpenAI 使用 `OPENAI_API_KEY`；
- Claude Code 使用 `ANTHROPIC_API_KEY`；
- 不要把引号、空格或示例前缀复制到真实 Key 中。

### 返回 422

检查 Prompt 是否包含本次请求实际使用的 API Key。该行为是主动安全阻断，
不是模型错误。代码文档中的示例凭证通常会匿名化，但当前认证 Key 会被阻断。

### Codex 没有经过 PrivacyTap

- 确认使用 `codex --profile privacytap`；
- 确认 Provider 位于用户级 `$HOME\.codex\config.toml`；
- 确认 `wire_api = "responses"`；
- 观察 PrivacyTap 终端是否出现请求。

### Claude Code 仍直连官方服务

- 使用 `claude --bare` 排除订阅 OAuth；
- 检查 `ANTHROPIC_BASE_URL`；
- 若设置被覆盖，使用显式 `--settings` 临时文件；
- 临时文件不得提交到 Git。

### Langfuse 不可用

先使用默认 `--exporter file` 完成主实验。Langfuse 是可选观测输出，不应成为
隐私保护链路的单点故障。

## 14. 五分钟课堂演示

1. 用一张架构图说明 PrivacyTap 位于 AI 客户端与模型 API 之间；
2. 展示包含邮箱和手机号的原始 Prompt；
3. 启动 Mock 上游与 PrivacyTap；
4. 执行真实 Claude Code CLI 或 Responses SSE 请求；
5. 展示 Mock 上游只有占位符；
6. 展示客户端仍得到原始值；
7. 搜索 `privacytap-traces`，证明日志中原始值命中数为 0；
8. 展示测试、F1、泄露率、恢复率和 P95 指标；
9. 总结：日志脱敏只能保护记录端，PrivacyTap 保护请求出站、观测和恢复全链路。

## 15. 安全边界

PrivacyTap 不防御：

- 已被恶意软件控制的本机；
- 进程内存转储；
- 用户绕过代理直接调用模型；
- 图片、音频、压缩包和二进制附件中的隐私；
- 当前规则未覆盖的姓名、自然语言地址等实体；
- 上游模型自行生成的新敏感信息。

它是课程实验和工程原型，不是法律合规认证产品。

