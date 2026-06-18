import asyncio
import json
import os
from pathlib import Path

import aiohttp


def get_proxy_url() -> str:
    return os.getenv(
        "PRIVACYTAP_PROXY_URL",
        "http://127.0.0.1:8080/v1/chat/completions",
    )


async def main() -> None:
    cases = json.loads(
        (Path(__file__).parent / "demo_prompts.json").read_text(
            encoding="utf-8"
        )
    )
    async with aiohttp.ClientSession() as session:
        for case in cases:
            response = await session.post(
                get_proxy_url(),
                headers={
                    "Authorization": "Bearer demo-transport-key"
                },
                json={
                    "model": "demo-model",
                    "stream": False,
                    "messages": [
                        {"role": "user", "content": case["prompt"]}
                    ],
                },
            )
            print(
                f"\n=== {case['name']} / HTTP {response.status} ==="
            )
            print(
                json.dumps(
                    await response.json(),
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
