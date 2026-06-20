# PrivacyTap Claude One-Click Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PowerShell launcher that needs only upstream URL, API key, model name, and archive path before starting PrivacyTap and Claude Code.

**Architecture:** A repository-local env file stores four user values. A single PowerShell entrypoint validates configuration, starts PrivacyTap as a hidden child process, waits for port 8080, launches Claude with user settings excluded, and cleans up its child process on exit.

**Tech Stack:** PowerShell 7/Windows PowerShell, PrivacyTap CLI, Claude Code CLI, pytest contract tests.

---

### Task 1: Define launcher contract

**Files:**
- Create: `tests/test_claude_launcher_contract.py`

- [ ] Assert the example configuration contains exactly the four public settings.
- [ ] Assert the launcher validates configuration without printing the API key.
- [ ] Assert the launcher starts PrivacyTap with Anthropic provider and the configured archive path.
- [ ] Assert Claude is launched with `--setting-sources project,local`.
- [ ] Run the test and verify it fails because the launcher files do not exist.

### Task 2: Implement launcher

**Files:**
- Create: `privacytap.claude.env.example`
- Create: `scripts/start_claude_with_privacytap.ps1`
- Modify: `.gitignore`

- [ ] Add the four-line example configuration.
- [ ] Implement repository-root discovery and env parsing.
- [ ] Implement executable, URL, output directory, and port validation.
- [ ] Start PrivacyTap hidden with redirected logs.
- [ ] Wait for port 8080 before launching Claude.
- [ ] Launch Claude with the configured model and excluded user settings.
- [ ] Stop only the child proxy in `finally`.
- [ ] Print the newest safe trace path.
- [ ] Run the contract test and verify it passes.

### Task 3: Document and verify

**Files:**
- Modify: `README.md`

- [ ] Add three-step usage instructions.
- [ ] Run PowerShell parser validation.
- [ ] Run the launcher contract test.
- [ ] Run the complete pytest suite.
- [ ] Run `git diff --check`.
