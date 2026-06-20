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
    combined = read("docs/project-brief.md") + read(
        "docs/threat-model.md"
    )
    assert "首版支持非流式" not in combined
    assert "首版不支持流式返回" not in combined
