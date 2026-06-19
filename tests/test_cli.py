from click.testing import CliRunner

from privacytap.cli import main


def test_root_help_only_lists_start_command():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    for legacy in ("claude", "gemini", "codex", "privacy-start"):
        assert legacy not in result.output


def test_start_help_exposes_standalone_options():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "--upstream-base-url" in result.output
    assert "--archive-dir" in result.output
    assert "--exporter" in result.output


def test_langfuse_selection_falls_back_to_file(
    monkeypatch, tmp_path
):
    from privacytap import cli

    messages = []
    monkeypatch.setattr(
        cli.click, "echo", lambda message: messages.append(str(message))
    )
    exporter = cli.build_exporter(
        "langfuse",
        tmp_path,
        langfuse_factory=lambda: (_ for _ in ()).throw(
            RuntimeError("unavailable")
        ),
    )
    exporter.export(
        {
            "timestamp": "2026-06-19T00:00:00",
            "provider": "openai-compatible",
            "model": "demo",
            "tokens": 0,
            "request": {},
            "response": {},
            "privacy": {"detected": {}, "processing_ms": 0},
        }
    )
    assert any("Langfuse unavailable" in message for message in messages)
    assert len(list(tmp_path.glob("*.json"))) == 1
