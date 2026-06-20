import json

from aiohttp import web

from privacytap.sse import SSEEvent, encode_sse


def completed_response(payload: dict) -> dict:
    received = json.dumps(
        payload.get("input", ""),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "id": "resp_privacytap_demo",
        "object": "response",
        "status": "completed",
        "model": payload.get("model", "demo-model"),
        "output": [
            {
                "type": "message",
                "id": "msg_privacytap_demo",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": f"上游实际收到：{received}",
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def responses(request: web.Request) -> web.StreamResponse:
    payload = await request.json()
    print("RESPONSES UPSTREAM RECEIVED:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    completed = completed_response(payload)
    if payload.get("stream") is not True:
        return web.json_response(completed)

    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream"}
    )
    await response.prepare(request)
    events = [
        {
            "type": "response.output_text.delta",
            "item_id": "msg_privacytap_demo",
            "output_index": 0,
            "content_index": 0,
            "delta": completed["output"][0]["content"][0]["text"],
            "sequence_number": 1,
        },
        {
            "type": "response.completed",
            "response": completed,
            "sequence_number": 2,
        },
    ]
    for event in events:
        await response.write(
            encode_sse(
                SSEEvent(
                    event=event["type"],
                    data=json.dumps(event, ensure_ascii=False),
                )
            )
        )
    await response.write_eof()
    return response


app = web.Application()
app.router.add_post("/v1/responses", responses)


if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=18080)
