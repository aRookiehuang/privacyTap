import json

import pytest
from aiohttp import ClientSession, web

from privacytap.proxy import PrivacyProxyServer


async def start_responses_upstream(port, handler):
    app = web.Application()
    app.router.add_post("/v1/responses", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner


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
