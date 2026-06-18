from __future__ import annotations

import json
import logging
import ssl
from datetime import datetime
from typing import Callable

import aiohttp
from aiohttp import web

from tokentap.parser import count_tokens
from tokentap.privacy.models import (
    SanitizedPayload,
    SensitiveCredentialError,
)
from tokentap.privacy.transformer import restore_payload, sanitize_payload


LOGGER = logging.getLogger(__name__)


class PrivacyProxyServer:
    """Non-streaming OpenAI-compatible reversible privacy proxy."""

    def __init__(
        self,
        port: int,
        upstream_base_url: str,
        on_safe_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.port = port
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.on_safe_event = on_safe_event
        self.app = web.Application(client_max_size=2 * 1024 * 1024)
        self.app.router.add_post(
            "/v1/chat/completions", self.handle_chat_completions
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.bound_port: int | None = None

    @staticmethod
    def _error(status: int, code: str, message: str) -> web.Response:
        return web.json_response(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "type": "privacy_proxy_error",
                }
            },
            status=status,
        )

    async def handle_chat_completions(
        self, request: web.Request
    ) -> web.Response:
        try:
            original_payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return self._error(
                400, "invalid_json", "Request body must be a JSON object"
            )

        if not isinstance(original_payload, dict):
            return self._error(
                400, "invalid_json", "Request body must be a JSON object"
            )
        if original_payload.get("stream") is True:
            return self._error(
                400,
                "streaming_not_supported",
                (
                    "PrivacyTap MVP supports only non-streaming "
                    "chat completions"
                ),
            )

        try:
            sanitized = sanitize_payload(original_payload)
        except SensitiveCredentialError as exc:
            return self._error(
                422,
                "sensitive_credential_detected",
                (
                    f"Blocked {len(exc.findings)} credential-like "
                    "value(s); remove them and retry"
                ),
            )

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower()
            not in {"host", "content-length", "content-encoding"}
        }
        upstream_url = (
            f"{self.upstream_base_url}/v1/chat/completions"
        )
        ssl_context = (
            None
            if upstream_url.startswith("http://")
            else ssl.create_default_context()
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    upstream_url,
                    headers=headers,
                    json=sanitized.payload,
                    ssl=ssl_context,
                ) as upstream:
                    raw_response = await upstream.read()
                    response_headers = {
                        key: value
                        for key, value in upstream.headers.items()
                        if key.lower()
                        not in {
                            "content-length",
                            "content-encoding",
                            "transfer-encoding",
                            "content-type",
                        }
                    }
                    if "application/json" not in upstream.headers.get(
                        "Content-Type", ""
                    ):
                        return web.Response(
                            status=upstream.status,
                            headers=response_headers,
                            body=raw_response,
                        )
                    try:
                        safe_response = json.loads(raw_response)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return self._error(
                            502,
                            "invalid_upstream_json",
                            "Upstream returned invalid JSON",
                        )

                    event = self._build_safe_event(
                        sanitized, safe_response
                    )
                    if self.on_safe_event is not None:
                        try:
                            self.on_safe_event(event)
                        except Exception:
                            LOGGER.warning("safe event callback failed")

                    restored_response = restore_payload(
                        safe_response, sanitized.vault
                    )
                    return web.json_response(
                        restored_response,
                        status=upstream.status,
                        headers=response_headers,
                    )
        except aiohttp.ClientError:
            return self._error(
                502,
                "upstream_unavailable",
                "Unable to reach upstream model API",
            )

    @staticmethod
    def _build_safe_event(
        sanitized: SanitizedPayload, safe_response: dict
    ) -> dict:
        request_text = json.dumps(
            sanitized.payload, ensure_ascii=False
        )
        usage = safe_response.get("usage") or {}
        return {
            "timestamp": datetime.now().isoformat(),
            "provider": "openai-compatible",
            "model": sanitized.payload.get("model", "unknown"),
            "tokens": usage.get("total_tokens")
            or count_tokens(request_text),
            "request": sanitized.payload,
            "response": safe_response,
            "privacy": {
                "detected": sanitized.stats.detected,
                "processing_ms": round(
                    sanitized.stats.processing_ms, 3
                ),
                "placeholder_count": sanitized.vault.placeholder_count,
            },
        }

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner, "127.0.0.1", self.port
        )
        await self._site.start()
        server = self._site._server
        if server is None or not server.sockets:
            raise RuntimeError("PrivacyTap proxy failed to bind a socket")
        self.bound_port = server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
