import json

import pytest
from aiohttp import ClientSession, web

from privacytap.proxy import PrivacyProxyServer
from privacytap.sse import SSEEvent, SSEParser, encode_sse


async def start_responses_upstream(port, handler):
    app = web.Application()
    app.router.add_post("/v1/responses", handler)
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
async def test_responses_json_anonymizes_upstream_and_restores_client(
    unused_tcp_port,
):
    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "resp_demo",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "联系 [PHONE_1]",
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            }
        )

    runner = await start_responses_upstream(unused_tcp_port, handler)
    events = []
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
        on_safe_event=events.append,
    )
    await proxy.start()
    transport_key = "sk-proj-currenttransportkey123456"
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/responses",
                headers={"Authorization": f"Bearer {transport_key}"},
                json={
                    "model": "gpt-5.4",
                    "input": "联系 13800138000",
                    "stream": False,
                },
            )
            body = await response.json()
        assert response.status == 200
        assert captured["body"]["input"] == "联系 [PHONE_1]"
        assert captured["headers"]["Authorization"] == (
            f"Bearer {transport_key}"
        )
        assert (
            body["output"][0]["content"][0]["text"]
            == "联系 13800138000"
        )
        serialized = json.dumps(events, ensure_ascii=False)
        assert "13800138000" not in serialized
        assert transport_key not in serialized
        assert (
            events[0]["response"]["output"][0]["content"][0]["text"]
            == "联系 [PHONE_1]"
        )
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_responses_sse_restores_split_text_and_tool_arguments(
    unused_tcp_port,
):
    captured = {}

    async def handler(request):
        captured["body"] = await request.json()
        response = web.StreamResponse(
            headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        items = [
            (
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "联系 [PHO",
                    "sequence_number": 1,
                },
            ),
            (
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "NE_1]",
                    "sequence_number": 2,
                },
            ),
            (
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "call_1",
                    "output_index": 1,
                    "delta": "{\"path\":\"[EMAIL_1]\"}",
                    "sequence_number": 3,
                },
            ),
            (
                "response.completed",
                {
                    "type": "response.completed",
                    "sequence_number": 4,
                    "response": {
                        "id": "resp_demo",
                        "status": "completed",
                        "usage": {
                            "input_tokens": 4,
                            "output_tokens": 4,
                        },
                    },
                },
            ),
        ]
        for event_name, payload in items:
            frame = encode_sse(
                SSEEvent(
                    event=event_name,
                    data=json.dumps(payload, ensure_ascii=False),
                )
            )
            for byte in frame:
                await response.write(bytes([byte]))
        await response.write_eof()
        return response

    runner = await start_responses_upstream(unused_tcp_port, handler)
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
                f"http://127.0.0.1:{proxy.bound_port}/v1/responses",
                headers={
                    "Authorization": (
                        "Bearer sk-proj-currenttransportkey123456"
                    )
                },
                json={
                    "model": "gpt-5.4",
                    "input": (
                        "联系 13800138000，"
                        "保存到 alice@example.com"
                    ),
                    "stream": True,
                },
            )
            raw = await response.read()
        assert response.status == 200
        assert captured["body"]["input"] == (
            "联系 [PHONE_1]，保存到 [EMAIL_1]"
        )
        payloads = parse_sse(raw)
        text_deltas = [
            payload["delta"]
            for payload in payloads
            if payload["type"] == "response.output_text.delta"
        ]
        tool_deltas = [
            payload["delta"]
            for payload in payloads
            if payload["type"]
            == "response.function_call_arguments.delta"
        ]
        assert "".join(text_deltas) == "联系 13800138000"
        assert "".join(tool_deltas) == (
            '{"path":"alice@example.com"}'
        )
        serialized = json.dumps(events, ensure_ascii=False)
        assert "13800138000" not in serialized
        assert "alice@example.com" not in serialized
        assert "[PHONE_1]" in serialized
        assert "[EMAIL_1]" in serialized
    finally:
        await proxy.stop()
        await runner.cleanup()
