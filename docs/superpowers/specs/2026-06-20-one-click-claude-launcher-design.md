# PrivacyTap Claude 一键启动器设计

## 目标

用户只需要在配置文件填写四项内容：

1. 中转站 Base URL；
2. API Key；
3. 中转站支持的 Claude 模型名；
4. 安全审计输出目录。

之后运行一个 PowerShell 脚本，即可自动启动 PrivacyTap 并进入真实 Claude Code。

## 文件

- `privacytap.claude.env.example`：不包含真实密钥的四项配置模板。
- `privacytap.claude.env`：用户本地配置，必须被 Git 忽略。
- `scripts/start_claude_with_privacytap.ps1`：一键启动器。
- `tests/test_claude_launcher_contract.py`：启动器静态契约测试。

## 启动流程

1. 以仓库根目录为基准读取 `privacytap.claude.env`。
2. 严格验证四项配置均非空，Base URL 为 HTTP/HTTPS 地址。
3. 检查 `privacytap.exe` 和 `claude` 是否可用。
4. 固定使用本机 `127.0.0.1:8080` 作为 Claude 到 PrivacyTap 的入口。
5. 后台隐藏启动 PrivacyTap，输出安全归档到用户配置的目录。
6. 等待 8080 端口可连接；超时则显示代理日志并退出。
7. 在当前终端设置 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY`。
8. 使用 `--setting-sources project,local` 启动 Claude，防止用户级
   `C:\Users\<用户>\.claude\settings.json` 覆盖本地代理地址。
9. Claude 退出后，只停止本次脚本创建的 PrivacyTap 进程。
10. 输出最新的 Markdown 审计文件路径。

## 错误处理

- 缺少配置文件时，从模板创建本地配置并提示用户填写。
- 配置缺失或仍为示例值时，拒绝启动且不打印 API Key。
- 8080 被其他进程占用时拒绝启动，避免误连未知服务。
- PrivacyTap 启动失败时显示标准错误日志路径。
- 模型不可用时由上游返回 `model_not_found`，用户只需修改模型配置。

## 安全边界

- 脚本不输出 API Key。
- 本地配置文件加入 `.gitignore`。
- PrivacyTap 归档仍只保存脱敏请求和脱敏上游响应。
- 脚本不修改用户全局 Claude 配置。
