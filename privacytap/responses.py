from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

import aiohttp

from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.transformer import restore_payload
from privacytap.privacy.vault import RequestVault
from privacytap.sse import SSEDecodeError, SSEEvent


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "content-encoding",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DELTA_EVENT_TYPES = {
    "response.output_text.delta",
    "response.function_call_arguments.delta",
}
DONE_EVENT_TYPES = {
    "response.output_text.done",
    "response.function_call_arguments.done",
}


def forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS | {"content-type"}
    }


def stream_key(payload: dict) -> str | None:
    event_type = payload.get("type")
    if event_type in {
        "response.output_text.delta",
        "response.output_text.done",
    }:
        return (
            f"text:{payload.get('item_id', '')}:"
            f"{payload.get('content_index', 0)}"
        )
    if event_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
    }:
        return (
            "call:"
            f"{payload.get('item_id', payload.get('output_index', 0))}"
        )
    return None


class ResponsesEventRestorer:
    """Restore known Responses API SSE event fields."""

    def __init__(self, vault: RequestVault) -> None:
        self._vault = vault
        self._streaming = StreamingRestorer(vault)
        self._templates: dict[str, tuple[SSEEvent, dict]] = {}
        self._sequence_offset = 0
        self._last_sequence = 0

    def transform(self, event: SSEEvent) -> list[SSEEvent]:
        if event.data == "[DONE]":
            return [event]
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise SSEDecodeError("SSE data is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise SSEDecodeError("SSE data must be a JSON object")

        key = stream_key(payload)
        if (
            key is not None
            and payload.get("type") in DELTA_EVENT_TYPES
            and isinstance(payload.get("delta"), str)
        ):
            self._templates[key] = (event, dict(payload))
            payload["delta"] = self._streaming.feed(
                key, payload["delta"]
            )
            self._adjust_sequence(payload)
            return [self._encode_payload(event, payload)]

        output: list[SSEEvent] = []
        if key is not None and payload.get("type") in DONE_EVENT_TYPES:
            pending = self._streaming.finish(key)
            if pending:
                output.append(
                    self._flush_event(key, pending, payload)
                )
        elif payload.get("type") == "response.completed":
            for pending_key, pending in self._streaming.finish_all().items():
                if pending:
                    output.append(
                        self._flush_event(
                            pending_key, pending, payload
                        )
                    )

        payload = restore_payload(payload, self._vault)
        self._adjust_sequence(payload)
        output.append(self._encode_payload(event, payload))
        return output

    def finish(self) -> list[SSEEvent]:
        output: list[SSEEvent] = []
        for key, pending in self._streaming.finish_all().items():
            if pending:
                output.append(self._flush_event(key, pending))
        return output

    def _flush_event(
        self,
        key: str,
        pending: str,
        current_payload: dict | None = None,
    ) -> SSEEvent:
        template_event, template_payload = self._templates.pop(key)
        payload = dict(template_payload)
        payload["delta"] = pending
        current_sequence = (
            current_payload.get("sequence_number")
            if current_payload is not None
            else None
        )
        if isinstance(current_sequence, int):
            payload["sequence_number"] = (
                current_sequence + self._sequence_offset
            )
            self._sequence_offset += 1
        else:
            payload["sequence_number"] = self._last_sequence + 1
        self._last_sequence = int(payload["sequence_number"])
        return self._encode_payload(template_event, payload)

    def _adjust_sequence(self, payload: dict) -> None:
        sequence = payload.get("sequence_number")
        if isinstance(sequence, int):
            payload["sequence_number"] = sequence + self._sequence_offset
            self._last_sequence = int(payload["sequence_number"])

    @staticmethod
    def _encode_payload(event: SSEEvent, payload: dict) -> SSEEvent:
        return SSEEvent(
            event=event.event,
            data=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
            event_id=event.event_id,
            retry=event.retry,
        )


@dataclass(slots=True)
class UpstreamResponse:
    response: aiohttp.ClientResponse
    session: aiohttp.ClientSession

    async def close(self) -> None:
        self.response.release()
        await self.session.close()


class OpenAIResponsesAdapter:
    """Forward sanitized Responses API requests to an OpenAI upstream."""

    def __init__(
        self,
        upstream_base_url: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._url = f"{upstream_base_url.rstrip('/')}/v1/responses"
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def post(
        self,
        headers: Mapping[str, str],
        payload: dict,
    ) -> UpstreamResponse:
        session = aiohttp.ClientSession(timeout=self._timeout)
        try:
            response = await session.post(
                self._url,
                headers=forward_headers(headers),
                json=payload,
            )
        except Exception:
            await session.close()
            raise
        return UpstreamResponse(response=response, session=session)
