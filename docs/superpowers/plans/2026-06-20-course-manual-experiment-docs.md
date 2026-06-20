# PrivacyTap Course Manual and Experiment Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成可直接用于安装演示、课程实验、报告撰写和答辩的 PrivacyTap 完整文档，并消除旧文档与当前实现之间的冲突。

**Architecture:** 使用“使用手册”和“课程实验计划”分离受众；README 作为入口，项目档案与威胁模型提供一致的背景和边界。通过文档契约测试检查文件存在、关键命令、课程价值、证据标准和过时表述。

**Tech Stack:** Markdown、Mermaid、PowerShell、pytest

---

### Task 1: 建立文档契约

**Files:**
- Create: `tests/test_course_docs_contract.py`

- [ ] **Step 1: 编写失败测试**

测试必须验证：

```python
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_course_documents_exist_and_are_linked():
    readme = read("README.md")
    assert Path("docs/user-manual.md").exists()
    assert Path("docs/course-experiment-plan.md").exists()
    assert "docs/user-manual.md" in readme
    assert "docs/course-experiment-plan.md" in readme


def test_manual_contains_runnable_clients_and_offline_demo():
    manual = read("docs/user-manual.md")
    for text in (
        "privacytap.exe start",
        "codex --profile privacytap",
        "claude --bare",
        "mock_responses_upstream.py",
        "mock_anthropic_upstream.py",
        "privacytap-traces",
    ):
        assert text in manual


def test_experiment_plan_defines_value_metrics_and_evidence():
    plan = read("docs/course-experiment-plan.md")
    for text in (
        "日志脱敏",
        "可逆匿名化",
        "Precision",
        "Recall",
        "F1",
        "P95",
        "证据充分",
        "可信度",
        "对照组",
        "课程要求",
    ):
        assert text in plan


def test_current_docs_do_not_claim_streaming_is_unsupported():
    combined = read("docs/project-brief.md") + read("docs/threat-model.md")
    assert "首版支持非流式" not in combined
    assert "首版不支持流式返回" not in combined
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_course_docs_contract.py -q
```

Expected: FAIL，因为两份核心文档尚不存在或 README 尚未链接。

### Task 2: 编写核心课程文档

**Files:**
- Create: `docs/user-manual.md`
- Create: `docs/course-experiment-plan.md`

- [ ] **Step 1: 编写使用手册**

必须包含安装、离线 Mock、OpenAI/Codex、Anthropic/Claude Code、Langfuse、证据查看、故障排查、安全边界和五分钟演示。

- [ ] **Step 2: 编写完整实验计划**

必须包含问题、价值、课程符合性、实验假设、对照组、指标公式、证据等级、通过阈值、实验步骤、结果表、报告目录和答辩流程。

- [ ] **Step 3: 运行文档契约测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_course_docs_contract.py -q
```

Expected: README 链接与旧表述相关测试仍可能失败，核心文档内容测试通过。

### Task 3: 同步旧文档和入口并全面验证

**Files:**
- Modify: `README.md`
- Modify: `docs/project-brief.md`
- Modify: `docs/experiment.md`
- Modify: `docs/threat-model.md`

- [ ] **Step 1: 更新当前能力和文档入口**

README 增加两份核心文档链接；项目档案与威胁模型改为当前 OpenAI/Anthropic、SSE 和工具调用能力；精简实验文档指向完整计划。

- [ ] **Step 2: 运行文档契约测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_course_docs_contract.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行完整测试与覆盖率**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=privacytap --cov-report=term-missing --cov-fail-under=90 -q
```

Expected: 全部测试通过，覆盖率不低于 90%。

- [ ] **Step 4: 运行隐私数据集评测与文档检查**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_privacy.py
rg -n "TODO|TBD|首版支持非流式|首版不支持流式" docs README.md
git diff --check
```

Expected: Precision、Recall、F1 输出真实结果；核心课程文档无占位符和过时表述；`git diff --check` 无输出。
