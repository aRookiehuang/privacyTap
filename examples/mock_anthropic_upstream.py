import json

from aiohttp import web

from privacytap.sse import SSEEvent, encode_sse


def extract_text(payload: dict) -> str:
    messages = payload.get("messages") or []
    if not messages:
        return ""
    content = messages[-1].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def messages(request: web.Request) -> web.StreamResponse:
    payload = await request.json()
    print("ANTHROPIC UPSTREAM RECEIVED:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    text = f"上游实际收到：{extract_text(payload)}"
    message = {
        "id": "msg_privacytap_demo",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model", "claude-sonnet-4-5"),
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    if payload.get("stream") is not True:
        return web.json_response(message)

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
                    **message,
                    "content": [],
                    "stop_reason": None,
                    "usage": {
                        "input_tokens": 1,
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
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        (
            "content_block_stop",
            {"type": "content_block_stop", "index": 0},
        ),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": 1},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    for event_name, event in events:
        await response.write(
            encode_sse(
                SSEEvent(
                    event=event_name,
                    data=json.dumps(event, ensure_ascii=False),
                )
            )
        )
    await response.write_eof()
    return response


async def count_tokens(request: web.Request) -> web.Response:
    payload = await request.json()
    print("ANTHROPIC COUNT TOKENS RECEIVED:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return web.json_response({"input_tokens": 1})


app = web.Application()
app.router.add_post("/v1/messages", messages)
app.router.add_post("/v1/messages/count_tokens", count_tokens)


if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=18082)
