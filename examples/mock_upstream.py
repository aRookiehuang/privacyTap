import json

from aiohttp import web


async def chat(request: web.Request) -> web.Response:
    payload = await request.json()
    print("UPSTREAM RECEIVED:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    content = payload["messages"][-1]["content"]
    return web.json_response(
        {
            "id": "chatcmpl-privacytap-demo",
            "object": "chat.completion",
            "model": payload.get("model", "demo-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"模型收到的内容是：{content}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 20,
                "total_tokens": 40,
            },
        }
    )


app = web.Application()
app.router.add_post("/v1/chat/completions", chat)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=18080)
