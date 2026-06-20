from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import aiohttp


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
