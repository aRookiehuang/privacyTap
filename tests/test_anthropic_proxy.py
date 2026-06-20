import json

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
