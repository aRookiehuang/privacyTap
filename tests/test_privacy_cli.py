from click.testing import CliRunner

from tokentap.cli import main


def test_privacy_start_is_listed():
    result = CliRunner().invoke(main, ["privacy-start", "--help"])
    assert result.exit_code == 0
    assert "--upstream-base-url" in result.output
    assert "--archive-dir" in result.output
    assert "--langfuse" in result.output
