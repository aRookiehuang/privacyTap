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
    if event_type == "response.output_text.delta":
        return (
            f"text:{payload.get('item_id', '')}:"
            f"{payload.get('content_index', 0)}"
        )
    if event_type == "response.function_call_arguments.delta":
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
            payload["delta"] = self._streaming.feed(
                key, payload["delta"]
            )
        else:
            payload = restore_payload(payload, self._vault)
        return [self._encode_payload(event, payload)]

    def finish(self) -> None:
        pending = self._streaming.finish_all()
        if any(pending.values()):
            raise SSEDecodeError(
                "response stream ended with an incomplete placeholder prefix"
            )

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
