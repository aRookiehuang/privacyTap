import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "privacytap.claude.env.example"
LOCAL_CONFIG = ROOT / "privacytap.claude.env"
LAUNCHER = ROOT / "scripts" / "start_claude_with_privacytap.ps1"


def test_example_config_exposes_only_four_user_settings():
    lines = [
        line.strip()
        for line in EXAMPLE_CONFIG.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == [
        "PRIVACYTAP_UPSTREAM_BASE_URL",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "PRIVACYTAP_OUTPUT_DIR",
    ]


def test_launcher_uses_local_proxy_and_ignores_user_settings():
    script = LAUNCHER.read_text(encoding="utf-8")
    for text in (
        "http://127.0.0.1:8080",
        "--provider",
        "anthropic",
        "--upstream-base-url",
        "--archive-dir",
        "--setting-sources",
        "project,local",
        "--model",
    ):
        assert text in script


def test_launcher_parses_in_windows_powershell():
    command = r"""
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $env:PRIVACYTAP_LAUNCHER,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_.Message }
    exit 1
}
"""
    env = os.environ.copy()
    env["PRIVACYTAP_LAUNCHER"] = str(LAUNCHER)
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    error_output = result.stderr.decode(errors="replace")
    assert result.returncode == 0, error_output


def test_launcher_protects_secret_and_owns_proxy_lifecycle():
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "Write-Host $apiKey" not in script
    assert "Write-Output $apiKey" not in script
    assert "Remove-Item Env:ANTHROPIC_AUTH_TOKEN" in script
    assert "-WindowStyle Hidden" in script
    assert "Stop-Process -Id $proxyProcess.Id" in script
    assert "finally" in script


def test_local_secret_config_is_gitignored_even_after_user_creates_it():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "privacytap.claude.env" in gitignore
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(LOCAL_CONFIG)],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0
