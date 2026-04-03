"""Unit tests for tokentap CLI — MiniMax _run_tool and run command."""

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tokentap.cli import main, _run_tool
from tokentap.config import DEFAULT_PROXY_PORT, PROVIDERS


class TestRunTool:
    """Tests for _run_tool with MiniMax provider."""

    @patch("tokentap.cli.subprocess.run")
    def test_minimax_sets_openai_base_url_with_prefix(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit, match="0"):
            _run_tool("minimax", "python", DEFAULT_PROXY_PORT, ("app.py",))
        call_env = mock_run.call_args[1]["env"]
        expected = f"http://127.0.0.1:{DEFAULT_PROXY_PORT}/minimax/v1"
        assert call_env["OPENAI_BASE_URL"] == expected

    @patch("tokentap.cli.subprocess.run")
    def test_minimax_runs_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit, match="0"):
            _run_tool("minimax", "python", 9999, ("my_app.py",))
        cmd = mock_run.call_args[0][0]
        assert cmd == ["python", "my_app.py"]

    @patch("tokentap.cli.subprocess.run")
    def test_anthropic_no_proxy_path(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit, match="0"):
            _run_tool("anthropic", "claude", DEFAULT_PROXY_PORT, ())
        call_env = mock_run.call_args[1]["env"]
        expected = f"http://127.0.0.1:{DEFAULT_PROXY_PORT}"
        assert call_env["ANTHROPIC_BASE_URL"] == expected

    @patch("tokentap.cli.subprocess.run")
    def test_openai_no_proxy_path(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit, match="0"):
            _run_tool("openai", "codex", DEFAULT_PROXY_PORT, ())
        call_env = mock_run.call_args[1]["env"]
        expected = f"http://127.0.0.1:{DEFAULT_PROXY_PORT}"
        assert call_env["OPENAI_BASE_URL"] == expected

    @patch("tokentap.cli.subprocess.run")
    def test_minimax_custom_port(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with pytest.raises(SystemExit, match="0"):
            _run_tool("minimax", "python", 9090, ("app.py",))
        call_env = mock_run.call_args[1]["env"]
        assert call_env["OPENAI_BASE_URL"] == "http://127.0.0.1:9090/minimax/v1"


class TestRunCommand:
    """Tests for the 'run' CLI command with MiniMax provider."""

    def test_minimax_in_provider_choices(self):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "minimax" in result.output

    @patch("tokentap.cli.subprocess.run")
    def test_run_minimax_provider(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        runner = CliRunner()
        result = runner.invoke(
            main, ["run", "--provider", "minimax", "python", "test.py"]
        )
        assert result.exit_code == 0
        call_env = mock_run.call_args[1]["env"]
        assert "/minimax/v1" in call_env["OPENAI_BASE_URL"]
