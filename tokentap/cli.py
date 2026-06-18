"""CLI interface for tokentap."""

import asyncio
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from tokentap.config import DEFAULT_PROXY_PORT, DEFAULT_TOKEN_LIMIT, PROVIDERS, PROMPTS_DIR, TOKENTAP_DIR
from tokentap.dashboard import TokenTapDashboard
from tokentap.privacy_proxy import PrivacyProxyServer
from tokentap.proxy import ProxyServer
from tokentap.safe_archive import save_safe_event

console = Console()


def save_prompt_to_file(event: dict, prompts_dir: Path) -> None:
    """Save a prompt to markdown and raw JSON files."""
    prompts_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.fromisoformat(event["timestamp"])
    base_filename = timestamp.strftime(f"%Y-%m-%d_%H-%M-%S_{event['provider']}")

    # Save markdown file (human-readable)
    md_filepath = prompts_dir / f"{base_filename}.md"
    lines = [
        f"# Prompt - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Provider:** {event['provider'].capitalize()}",
        f"**Model:** {event['model']}",
        f"**Tokens:** {event['tokens']:,}",
        "",
        "## Messages",
    ]

    for msg in event.get("messages", []):
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        lines.append(f"### {role}")
        lines.append(content)
        lines.append("")

    md_filepath.write_text("\n".join(lines))

    # Save raw JSON file (original request body)
    raw_body = event.get("raw_body")
    if raw_body is not None:
        json_filepath = prompts_dir / f"{base_filename}.json"
        json_filepath.write_text(json.dumps(raw_body, indent=2))


def get_prompts_dir_interactive() -> Path:
    """Prompt user for prompts directory."""
    console.print(f"[cyan]Directory to save prompts (press Enter for default):[/cyan]")
    console.print(f"[dim]Default: {PROMPTS_DIR}[/dim]")

    try:
        user_input = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        user_input = ""

    if user_input:
        return Path(user_input).expanduser().resolve()
    return PROMPTS_DIR


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """tokentap - LLM API traffic interceptor and token tracker.

    Start the dashboard in one terminal:

        tokentap start

    Then run your LLM tool in another terminal:

        tokentap claude
        tokentap gemini
        tokentap codex
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option("--port", "-p", default=DEFAULT_PROXY_PORT, help="Proxy port number")
@click.option("--limit", "-l", default=DEFAULT_TOKEN_LIMIT, help="Token limit for fuel gauge")
def start(port: int, limit: int):
    """Start the proxy and dashboard.

    Run this in one terminal, then use 'tokentap claude' (or gemini/codex)
    in another terminal.
    """
    # Ask for prompts directory
    prompts_dir = get_prompts_dir_interactive()
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Create dashboard
    dashboard = TokenTapDashboard(token_limit=limit)

    # Event queue for thread-safe communication
    event_queue = []
    event_lock = threading.Lock()

    def on_request(event: dict) -> None:
        """Handle incoming request event."""
        # Save prompt to file
        save_prompt_to_file(event, prompts_dir)
        # Queue event for dashboard
        with event_lock:
            event_queue.append(event)

    def poll_events() -> list[dict]:
        """Poll for new events (called by dashboard)."""
        with event_lock:
            events = event_queue.copy()
            event_queue.clear()
        return events

    # Create and start proxy
    proxy = ProxyServer(port=port, on_request=on_request)

    loop = asyncio.new_event_loop()

    def run_proxy():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(proxy.start())
        loop.run_forever()

    proxy_thread = threading.Thread(target=run_proxy, daemon=True)
    proxy_thread.start()

    # Give proxy time to start
    import time
    time.sleep(0.5)

    console.print(f"[green]Proxy running on http://127.0.0.1:{port}[/green]")
    console.print(f"[green]Saving prompts to {prompts_dir}[/green]")
    console.print()
    console.print("[yellow]In another terminal, run:[/yellow]")
    console.print(f"  [cyan]tokentap claude[/cyan]")
    console.print(f"  [cyan]tokentap gemini[/cyan]")
    console.print(f"  [cyan]tokentap codex[/cyan]")
    console.print()
    console.print("[dim]Starting dashboard...[/dim]")

    import time
    time.sleep(1)

    # Run dashboard
    try:
        dashboard.run(poll_events)
    except KeyboardInterrupt:
        pass
    finally:
        loop.call_soon_threadsafe(loop.stop)
        console.print()
        console.print(f"[cyan]Session complete. Total: {dashboard.total_tokens:,} tokens across {len(dashboard.requests)} requests.[/cyan]")


@main.command("privacy-start")
@click.option(
    "--port", "-p", default=8080, show_default=True, type=int
)
@click.option(
    "--upstream-base-url",
    envvar="PRIVACYTAP_UPSTREAM_BASE_URL",
    required=True,
    help=(
        "OpenAI-compatible upstream base URL without "
        "/v1/chat/completions"
    ),
)
@click.option(
    "--archive-dir",
    default="./privacytap-traces",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--langfuse/--no-langfuse", default=False, show_default=True
)
def privacy_start(
    port: int,
    upstream_base_url: str,
    archive_dir: Path,
    langfuse: bool,
) -> None:
    """Start the full-chain reversible privacy proxy."""
    exporter = None
    if langfuse:
        try:
            from tokentap.privacy.langfuse_exporter import (
                LangfuseSafeExporter,
            )

            exporter = LangfuseSafeExporter()
        except (ImportError, ValueError) as exc:
            raise click.ClickException(
                "Langfuse is unavailable. Install .[langfuse] "
                "and configure credentials."
            ) from exc

    def on_safe_event(event: dict) -> None:
        save_safe_event(event, archive_dir)
        if exporter is not None:
            try:
                exporter.export(event)
            except Exception:
                console.print(
                    "[yellow]Langfuse export failed; "
                    "request result is unaffected.[/yellow]"
                )

    proxy = PrivacyProxyServer(
        port=port,
        upstream_base_url=upstream_base_url,
        on_safe_event=on_safe_event,
    )

    async def serve() -> None:
        await proxy.start()
        try:
            console.print(
                "[green]PrivacyTap listening on "
                f"http://127.0.0.1:{proxy.bound_port}[/green]"
            )
            console.print(
                f"[green]Safe traces: {archive_dir.resolve()}[/green]"
            )
            console.print(
                "[yellow]Only non-streaming POST "
                "/v1/chat/completions is supported.[/yellow]"
            )
            await asyncio.Event().wait()
        finally:
            await proxy.stop()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        console.print("\n[cyan]PrivacyTap stopped.[/cyan]")


@main.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--port", "-p", default=DEFAULT_PROXY_PORT, help="Proxy port number")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def claude(port: int, args: tuple):
    """Run Claude Code with proxy configured.

    Start 'tokentap start' in another terminal first.

    Example: tokentap claude
    """
    _run_tool("anthropic", "claude", port, args)


@main.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--port", "-p", default=DEFAULT_PROXY_PORT, help="Proxy port number")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def gemini(port: int, args: tuple):
    """Run Gemini CLI with proxy configured.

    Start 'tokentap start' in another terminal first.

    Example: tokentap gemini
    """
    _run_tool("gemini", "gemini", port, args)


@main.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--port", "-p", default=DEFAULT_PROXY_PORT, help="Proxy port number")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def codex(port: int, args: tuple):
    """Run OpenAI Codex CLI with proxy configured.

    Start 'tokentap start' in another terminal first.

    Example: tokentap codex
    """
    _run_tool("openai", "codex", port, args)


@main.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--port", "-p", default=DEFAULT_PROXY_PORT, help="Proxy port number")
@click.option("--provider", "-P", required=True, type=click.Choice(list(PROVIDERS.keys())), help="LLM provider")
@click.argument("command")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def run(port: int, provider: str, command: str, args: tuple):
    """Run any command with proxy configured.

    Start 'tokentap start' in another terminal first.

    Example: tokentap run --provider anthropic my-custom-tool --some-flag
    """
    _run_tool(provider, command, port, args)


def _run_tool(provider: str, command: str, port: int, args: tuple) -> None:
    """Run a tool with the proxy environment variable set."""
    provider_config = PROVIDERS.get(provider)
    if not provider_config:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        sys.exit(1)

    env = os.environ.copy()
    proxy_url = f"http://127.0.0.1:{port}"

    # Append provider-specific proxy path (e.g., /minimax/v1 for
    # OpenAI-compatible providers that need path-prefix routing)
    proxy_path = provider_config.get("proxy_path", "")
    if proxy_path:
        proxy_url += proxy_path

    # Set all environment variables for this provider
    for env_var in provider_config["env_vars"]:
        env[env_var] = proxy_url

    cmd = [command] + list(args)
    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except FileNotFoundError:
        console.print(f"[red]Error: '{command}' not found. Make sure it's installed and in your PATH.[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
