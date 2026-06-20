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


def test_start_help_exposes_openai_provider_and_timeout():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--upstream-timeout" in result.output
    assert "openai" in result.output


def test_start_help_lists_anthropic_provider():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "openai|anthropic" in result.output


def test_openai_upstream_has_a_safe_default():
    from privacytap.cli import DEFAULT_OPENAI_BASE_URL

    assert DEFAULT_OPENAI_BASE_URL == "https://api.openai.com"


def test_default_upstream_depends_on_provider():
    from privacytap.cli import default_upstream_base_url

    assert default_upstream_base_url("openai") == (
        "https://api.openai.com"
    )
    assert default_upstream_base_url("anthropic") == (
        "https://api.anthropic.com"
    )


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
