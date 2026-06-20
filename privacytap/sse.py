from __future__ import annotations

import codecs
from dataclasses import dataclass


class SSEDecodeError(ValueError):
    """Raised when an upstream event stream is not valid SSE."""


@dataclass(frozen=True, slots=True)
class SSEEvent:
    event: str | None
    data: str
    event_id: str | None = None
    retry: int | None = None


class SSEParser:
    """Incrementally decode UTF-8 bytes into complete SSE events."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._text = ""

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        try:
            self._text += self._decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise SSEDecodeError("invalid UTF-8 in SSE stream") from exc
        self._normalize_complete_line_endings()
        events: list[SSEEvent] = []
        while "\n\n" in self._text:
            frame, self._text = self._text.split("\n\n", 1)
            event = self._parse_frame(frame)
            if event is not None:
                events.append(event)
        return events

    def finish(self) -> list[SSEEvent]:
        try:
            self._text += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise SSEDecodeError("invalid UTF-8 in SSE stream") from exc
        self._text = self._text.replace("\r\n", "\n").replace("\r", "\n")
        events: list[SSEEvent] = []
        while "\n\n" in self._text:
            frame, self._text = self._text.split("\n\n", 1)
            event = self._parse_frame(frame)
            if event is not None:
                events.append(event)
        if self._text.strip():
            raise SSEDecodeError("incomplete SSE frame")
        self._text = ""
        return events

    def _normalize_complete_line_endings(self) -> None:
        trailing_cr = self._text.endswith("\r")
        complete = self._text[:-1] if trailing_cr else self._text
        complete = complete.replace("\r\n", "\n").replace("\r", "\n")
        self._text = complete + ("\r" if trailing_cr else "")

    @staticmethod
    def _parse_frame(frame: str) -> SSEEvent | None:
        event_name = None
        event_id = None
        retry = None
        data: list[str] = []
        for line in frame.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data.append(value)
            elif field == "id":
                event_id = value
            elif field == "retry":
                try:
                    retry = int(value)
                except ValueError as exc:
                    raise SSEDecodeError("invalid retry field") from exc
        if not data and event_name is None:
            return None
        return SSEEvent(
            event=event_name,
            data="\n".join(data),
            event_id=event_id,
            retry=retry,
        )


def encode_sse(event: SSEEvent) -> bytes:
    """Encode one SSE event using LF line endings."""

    lines: list[str] = []
    if event.event is not None:
        lines.append(f"event: {event.event}")
    if event.event_id is not None:
        lines.append(f"id: {event.event_id}")
    if event.retry is not None:
        lines.append(f"retry: {event.retry}")
    for line in event.data.split("\n"):
        lines.append(f"data: {line}")
    return ("\n".join(lines) + "\n\n").encode()
