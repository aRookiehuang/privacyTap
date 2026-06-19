import asyncio
import json

import pytest
from aiohttp import ClientSession, web

from privacytap.proxy import PrivacyProxyServer


def assert_secrets_absent(value, secrets: list[str]) -> None:
    serialized = json.dumps(value, ensure_ascii=False)
    for secret in secrets:
        assert secret not in serialized


async def start_upstream(port, handler):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


@pytest.mark.asyncio
async def test_fifty_concurrent_requests_keep_vaults_isolated(
    unused_tcp_port,
):
    upstream_payloads = []

    async def upstream_handler(request):
        payload = await request.json()
        upstream_payloads.append(payload)
        content = payload["messages"][0]["content"]
        return web.json_response(
            {
                "model": "demo-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 4},
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
    phones = [str(13000000000 + index) for index in range(50)]

    async def send(session: ClientSession, phone: str) -> str:
        response = await session.post(
            f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
            json={
                "model": "demo-model",
                "messages": [
                    {"role": "user", "content": f"电话 {phone}"}
                ],
            },
        )
        assert response.status == 200
        body = await response.json()
        return body["choices"][0]["message"]["content"]

    try:
        async with ClientSession() as session:
            outputs = await asyncio.gather(
                *(send(session, phone) for phone in phones)
            )
        assert outputs == [f"电话 {phone}" for phone in phones]
        assert len(upstream_payloads) == 50
        assert all(
            payload["messages"][0]["content"] == "电话 [PHONE_1]"
            for payload in upstream_payloads
        )
        assert_secrets_absent(events, phones)
    finally:
        await proxy.stop()
        await upstream_runner.cleanup()


@pytest.mark.asyncio
async def test_transport_authorization_is_forwarded_but_never_observed(
    unused_tcp_port,
):
    captured_headers = []

    async def upstream_handler(request):
        captured_headers.append(dict(request.headers))
        return web.json_response(
            {
                "model": "demo-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 2},
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
    transport_secret = "Bearer legitimate-transport-secret-123456789"

    try:
        async with ClientSession() as session:
            allowed = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
                headers={"Authorization": transport_secret},
                json={
                    "model": "demo-model",
                    "messages": [
                        {"role": "user", "content": "hello"}
                    ],
                },
            )
            blocked = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/chat/completions",
                json={
                    "model": "demo-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": f"请检查 {transport_secret}",
                        }
                    ],
                },
            )
            blocked_body = await blocked.json()

        assert allowed.status == 200
        assert captured_headers[0]["Authorization"] == transport_secret
        assert_secrets_absent(events, [transport_secret])
        assert blocked.status == 422
        assert (
            blocked_body["error"]["code"]
            == "sensitive_credential_detected"
        )
        assert_secrets_absent(blocked_body, [transport_secret])
        assert len(captured_headers) == 1
    finally:
        await proxy.stop()
        await upstream_runner.cleanup()
