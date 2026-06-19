from typing import Protocol


class SafeEventExporter(Protocol):
    """An output sink that only accepts already-sanitized events."""

    def export(self, event: dict) -> None: ...


class CompositeExporter:
    """Fan out safe events without allowing optional sinks to break calls."""

    def __init__(self, exporters: list[SafeEventExporter]) -> None:
        self.exporters = exporters

    def export(self, event: dict) -> None:
        for exporter in self.exporters:
            try:
                exporter.export(event)
            except Exception:
                continue
