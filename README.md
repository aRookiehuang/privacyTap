# PrivacyTap

PrivacyTap 是一个运行在本机的 LLM 隐私中间件，用于解决：

> Prompt 中的敏感信息在进入第三方模型之前无法只靠日志脱敏得到保护，而普通
> 字符串替换又会破坏 Codex 的流式响应和工具调用参数。

PrivacyTap 在请求离开本机前匿名化手机号、身份证号、邮箱、银行卡号、学号和
代码中的凭证；模型响应中的占位符在本机恢复。OpenAI 和安全日志只看到脱敏
内容，Codex 仍能使用真实的文件路径、命令参数和输出文本。

## 核心链路

```mermaid
flowchart LR
    A["Codex CLI"] -->|"Responses API + SSE"| B["PrivacyTap"]
    B --> C["请求脱敏"]
    C --> D["请求级内存 Vault"]
    D --> E["OpenAI Responses API"]
    E --> F["脱敏 SSE / JSON"]
    F --> G["安全日志"]
    F --> H["本地流式恢复"]
    H --> A
```

## 支持的数据

| 类型 | 处理策略 |
|---|---|
| 中国大陆手机号 | `[PHONE_n]` 可逆替换 |
| 中国居民身份证 | 校验位通过后 `[CN_ID_n]` |
| 邮箱 | `[EMAIL_n]` 可逆替换 |
| 银行卡 | Luhn 通过后 `[BANK_CARD_n]` |
| 学号 | 具有“学号/Student ID”上下文时替换 |
| 代码中的 API Key / Bearer Token | `[CREDENTIAL_n]` 可逆替换 |
| 当前请求使用的真实 API Key出现在 Prompt | HTTP 422 阻断 |

支持：

- `POST /v1/responses`：JSON 与 SSE，供真实 Codex 使用；
- `POST /v1/chat/completions`：保留原有非流式 Demo。

## 安装

```powershell
git clone https://github.com/aRookiehuang/privacyTap.git
Set-Location privacyTap
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 真实 Codex 接入

### 1. 配置 Codex Provider

把以下内容合并到用户级 `$HOME\.codex\config.toml`：

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

Provider 配置必须放在用户级配置中。Codex 会忽略项目级
`.codex/config.toml` 中的 `model_provider` 和 `model_providers`。

### 2. 启动 PrivacyTap

```powershell
$env:OPENAI_API_KEY="sk-..."

.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url https://api.openai.com `
  --archive-dir .\privacytap-traces
```

API Key只通过 `Authorization` Header 转发给 OpenAI，不会写入本地归档或
Langfuse。PrivacyTap只监听 `127.0.0.1`。

### 3. 启动 Codex

```powershell
codex --profile privacytap
```

建议验证任务：

```text
请记住邮箱 test2026@example.com 和手机号 13800138000。
在临时目录创建 contact.txt，写入上述信息，然后读取并报告内容。
```

预期结果：

1. Codex 正常完成文件工具调用；
2. 文件和 Codex 界面显示原始邮箱、手机号；
3. `privacytap-traces` 中只出现 `[EMAIL_1]`、`[PHONE_1]`；
4. 归档中不出现 `OPENAI_API_KEY`。

## 无 Key 离线 Responses 演示

### Terminal 1：Mock Responses 上游

```powershell
.\.venv\Scripts\python.exe examples\mock_responses_upstream.py
```

### Terminal 2：PrivacyTap

```powershell
.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url http://127.0.0.1:18080
```

可向 `http://127.0.0.1:8080/v1/responses` 发送 `stream=true` 请求。Mock
终端打印实际收到的脱敏请求，客户端收到恢复后的 SSE。

## 原 Chat Completions Demo

```powershell
# Terminal 1
.\.venv\Scripts\python.exe examples\mock_upstream.py

# Terminal 2
.\.venv\Scripts\privacytap.exe start `
  --upstream-base-url http://127.0.0.1:18080

# Terminal 3
.\.venv\Scripts\python.exe examples\demo_client.py
```

## 可选 Langfuse 输出

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[langfuse]"

$env:LANGFUSE_PUBLIC_KEY="pk-lf-..."
$env:LANGFUSE_SECRET_KEY="sk-lf-..."
$env:LANGFUSE_BASE_URL="http://127.0.0.1:3000"

.\.venv\Scripts\privacytap.exe start --exporter langfuse
```

Langfuse 只是脱敏事件输出适配器，不属于关键请求链路；不可用时自动回退到
本地安全归档。

## 测试与量化

```powershell
.\.venv\Scripts\python.exe -m pytest -q

.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q

.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

目标指标：

- 可控上游原始敏感信息泄露数：`0`
- 安全日志原始敏感信息泄露数：`0`
- SSE 分片恢复正确率：`100%`
- API Key泄露数：`0`
- 新增代码测试覆盖率：不低于 `90%`
- 隐私变换 P95：小于 `20 ms`

## 项目边界

- 首期真实接入只保证 OpenAI Responses API。
- DeepSeek 当前不作为 Codex Responses 的直接上游；后续可增加协议 Adapter。
- 不支持 WebSocket Responses。
- 不处理姓名、自然语言地址、图片、音频或二进制文件中的隐私。
- 不防御已被攻陷的本机、进程内存转储或绕过代理的直接调用。
- 本项目不是法律合规认证产品。

## 相关工作

项目设计参考但不依赖：

- [TokenTap](https://github.com/jmuncor/tokentap) 的本地代理拦截思路；
- [Langfuse](https://github.com/langfuse/langfuse) 的 LLM 可观测性思路；
- [Microsoft Presidio](https://github.com/microsoft/presidio) 的 PII 检测设计；
- [LLM Guard](https://github.com/protectai/llm-guard) 的输入匿名化设计。

## 文档

- [课程项目档案](docs/project-brief.md)
- [实验设计](docs/experiment.md)
- [威胁模型](docs/threat-model.md)
- [Codex 接入设计](docs/superpowers/specs/2026-06-20-codex-responses-integration-design.md)
