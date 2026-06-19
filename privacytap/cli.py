"""Command-line interface for the standalone PrivacyTap proxy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import click

from privacytap.archive import FileExporter
from privacytap.exporters import CompositeExporter, SafeEventExporter
from privacytap.proxy import PrivacyProxyServer


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
    "--exporter",
    type=click.Choice(["file", "langfuse"]),
    default="file",
    show_default=True,
)
def start(
    port: int,
    upstream_base_url: str,
    archive_dir: Path,
    exporter: str,
) -> None:
    """Start the non-streaming OpenAI-compatible privacy proxy."""
    safe_exporter = build_exporter(exporter, archive_dir)
    proxy = PrivacyProxyServer(
        port=port,
        upstream_base_url=upstream_base_url,
        on_safe_event=safe_exporter.export,
    )

    async def serve() -> None:
        await proxy.start()
        try:
            click.echo(
                f"PrivacyTap listening on "
                f"http://127.0.0.1:{proxy.bound_port}"
            )
            click.echo(f"Safe traces: {archive_dir.resolve()}")
            click.echo(
                "Only non-streaming POST /v1/chat/completions "
                "is supported."
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
