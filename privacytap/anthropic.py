from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

import aiohttp

from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.transformer import restore_payload
from privacytap.privacy.vault import RequestVault
from privacytap.responses import HOP_BY_HOP_HEADERS
from privacytap.sse import SSEDecodeError, SSEEvent


def forward_anthropic_headers(
    headers: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def anthropic_response_headers(
    headers: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS | {"content-type"}
    }


class AnthropicEventRestorer:
    """Restore Anthropic text and tool-use deltas."""

    def __init__(self, vault: RequestVault) -> None:
        self._vault = vault
        self._streaming = StreamingRestorer(vault)
        self._templates: dict[str, tuple[SSEEvent, dict, str]] = {}

    def transform(self, event: SSEEvent) -> list[SSEEvent]:
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise SSEDecodeError(
                "Anthropic SSE data is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SSEDecodeError(
                "Anthropic SSE data must be a JSON object"
            )

        key, field = self._delta_target(payload)
        if key is not None and field is not None:
            self._templates[key] = (event, dict(payload), field)
            delta = payload["delta"]
            delta[field] = self._streaming.feed(key, delta[field])
            return [self._encode(event, payload)]

        output: list[SSEEvent] = []
        if payload.get("type") == "content_block_stop":
            index = payload.get("index", 0)
            for key in (f"text:{index}", f"tool:{index}"):
                pending = self._streaming.finish(key)
                if pending:
                    output.append(self._flush(key, pending))
        elif payload.get("type") == "message_stop":
            output.extend(self.finish())

        output.append(
            self._encode(event, self._restore_safe_event(payload))
        )
        return output

    def finish(self) -> list[SSEEvent]:
        return [
            self._flush(key, pending)
            for key, pending in self._streaming.finish_all().items()
            if pending
        ]

    @staticmethod
    def _delta_target(payload: dict) -> tuple[str | None, str | None]:
        if payload.get("type") != "content_block_delta":
            return None, None
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            return None, None
        index = payload.get("index", 0)
        if (
            delta.get("type") == "text_delta"
            and isinstance(delta.get("text"), str)
        ):
            return f"text:{index}", "text"
        if (
            delta.get("type") == "input_json_delta"
            and isinstance(delta.get("partial_json"), str)
        ):
            return f"tool:{index}", "partial_json"
        return None, None

    def _flush(self, key: str, pending: str) -> SSEEvent:
        event, template, field = self._templates.pop(key)
        payload = json.loads(json.dumps(template))
        payload["delta"][field] = pending
        return self._encode(event, payload)

    def _restore_safe_event(self, payload: dict) -> dict:
        delta = payload.get("delta")
        if (
            isinstance(delta, dict)
            and delta.get("type") == "signature_delta"
        ):
            return payload
        return restore_payload(payload, self._vault)

    @staticmethod
    def _encode(event: SSEEvent, payload: dict) -> SSEEvent:
        return SSEEvent(
            event=event.event,
            data=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
            event_id=event.event_id,
            retry=event.retry,
        )


@dataclass(slots=True)
class AnthropicUpstreamResponse:
    response: aiohttp.ClientResponse
    session: aiohttp.ClientSession

    async def close(self) -> None:
        self.response.release()
        await self.session.close()


class AnthropicMessagesAdapter:
    def __init__(
        self,
        upstream_base_url: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        base = upstream_base_url.rstrip("/")
        self.messages_url = f"{base}/v1/messages"
        self.count_tokens_url = f"{base}/v1/messages/count_tokens"
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def post(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict,
    ) -> AnthropicUpstreamResponse:
        url = (
            self.messages_url
            if endpoint == "messages"
            else self.count_tokens_url
        )
        session = aiohttp.ClientSession(timeout=self._timeout)
        try:
            response = await session.post(
                url,
                headers=forward_anthropic_headers(headers),
                json=payload,
            )
        except Exception:
            await session.close()
            raise
        return AnthropicUpstreamResponse(response, session)
