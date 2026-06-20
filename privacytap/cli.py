"""Command-line interface for the standalone PrivacyTap proxy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import click

from privacytap.archive import FileExporter
from privacytap.exporters import CompositeExporter, SafeEventExporter
from privacytap.proxy import PrivacyProxyServer


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_UPSTREAMS = {
    "openai": DEFAULT_OPENAI_BASE_URL,
    "anthropic": DEFAULT_ANTHROPIC_BASE_URL,
}


def default_upstream_base_url(provider: str) -> str:
    return DEFAULT_UPSTREAMS[provider]


def _default_langfuse_factory() -> SafeEventExporter:
    from integrations.langfuse_exporter import LangfuseExporter

    return LangfuseExporter()


def build_exporter(
    name: str,
    archive_dir: Path,
    langfuse_factory: Callable[[], SafeEventExporter] | None = None,
) -> SafeEventExporter:
    file_exporter = FileExporter(archive_dir)
    if name == "file":
        return file_exporter

    factory = langfuse_factory or _default_langfuse_factory
    try:
        langfuse_exporter = factory()
    except Exception:
        click.echo(
            "Langfuse unavailable; falling back to local safe archive."
        )
        return file_exporter
    return CompositeExporter([file_exporter, langfuse_exporter])


@click.group()
def main() -> None:
    """PrivacyTap: reversible anonymization proxy for LLM calls."""


@main.command()
@click.option("--port", "-p", default=8080, show_default=True, type=int)
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic"]),
    default="openai",
    show_default=True,
)
@click.option(
    "--upstream-base-url",
    envvar="PRIVACYTAP_UPSTREAM_BASE_URL",
    default=None,
    help="Provider upstream base URL without endpoint path",
)
@click.option(
    "--upstream-timeout",
    envvar="PRIVACYTAP_UPSTREAM_TIMEOUT",
    default=300.0,
    show_default=True,
    type=click.FloatRange(min=0.1),
)
@click.option(
    "--archive-dir",
    default="./privacytap-traces",
    show_default=True,
    type=click.Path(path_type=Path),
)
@click.option(
    "--exporter",
    type=click.Choice(["file", "langfuse"]),
    default="file",
    show_default=True,
)
def start(
    port: int,
    provider: str,
    upstream_base_url: str,
    upstream_timeout: float,
    archive_dir: Path,
    exporter: str,
) -> None:
    """Start the OpenAI or Anthropic privacy proxy."""
    upstream_base_url = (
        upstream_base_url or default_upstream_base_url(provider)
    )
    safe_exporter = build_exporter(exporter, archive_dir)
    proxy = PrivacyProxyServer(
        port=port,
        upstream_base_url=upstream_base_url,
        on_safe_event=safe_exporter.export,
        upstream_timeout=upstream_timeout,
    )

    async def serve() -> None:
        await proxy.start()
        try:
            click.echo(
                f"PrivacyTap listening on "
                f"http://127.0.0.1:{proxy.bound_port}"
            )
            click.echo(f"Safe traces: {archive_dir.resolve()}")
            click.echo(f"Provider: {provider}")
            click.echo("Codex endpoint: /v1/responses (JSON + SSE)")
            click.echo(
                "Claude endpoints: /v1/messages and "
                "/v1/messages/count_tokens"
            )
            click.echo(
                "Legacy endpoint: /v1/chat/completions (non-streaming)"
            )
            await asyncio.Event().wait()
        finally:
            await proxy.stop()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        click.echo("PrivacyTap stopped.")


if __name__ == "__main__":
    main()
