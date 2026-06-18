import json

import pytest
from aiohttp import ClientSession, web

from tokentap.privacy_proxy import PrivacyProxyServer


async def start_upstream(port, handler):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


@pytest.mark.asyncio
async def test_proxy_anonymizes_upstream_restores_client_and_logs_safe_event(
    unused_tcp_port,
):
    captured = {}

    async def upstream_handler(request):
        captured["request"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl-demo",
                "object": "chat.completion",
                "model": "demo-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "已通知 [PHONE_1] 和 [EMAIL_1]",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                },
            }
        )

    upstream_runner = await start_upstream(
        unused_tcp_port, upstream_handler
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
                f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
                json={
                    "model": "demo-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "联系 13812345678，邮箱 alice@example.com"
                            ),
                        }
                    ],
                },
            )
            body = await response.json()
        assert response.status == 200
        assert (
            captured["request"]["messages"][0]["content"]
            == "联系 [PHONE_1]，邮箱 [EMAIL_1]"
        )
        assert (
            body["choices"][0]["message"]["content"]
            == "已通知 13812345678 和 alice@example.com"
        )
        assert "13812345678" not in json.dumps(events, ensure_ascii=False)
        assert "alice@example.com" not in json.dumps(
            events, ensure_ascii=False
        )
        assert (
            events[0]["response"]["choices"][0]["message"]["content"]
            == "已通知 [PHONE_1] 和 [EMAIL_1]"
        )
    finally:
        await proxy.stop()
        await upstream_runner.cleanup()


@pytest.mark.asyncio
async def test_api_key_is_blocked_without_upstream_call(unused_tcp_port):
    calls = 0

    async def upstream_handler(request):
        nonlocal calls
        calls += 1
        return web.json_response({})

    runner = await start_upstream(unused_tcp_port, upstream_handler)
    proxy = PrivacyProxyServer(
        port=0,
        upstream_base_url=f"http://127.0.0.1:{unused_tcp_port}",
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
                json={
                    "model": "demo-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "密钥 sk-proj-abcdefghijklmnopqrstuv"
                            ),
                        }
                    ],
                },
            )
            body = await response.json()
        assert response.status == 422
        assert body["error"]["code"] == "sensitive_credential_detected"
        assert calls == 0
    finally:
        await proxy.stop()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_streaming_is_explicitly_rejected():
    proxy = PrivacyProxyServer(
        port=0, upstream_base_url="http://127.0.0.1:9"
    )
    await proxy.start()
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
                json={
                    "model": "demo-model",
                    "messages": [],
                    "stream": True,
                },
            )
            body = await response.json()
        assert response.status == 400
        assert body["error"]["code"] == "streaming_not_supported"
    finally:
        await proxy.stop()
