import json
import asyncio

import aiohttp
import pytest
from aiohttp import ClientSession, web

from privacytap.proxy import PrivacyProxyServer
from privacytap.sse import SSEEvent, SSEParser, encode_sse


async def start_anthropic_upstream(port, messages, count_tokens=None):
    app = web.Application()
    app.router.add_post("/v1/messages", messages)
    if count_tokens is not None:
        app.router.add_post(
            "/v1/messages/count_tokens", count_tokens
        )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


def parse_sse(raw: bytes) -> list[dict]:
    parser = SSEParser()
    events = parser.feed(raw)
    events.extend(parser.finish())
    return [json.loads(event.data) for event in events]


@pytest.mark.asyncio
async def test_messages_json_anonymizes_upstream_restores_client_and_logs(
    unused_tcp_port,
):
    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "msg_demo",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [
                    {
                        "type": "text",
                        "text": "联系 [PHONE_1] 和 [EMAIL_1]",
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 4},
            }
        )

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    events = []
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=events.append,
    )
    await proxy.start()
    key = "sk-ant-currenttransportkey123456"
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                headers={
                    "X-Api-Key": key,
                    "Anthropic-Version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 64,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "联系 13800138000 和 "
                                "alice@example.com"
                            ),
                        }
                    ],
                },
            )
            body = await response.json()
        assert response.status == 200
        assert (
            captured["body"]["messages"][0]["content"]
            == "联系 [PHONE_1] 和 [EMAIL_1]"
        )
        assert captured["headers"]["X-Api-Key"] == key
        assert (
            body["content"][0]["text"]
            == "联系 13800138000 和 alice@example.com"
        )
        serialized = json.dumps(events, ensure_ascii=False)
        assert "13800138000" not in serialized
        assert "alice@example.com" not in serialized
        assert key not in serialized
        assert events[0]["provider"] == "anthropic-messages"
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_count_tokens_sends_only_sanitized_request(
    unused_tcp_port,
):
    captured = {}

    async def messages(request):
        return web.json_response({})

    async def count_tokens(request):
        captured["body"] = await request.json()
        return web.json_response({"input_tokens": 12})

    runner = await start_anthropic_upstream(
        unused_tcp_port, messages, count_tokens
    )
    events = []
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=events.append,
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                (
                    f"http://127.0.0.1:{proxy.bound_port}"
                    "/v1/messages/count_tokens"
                ),
                headers={
                    "X-Api-Key": "sk-ant-currentkey123456",
                    "Anthropic-Version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "messages": [
                        {
                            "role": "user",
                            "content": "邮箱 alice@example.com",
                        }
                    ],
                },
            )
            body = await response.json()
        assert body == {"input_tokens": 12}
        assert (
            captured["body"]["messages"][0]["content"]
            == "邮箱 [EMAIL_1]"
        )
        assert events[0]["provider"] == "anthropic-count-tokens"
        assert events[0]["tokens"] == 12
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_current_anthropic_key_in_prompt_is_blocked(
    unused_tcp_port,
):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return web.json_response({})

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
    )
    await proxy.start()
    key = "sk-ant-currenttransportkey123456"
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                headers={"X-Api-Key": key},
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"不要泄露 {key}",
                        }
                    ],
                },
            )
            body = await response.json()
        assert response.status == 422
        assert body["error"]["code"] == "sensitive_credential_detected"
        assert key not in json.dumps(body)
        assert calls == 0
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_anthropic_connection_failure_maps_to_502():
    class FailingAdapter:
        async def post(self, endpoint, headers, payload):
            raise aiohttp.ClientConnectionError("refused")

    proxy = PrivacyProxyServer(
        port=0, upstream_base_url="http://127.0.0.1:9"
    )
    proxy.anthropic = FailingAdapter()
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [],
                },
            )
            body = await response.json()
        assert response.status == 502
        assert body["error"]["code"] == "upstream_unavailable"
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_anthropic_timeout_maps_to_504(unused_tcp_port):
    async def handler(request):
        await asyncio.sleep(0.2)
        return web.json_response({})

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        upstream_timeout=0.01,
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [],
                },
            )
            body = await response.json()
        assert response.status == 504
        assert body["error"]["code"] == "upstream_timeout"
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_anthropic_invalid_request_json_returns_400():
    proxy = PrivacyProxyServer(
        port=0, upstream_base_url="http://127.0.0.1:9"
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                data="{",
                headers={"Content-Type": "application/json"},
            )
            body = await response.json()
        assert response.status == 400
        assert body["error"]["code"] == "invalid_json"
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_anthropic_non_object_request_returns_400():
    proxy = PrivacyProxyServer(
        port=0, upstream_base_url="http://127.0.0.1:9"
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json=[],
            )
            body = await response.json()
        assert response.status == 400
        assert body["error"]["code"] == "invalid_json"
    finally:
        await proxy.stop()


@pytest.mark.asyncio
async def test_anthropic_invalid_upstream_json_returns_502(
    unused_tcp_port,
):
    async def handler(request):
        return web.Response(
            body=b"{",
            headers={"Content-Type": "application/json"},
        )

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [],
                },
            )
            body = await response.json()
        assert response.status == 502
        assert body["error"]["code"] == "invalid_upstream_json"
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_anthropic_non_json_upstream_body_is_preserved(
    unused_tcp_port,
):
    async def handler(request):
        return web.Response(status=429, text="limited")

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [],
                },
            )
            body = await response.text()
        assert response.status == 429
        assert body == "limited"
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_anthropic_invalid_sse_is_not_forwarded(
    unused_tcp_port,
):
    async def handler(request):
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        await response.write(
            b"event: content_block_delta\ndata: not-json\n\n"
        )
        await response.write_eof()
        return response

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    events = []
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=events.append,
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "stream": True,
                    "messages": [
                        {
                            "role": "user",
                            "content": "电话 13800138000",
                        }
                    ],
                },
            )
            raw = await response.read()
        assert response.status == 200
        assert b"not-json" not in raw
        assert "13800138000" not in json.dumps(
            events, ensure_ascii=False
        )
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_anthropic_exporter_failure_does_not_break_response(
    unused_tcp_port,
):
    async def handler(request):
        return web.json_response(
            {
                "id": "msg_demo",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )

    def failing_exporter(event):
        raise RuntimeError("archive unavailable")

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=failing_exporter,
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 8,
                    "messages": [],
                },
            )
            body = await response.json()
        assert response.status == 200
        assert body["content"][0]["text"] == "ok"
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_messages_sse_restores_text_and_tool_arguments(
    unused_tcp_port,
):
    captured = {}

    async def handler(request):
        captured["body"] = await request.json()
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_demo",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": "claude-sonnet-4-5",
                        "stop_reason": None,
                        "usage": {
                            "input_tokens": 5,
                            "output_tokens": 0,
                        },
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "text_delta",
                        "text": "联系 [PHO",
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "text_delta",
                        "text": "NE_1]",
                    },
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 0},
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_demo",
                        "name": "Write",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": (
                            '{"path":"[EMAIL_1]"}'
                        ),
                    },
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 1},
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 8},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        for event_name, payload in events:
            await response.write(
                encode_sse(
                    SSEEvent(
                        event=event_name,
                        data=json.dumps(
                            payload, ensure_ascii=False
                        ),
                    )
                )
            )
        await response.write_eof()
        return response

    runner = await start_anthropic_upstream(
        unused_tcp_port, handler
    )
    events = []
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=events.append,
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/messages",
                headers={
                    "X-Api-Key": "sk-ant-currentkey123456",
                    "Anthropic-Version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 64,
                    "stream": True,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "联系 13800138000，写入 "
                                "alice@example.com"
                            ),
                        }
                    ],
                },
            )
            raw = await response.read()
        assert response.status == 200
        assert (
            captured["body"]["messages"][0]["content"]
            == "联系 [PHONE_1]，写入 [EMAIL_1]"
        )
        payloads = parse_sse(raw)
        text = "".join(
            payload["delta"]["text"]
            for payload in payloads
            if payload.get("delta", {}).get("type") == "text_delta"
        )
        tool = "".join(
            payload["delta"]["partial_json"]
            for payload in payloads
            if payload.get("delta", {}).get("type")
            == "input_json_delta"
        )
        assert text == "联系 13800138000"
        assert tool == '{"path":"alice@example.com"}'
        serialized = json.dumps(events, ensure_ascii=False)
        assert "13800138000" not in serialized
        assert "alice@example.com" not in serialized
    finally:
        await proxy.stop()
        await runner.cleanup()
