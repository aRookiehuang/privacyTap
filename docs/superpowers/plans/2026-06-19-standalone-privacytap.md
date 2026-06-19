# Standalone PrivacyTap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 TokenTap fork 重构为完全独立的 `privacytap` Python 包和 CLI，同时保留已验证的全链路可逆匿名化能力。

**Architecture:** 核心包只包含检测、请求级 Vault、JSON 转换、OpenAI-compatible 代理、安全归档和通用 exporter 协议。Langfuse 放在 `integrations/` 作为可选示例；TokenTap 原有 Dashboard、Provider 路由和工具启动命令全部删除。

**Tech Stack:** Python 3.10+、aiohttp、Click、pytest、pytest-asyncio、pytest-cov；Langfuse 仅为可选 extra。

---

## 最终文件边界

```text
privacytap/
├─ __init__.py
├─ cli.py
├─ proxy.py
├─ archive.py
├─ exporters.py
└─ privacy/
   ├─ __init__.py
   ├─ models.py
   ├─ validators.py
   ├─ detectors.py
   ├─ vault.py
   └─ transformer.py
integrations/
└─ langfuse_exporter.py
```

### Task 1: 用测试固定独立项目契约

**Files:**
- Create: `tests/test_standalone_contract.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
import importlib.util
from pathlib import Path

from click.testing import CliRunner

from privacytap.cli import main


def test_privacytap_package_exists_and_tokentap_package_is_removed():
    assert importlib.util.find_spec("privacytap") is not None
    assert importlib.util.find_spec("tokentap") is None


def test_cli_contains_only_start_command():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    for legacy in ("claude", "gemini", "codex", "privacy-start"):
        assert legacy not in result.output


def test_repository_has_no_tokentap_source_tree():
    assert not Path("tokentap").exists()
```

- [ ] **Step 2: 运行并确认因 `privacytap` 不存在而失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_standalone_contract.py -q
```

- [ ] **Step 3: 暂不实现，进入迁移任务**

### Task 2: 迁移隐私核心

**Files:**
- Create: `privacytap/__init__.py`
- Create: `privacytap/privacy/*.py`
- Modify: `tests/test_detectors.py`
- Modify: `tests/test_transformer.py`
- Modify: `tests/test_validators.py`
- Modify: `tests/test_vault.py`
- Modify: `scripts/evaluate_privacy.py`

- [ ] **Step 1: 将所有测试和评测导入从 `tokentap.privacy` 改为 `privacytap.privacy`**

```powershell
Get-ChildItem tests,scripts -Recurse -File |
  ForEach-Object {
    (Get-Content -Raw $_.FullName).Replace(
      'tokentap.privacy',
      'privacytap.privacy'
    ) | Set-Content -Encoding utf8 $_.FullName
  }
```

- [ ] **Step 2: 复制自主实现的六个隐私模块到新包并修改内部导入**

目标模块：

```text
models.py
validators.py
detectors.py
vault.py
transformer.py
__init__.py
```

所有内部导入必须以 `privacytap.privacy` 开头。

- [ ] **Step 3: 运行核心测试**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_detectors.py `
  tests\test_transformer.py `
  tests\test_validators.py `
  tests\test_vault.py -q
```

Expected: 全部通过。

### Task 3: 建立独立 exporter 与安全归档

**Files:**
- Create: `privacytap/exporters.py`
- Create: `privacytap/archive.py`
- Create: `integrations/__init__.py`
- Create: `integrations/langfuse_exporter.py`
- Modify: `tests/test_safe_archive.py`
- Modify: `tests/test_langfuse_exporter.py`

- [ ] **Step 1: 将归档测试导入改为 `privacytap.archive`**

- [ ] **Step 2: 定义通用协议**

```python
from typing import Protocol


class SafeEventExporter(Protocol):
    def export(self, event: dict) -> None: ...


class CompositeExporter:
    def __init__(self, exporters: list[SafeEventExporter]) -> None:
        self.exporters = exporters

    def export(self, event: dict) -> None:
        for exporter in self.exporters:
            try:
                exporter.export(event)
            except Exception:
                continue
```

- [ ] **Step 3: 将本地归档实现为 `FileExporter`**

```python
class FileExporter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def export(self, event: dict) -> None:
        save_safe_event(event, self.output_dir)
```

- [ ] **Step 4: 将 Langfuse 实现迁入 `integrations/langfuse_exporter.py`**

该模块只能导入 `langfuse` 和标准库，不得被核心包自动导入。

- [ ] **Step 5: 运行 exporter 与归档测试**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_safe_archive.py `
  tests\test_langfuse_exporter.py -q
```

### Task 4: 迁移独立代理

**Files:**
- Create: `privacytap/proxy.py`
- Modify: `tests/test_privacy_proxy.py`
- Modify: `tests/test_privacy_invariants.py`
- Delete: `tests/test_proxy.py`
- Delete: `tests/test_integration.py`

- [ ] **Step 1: 将代理测试导入改为 `privacytap.proxy`**

- [ ] **Step 2: 从现有隐私代理迁移 `PrivacyProxyServer`**

必须移除对 TokenTap parser 的依赖。Token 数量按以下优先级记录：

```python
usage = safe_response.get("usage") or {}
tokens = int(usage.get("total_tokens") or 0)
```

- [ ] **Step 3: 运行代理及安全不变量测试**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_privacy_proxy.py `
  tests\test_privacy_invariants.py -q
```

### Task 5: 重写独立 CLI

**Files:**
- Create: `privacytap/cli.py`
- Replace: `tests/test_cli.py`
- Delete: `tests/test_config.py`
- Delete: `tests/test_privacy_cli.py`

- [ ] **Step 1: 测试 CLI 仅暴露 `start`**

```python
from click.testing import CliRunner
from privacytap.cli import main


def test_start_help():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "--upstream-base-url" in result.output
    assert "--archive-dir" in result.output
    assert "--exporter" in result.output
```

- [ ] **Step 2: 实现命令**

```text
privacytap start --port 8080 --upstream-base-url URL
                 --archive-dir PATH
                 --exporter file|langfuse
```

默认 exporter 为 `file`。选择 `langfuse` 时动态导入 `integrations.langfuse_exporter`；导入或运行失败不得影响代理响应。

- [ ] **Step 3: 运行 CLI 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_cli.py `
  tests\test_standalone_contract.py -q
```

### Task 6: 删除 TokenTap 遗留并更新构建元数据

**Files:**
- Delete: `tokentap/`
- Modify: `pyproject.toml`
- Modify: `MANIFEST.in`
- Delete: `.github/workflows/publish.yml`

- [ ] **Step 1: 删除 `tokentap` 目录和旧项目测试**

- [ ] **Step 2: 设置项目元数据**

```toml
[project]
name = "privacytap"
version = "0.1.0"
description = "Full-chain reversible anonymization proxy for OpenAI-compatible LLM calls"

[project.scripts]
privacytap = "privacytap.cli:main"
```

核心依赖仅保留：

```toml
"aiohttp>=3.9.0,<4"
"click>=8.0.0,<9"
```

- [ ] **Step 3: 检查源代码中的旧命名**

```powershell
Get-ChildItem privacytap,tests,examples,scripts -Recurse -File |
  Select-String -Pattern 'tokentap|TokenTap'
```

Expected: 无匹配。

### Task 7: 更新示例和课程文档

**Files:**
- Modify: `examples/demo_client.py`
- Modify: `README.md`
- Modify: `docs/project-brief.md`
- Modify: `docs/experiment.md`
- Modify: `docs/threat-model.md`

- [ ] **Step 1: 示例默认 URL 改为 `PRIVACYTAP_PROXY_URL`，命令改为 `privacytap start`**

- [ ] **Step 2: README 将 TokenTap/Langfuse 只放在“相关工作”**

正文不得使用“基于 TokenTap”“TokenTap 增强”“Langfuse 增强”等表述。

- [ ] **Step 3: 课程文档统一为独立项目叙事**

答辩核心表述：

```text
PrivacyTap 借鉴本地代理和 LLM 可观测系统的设计思路，
独立实现敏感信息检测、可逆匿名化、凭证阻断和安全观测。
```

### Task 8: 完整验收与推送

**Files:**
- Verify only

- [ ] **Step 1: 安装独立包并运行测试**

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,langfuse]"
.\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 2: 覆盖率和评测**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
```

- [ ] **Step 3: 构建并检查 wheel**

```powershell
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m zipfile -l dist\privacytap-0.1.0-py3-none-any.whl
```

Expected:

- 包含 `privacytap/`；
- 不包含 `tokentap/`；
- entry point 为 `privacytap`。

- [ ] **Step 4: 离线三端演示**

使用 Mock 上游验证匿名化、恢复、422 阻断和日志零泄露。

- [ ] **Step 5: 提交并推送**

```powershell
git push privacytap HEAD:main
```

核对 `git rev-parse HEAD` 与 `git ls-remote ... refs/heads/main` 一致。
