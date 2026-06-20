# Claude Code Messages Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Claude Code 2.1.177 使用 `ANTHROPIC_API_KEY` 通过 PrivacyTap 的 Anthropic Messages API安全工作，并支持 JSON、SSE、工具参数恢复、Token 计数和零原文归档。

**Architecture:** 在现有 OpenAI Responses 适配旁新增独立 `anthropic.py` 协议模块，将共享隐私转换、SSE Codec 和 RequestVault继续作为协议无关基础设施。Proxy 注册 `/v1/messages` 与 `/v1/messages/count_tokens`，Anthropic事件恢复器仅解释 Messages SSE 的 `text_delta` 和 `input_json_delta`，签名及未知事件保持不变。

**Tech Stack:** Python 3.10+、aiohttp、Click、pytest、pytest-asyncio、pytest-cov、Anthropic Messages API、Server-Sent Events、Claude Code 2.1.177。

---

## File map

- Create: `privacytap/anthropic.py`
  - Anthropic Header 过滤、上游适配器、Messages SSE 恢复。
- Create: `tests/test_anthropic_contract.py`
  - Anthropic事件结构、分片、工具参数、签名和未知事件契约。
- Create: `tests/test_anthropic_proxy.py`
  - Messages JSON/SSE、count_tokens、认证、错误和安全事件集成测试。
- Create: `examples/mock_anthropic_upstream.py`
  - 可由真实 Claude Code二进制调用的本地 Anthropic Mock。
- Modify: `privacytap/proxy.py`
  - 注册 Anthropic路由、统一请求处理和安全归档。
- Modify: `privacytap/cli.py`
  - Provider 增加 `anthropic`，按 Provider 选择默认上游。
- Modify: `tests/test_cli.py`
  - Anthropic CLI 选项和默认 URL测试。
- Modify: `tests/test_privacy_invariants.py`
  - Anthropic并发 Vault隔离。
- Modify: `tests/test_demo_client.py`
  - Mock Anthropic路由契约。
- Modify: `tests/test_standalone_contract.py`
  - README Claude Code文档契约。
- Modify: `README.md`
  - 增加 Claude Code配置、启动、离线与真实验证。
- Modify: `docs/experiment.md`
  - 增加 Claude Messages 双证据实验。
- Modify: `.env.example`
  - 增加 Anthropic环境变量。
- Modify: `scripts/evaluate_privacy.py`
  - 增加 Anthropic delta 分片恢复量化。

### Task 1: Anthropic Header and adapter primitives

**Files:**
- Create: `privacytap/anthropic.py`
- Create: `tests/test_anthropic_contract.py`

- [ ] **Step 1: Write failing Header and URL tests**

Create `tests/test_anthropic_contract.py`:

```python
from privacytap.anthropic import (
    AnthropicMessagesAdapter,
    forward_anthropic_headers,
)


def test_anthropic_headers_preserve_protocol_and_auth_headers():
    result = forward_anthropic_headers({
        "Host": "127.0.0.1:8080",
        "Content-Length": "10",
        "X-Api-Key": "sk-ant-demo",
        "Anthropic-Version": "2023-06-01",
        "Anthropic-Beta": "prompt-caching-2024-07-31",
        "X-Claude-Code-Session-Id": "session-1",
        "User-Agent": "claude-code/2.1.177",
    })
    assert "Host" not in result
    assert "Content-Length" not in result
    assert result["X-Api-Key"] == "sk-ant-demo"
    assert result["Anthropic-Version"] == "2023-06-01"
    assert result["Anthropic-Beta"] == "prompt-caching-2024-07-31"
    assert result["X-Claude-Code-Session-Id"] == "session-1"


def test_anthropic_adapter_builds_both_endpoint_urls():
    adapter = AnthropicMessagesAdapter("https://api.anthropic.com/")
    assert adapter.messages_url == "https://api.anthropic.com/v1/messages"
    assert (
        adapter.count_tokens_url
        == "https://api.anthropic.com/v1/messages/count_tokens"
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_contract.py -q
```

Expected: FAIL with `ModuleNotFoundError: privacytap.anthropic`.

- [ ] **Step 3: Implement Header filtering and adapter**

Create `privacytap/anthropic.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import aiohttp

from privacytap.responses import HOP_BY_HOP_HEADERS


def forward_anthropic_headers(
    headers: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def anthropic_response_headers(
    headers: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS | {"content-type"}
    }


@dataclass(slots=True)
class AnthropicUpstreamResponse:
    response: aiohttp.ClientResponse
    session: aiohttp.ClientSession

    async def close(self) -> None:
        self.response.release()
        await self.session.close()


class AnthropicMessagesAdapter:
    def __init__(
        self,
        upstream_base_url: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        base = upstream_base_url.rstrip("/")
        self.messages_url = f"{base}/v1/messages"
        self.count_tokens_url = f"{base}/v1/messages/count_tokens"
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def post(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        payload: dict,
    ) -> AnthropicUpstreamResponse:
        url = (
            self.messages_url
            if endpoint == "messages"
            else self.count_tokens_url
        )
        session = aiohttp.ClientSession(timeout=self._timeout)
        try:
            response = await session.post(
                url,
                headers=forward_anthropic_headers(headers),
                json=payload,
            )
        except Exception:
            await session.close()
            raise
        return AnthropicUpstreamResponse(response, session)
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_contract.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/anthropic.py tests/test_anthropic_contract.py
git commit -m "feat: add Anthropic Messages adapter primitives"
```

### Task 2: Anthropic event restoration

**Files:**
- Modify: `privacytap/anthropic.py`
- Modify: `tests/test_anthropic_contract.py`

- [ ] **Step 1: Write failing text and tool delta tests**

Add:

```python
import json
import pytest

from privacytap.anthropic import AnthropicEventRestorer
from privacytap.privacy.models import EntityType
from privacytap.privacy.vault import RequestVault
from privacytap.sse import SSEEvent


@pytest.mark.parametrize("split_at", range(1, len("[EMAIL_1]")))
def test_anthropic_text_delta_restores_every_split(split_at):
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.EMAIL, "alice@example.com"
    )
    restorer = AnthropicEventRestorer(vault)
    chunks = []
    for text in (placeholder[:split_at], placeholder[split_at:]):
        output = restorer.transform(SSEEvent(
            event="content_block_delta",
            data=json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            }),
        ))
        chunks.extend(
            json.loads(event.data)["delta"]["text"]
            for event in output
        )
    chunks.extend(
        json.loads(event.data)["delta"]["text"]
        for event in restorer.finish()
    )
    assert "".join(chunks) == "alice@example.com"


def test_anthropic_tool_partial_json_restores_and_isolates_indexes():
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.STUDENT_ID, "2023123456"
    )
    restorer = AnthropicEventRestorer(vault)
    left = restorer.transform(SSEEvent(
        event="content_block_delta",
        data=json.dumps({
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": f'{{"id":"{placeholder[:5]}',
            },
        }),
    ))
    right = restorer.transform(SSEEvent(
        event="content_block_delta",
        data=json.dumps({
            "type": "content_block_delta",
            "index": 2,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"safe":true}',
            },
        }),
    ))
    left += restorer.transform(SSEEvent(
        event="content_block_delta",
        data=json.dumps({
            "type": "content_block_delta",
            "index": 1,
            "delta": {
                "type": "input_json_delta",
                "partial_json": f'{placeholder[5:]}"}}',
            },
        }),
    ))
    assert "".join(
        json.loads(event.data)["delta"]["partial_json"]
        for event in left
    ) == '{"id":"2023123456"}'
    assert json.loads(right[0].data)["delta"]["partial_json"] == (
        '{"safe":true}'
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_contract.py -q
```

Expected: FAIL because `AnthropicEventRestorer` is missing.

- [ ] **Step 3: Implement Anthropic delta restoration**

Add to `privacytap/anthropic.py`:

```python
import json

from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.transformer import restore_payload
from privacytap.privacy.vault import RequestVault
from privacytap.sse import SSEDecodeError, SSEEvent


class AnthropicEventRestorer:
    def __init__(self, vault: RequestVault) -> None:
        self._vault = vault
        self._streaming = StreamingRestorer(vault)
        self._templates: dict[str, tuple[SSEEvent, dict]] = {}

    def transform(self, event: SSEEvent) -> list[SSEEvent]:
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise SSEDecodeError(
                "Anthropic SSE data is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SSEDecodeError(
                "Anthropic SSE data must be a JSON object"
            )

        key, field = self._delta_target(payload)
        if key is not None and field is not None:
            self._templates[key] = (event, payload)
            delta = payload["delta"]
            delta[field] = self._streaming.feed(key, delta[field])
            return [self._encode(event, payload)]

        output = []
        if payload.get("type") == "content_block_stop":
            key_candidates = (
                f"text:{payload.get('index')}",
                f"tool:{payload.get('index')}",
            )
            for candidate in key_candidates:
                pending = self._streaming.finish(candidate)
                if pending:
                    output.append(self._flush(candidate, pending))
        elif payload.get("type") == "message_stop":
            for key, pending in self._streaming.finish_all().items():
                if pending:
                    output.append(self._flush(key, pending))

        output.append(self._encode(
            event, self._restore_safe_event(payload)
        ))
        return output

    def finish(self) -> list[SSEEvent]:
        return [
            self._flush(key, pending)
            for key, pending in self._streaming.finish_all().items()
            if pending
        ]

    @staticmethod
    def _delta_target(payload):
        if payload.get("type") != "content_block_delta":
            return None, None
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            return None, None
        index = payload.get("index", 0)
        if delta.get("type") == "text_delta":
            return f"text:{index}", "text"
        if delta.get("type") == "input_json_delta":
            return f"tool:{index}", "partial_json"
        return None, None
```

Implement `_flush`, `_encode`, and `_restore_safe_event`. `_restore_safe_event`
must recursively restore normal events but return payload unchanged when delta
type is `signature_delta`. Preserve all event metadata.

- [ ] **Step 4: Add stop, signature, ping and unknown-event tests**

Add tests asserting:

- `content_block_stop` emits pending delta before stop.
- `message_stop` flushes all indexes.
- `signature_delta.signature` is byte-for-byte unchanged.
- `ping` is unchanged.
- Unknown dictionary event is recursively restored only in ordinary strings.
- Invalid JSON and non-object event raise `SSEDecodeError`.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_contract.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/anthropic.py tests/test_anthropic_contract.py
git commit -m "feat: restore Anthropic text and tool streams"
```

### Task 3: Non-streaming Messages proxy

**Files:**
- Modify: `privacytap/proxy.py`
- Create: `tests/test_anthropic_proxy.py`

- [ ] **Step 1: Write failing Messages JSON integration test**

Create `tests/test_anthropic_proxy.py`:

```python
import json
import pytest
from aiohttp import ClientSession, web

from privacytap.proxy import PrivacyProxyServer


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


@pytest.mark.asyncio
async def test_messages_json_anonymizes_upstream_restores_client_and_logs(
    unused_tcp_port,
):
    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response({
            "id": "msg_demo",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5",
            "content": [{
                "type": "text",
                "text": "联系 [PHONE_1] 和 [EMAIL_1]",
            }],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 4},
        })

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
                    "messages": [{
                        "role": "user",
                        "content": (
                            "联系 13800138000 和 alice@example.com"
                        ),
                    }],
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
    finally:
        await proxy.stop()
        await runner.cleanup()
```

- [ ] **Step 2: Run test and verify 404**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_proxy.py::test_messages_json_anonymizes_upstream_restores_client_and_logs -q
```

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Register Anthropic adapter and routes**

In `PrivacyProxyServer.__init__`:

```python
self.anthropic = AnthropicMessagesAdapter(
    self.upstream_base_url,
    timeout_seconds=upstream_timeout,
)
self.app.router.add_post("/v1/messages", self.handle_messages)
self.app.router.add_post(
    "/v1/messages/count_tokens",
    self.handle_count_tokens,
)
```

Add:

```python
@staticmethod
def _anthropic_credentials(request: web.Request) -> set[str]:
    values = set()
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        values.add(api_key)
    values.update(PrivacyProxyServer._bearer_credentials(request))
    return values
```

Implement `_read_json_object`, `_post_anthropic`, and `handle_messages`:

1. Validate JSON object.
2. `sanitize_payload(..., blocked_credentials=...)`.
3. Call adapter endpoint `messages`.
4. If SSE, delegate to Task 4 stream handler.
5. For JSON, archive sanitized response and restore recursively.
6. Map timeout to 504 and `aiohttp.ClientError` to 502.
7. Close upstream in `finally`.

- [ ] **Step 4: Add Anthropic safe-event builder**

```python
@staticmethod
def _build_anthropic_event(
    sanitized: SanitizedPayload,
    safe_response: dict | list,
    provider: str = "anthropic-messages",
) -> dict:
    response_object = (
        safe_response if isinstance(safe_response, dict) else {}
    )
    usage = response_object.get("usage") or {}
    tokens = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
    )
    return {
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "model": sanitized.payload.get("model", "unknown"),
        "tokens": tokens,
        "request": sanitized.payload,
        "response": safe_response,
        "privacy": {
            "detected": sanitized.stats.detected,
            "processing_ms": round(
                sanitized.stats.processing_ms, 3
            ),
            "placeholder_count": sanitized.vault.placeholder_count,
        },
    }
```

- [ ] **Step 5: Run test and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_proxy.py::test_messages_json_anonymizes_upstream_restores_client_and_logs tests/test_responses_proxy.py -q
```

Expected: PASS and existing Responses tests remain green.

Commit:

```powershell
git add privacytap/proxy.py tests/test_anthropic_proxy.py
git commit -m "feat: proxy non-streaming Anthropic Messages"
```

### Task 4: Anthropic Messages SSE proxy

**Files:**
- Modify: `privacytap/proxy.py`
- Modify: `tests/test_anthropic_proxy.py`

- [ ] **Step 1: Write failing SSE text and tool test**

Mock upstream emits:

```python
events = [
    ("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_demo",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": "claude-sonnet-4-5",
            "stop_reason": None,
            "usage": {"input_tokens": 5, "output_tokens": 0},
        },
    }),
    ("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    }),
    ("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "联系 [PHO"},
    }),
    ("content_block_delta", {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "NE_1]"},
    }),
    ("content_block_start", {
        "type": "content_block_start",
        "index": 1,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_demo",
            "name": "Write",
            "input": {},
        },
    }),
    ("content_block_delta", {
        "type": "content_block_delta",
        "index": 1,
        "delta": {
            "type": "input_json_delta",
            "partial_json": '{"path":"[EMAIL_1]"}',
        },
    }),
    ("content_block_stop", {
        "type": "content_block_stop", "index": 1,
    }),
    ("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 8},
    }),
    ("message_stop", {"type": "message_stop"}),
]
```

Client assertions:

```python
assert "".join(text_deltas) == "联系 13800138000"
assert "".join(tool_deltas) == '{"path":"alice@example.com"}'
assert raw secrets not in safe events
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_proxy.py -q
```

Expected: streaming test FAIL because stream handler is absent.

- [ ] **Step 3: Implement `_stream_anthropic_messages`**

Use `SSEParser`, `AnthropicEventRestorer`, and `encode_sse`:

```python
async def _stream_anthropic_messages(
    self, request, upstream, sanitized
):
    headers = anthropic_response_headers(
        upstream.response.headers
    )
    headers["Content-Type"] = "text/event-stream"
    client = web.StreamResponse(
        status=upstream.response.status,
        headers=headers,
    )
    await client.prepare(request)
    parser = SSEParser()
    restorer = AnthropicEventRestorer(sanitized.vault)
    safe_events = []

    async def process(events):
        for event in events:
            safe_events.append({
                "event": event.event,
                "data": json.loads(event.data),
            })
            for restored in restorer.transform(event):
                await client.write(encode_sse(restored))

    try:
        async for chunk in upstream.response.content.iter_any():
            await process(parser.feed(chunk))
        await process(parser.finish())
        for event in restorer.finish():
            await client.write(encode_sse(event))
    except (json.JSONDecodeError, SSEDecodeError):
        LOGGER.warning("invalid upstream Anthropic SSE stream")
        safe_events.append({
            "event": "privacytap.error",
            "data": {"code": "invalid_upstream_sse"},
        })
    finally:
        self._emit_safe_event(
            self._build_anthropic_event(
                sanitized, safe_events
            )
        )
        await client.write_eof()
    return client
```

- [ ] **Step 4: Add malformed SSE and exporter failure tests**

Assert:

- invalid event JSON is never forwarded raw;
- trace excludes input secrets;
- exporter exception does not fail valid stream;
- upstream non-2xx status is preserved.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_contract.py tests/test_anthropic_proxy.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/proxy.py tests/test_anthropic_proxy.py
git commit -m "feat: restore Anthropic Messages SSE"
```

### Task 5: Count tokens and error paths

**Files:**
- Modify: `privacytap/proxy.py`
- Modify: `tests/test_anthropic_proxy.py`

- [ ] **Step 1: Write failing count_tokens test**

```python
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
                headers={"X-Api-Key": "sk-ant-currentkey123456"},
                json={
                    "model": "claude-sonnet-4-5",
                    "messages": [{
                        "role": "user",
                        "content": "邮箱 alice@example.com",
                    }],
                },
            )
            body = await response.json()
        assert body == {"input_tokens": 12}
        assert (
            captured["body"]["messages"][0]["content"]
            == "邮箱 [EMAIL_1]"
        )
        assert events[0]["provider"] == "anthropic-count-tokens"
    finally:
        await proxy.stop()
        await runner.cleanup()
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_proxy.py::test_count_tokens_sends_only_sanitized_request -q
```

Expected: FAIL because route handler is incomplete.

- [ ] **Step 3: Implement count_tokens**

Reuse common Anthropic JSON forwarding helper with:

```python
endpoint="count_tokens"
provider="anthropic-count-tokens"
restore_response=False
```

The response is returned unchanged. Safe event tokens should use
`input_tokens`.

- [ ] **Step 4: Add credential and error tests**

Tests:

- exact `x-api-key` in Prompt returns 422 and zero upstream calls;
- Bearer token in Prompt returns 422;
- example credential becomes `[CREDENTIAL_1]`;
- connect failure → 502;
- timeout → 504;
- invalid JSON request → 400;
- non-object request → 400;
- invalid upstream JSON → 502;
- non-JSON upstream body preserves status and body.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_anthropic_proxy.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/proxy.py tests/test_anthropic_proxy.py
git commit -m "feat: support Anthropic token counting and errors"
```

### Task 6: Anthropic concurrency privacy invariants

**Files:**
- Modify: `tests/test_privacy_invariants.py`

- [ ] **Step 1: Add failing 50-request Anthropic test**

Add a local `/v1/messages` upstream. Each request input is `电话 <unique phone>`;
upstream echoes the sanitized content as a text block.

Assertions:

```python
assert outputs == [f"电话 {phone}" for phone in phones]
assert all(
    payload["messages"][0]["content"] == "电话 [PHONE_1]"
    for payload in upstream_payloads
)
assert_secrets_absent(events, phones)
```

- [ ] **Step 2: Run test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_privacy_invariants.py -q
```

Expected: PASS if request-scoped Vault behavior is correct; otherwise fix only
the shared-state defect revealed by the test.

- [ ] **Step 3: Add transport Header no-observation test**

Send:

```python
headers={
    "X-Api-Key": "sk-ant-transportsecret123456",
    "Anthropic-Version": "2023-06-01",
}
```

Assert upstream receives it, events and client errors do not contain it.

- [ ] **Step 4: Run and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_privacy_invariants.py -q
git add tests/test_privacy_invariants.py
git commit -m "test: enforce Anthropic privacy invariants"
```

### Task 7: Provider-aware CLI and Anthropic Mock

**Files:**
- Modify: `privacytap/cli.py`
- Modify: `tests/test_cli.py`
- Create: `examples/mock_anthropic_upstream.py`
- Modify: `tests/test_demo_client.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_start_help_lists_anthropic_provider():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "openai|anthropic" in result.output


def test_default_upstream_depends_on_provider():
    from privacytap.cli import default_upstream_base_url
    assert default_upstream_base_url("openai") == (
        "https://api.openai.com"
    )
    assert default_upstream_base_url("anthropic") == (
        "https://api.anthropic.com"
    )
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q
```

- [ ] **Step 3: Implement provider-aware default**

Use a Click callback or resolve inside `start`:

```python
DEFAULT_UPSTREAMS = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}


def default_upstream_base_url(provider: str) -> str:
    return DEFAULT_UPSTREAMS[provider]
```

Change `--upstream-base-url` default to `None`, then:

```python
upstream_base_url = (
    upstream_base_url
    or default_upstream_base_url(provider)
)
```

Provider choice:

```python
click.Choice(["openai", "anthropic"])
```

- [ ] **Step 4: Create Mock Anthropic**

`examples/mock_anthropic_upstream.py` must expose:

- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

For non-streaming, return Anthropic message JSON. For streaming, emit valid
Anthropic SSE event order. Print sanitized input to console.

- [ ] **Step 5: Add Mock route contract**

```python
def test_mock_anthropic_exposes_gateway_routes():
    from examples.mock_anthropic_upstream import app
    routes = {route.resource.canonical for route in app.router.routes()}
    assert "/v1/messages" in routes
    assert "/v1/messages/count_tokens" in routes
```

- [ ] **Step 6: Update env example**

```dotenv
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key
ANTHROPIC_BASE_URL=http://127.0.0.1:8080
```

- [ ] **Step 7: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_demo_client.py -q
git add privacytap/cli.py tests/test_cli.py examples/mock_anthropic_upstream.py tests/test_demo_client.py .env.example
git commit -m "feat: expose Claude Code gateway from CLI"
```

### Task 8: Claude Code documentation and experiment

**Files:**
- Modify: `README.md`
- Modify: `docs/experiment.md`
- Modify: `tests/test_standalone_contract.py`
- Modify: `scripts/evaluate_privacy.py`
- Modify: `tests/test_evaluate_privacy.py`

- [ ] **Step 1: Add failing README contract**

```python
def test_readme_documents_real_claude_code_setup():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "ANTHROPIC_BASE_URL" in readme
    assert "ANTHROPIC_API_KEY" in readme
    assert "/v1/messages/count_tokens" in readme
    assert "claude --bare -p" in readme
```

- [ ] **Step 2: Run and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standalone_contract.py::test_readme_documents_real_claude_code_setup -q
```

- [ ] **Step 3: Update README**

Add sections:

1. Claude Code真实接入。
2. Claude Code离线 Mock验证。
3. `x-api-key` 和 `anthropic-version` Header说明。
4. Codex 与 Claude 共存端点表。
5. Anthropic真实 API验证任务。

Exact setup:

```powershell
.\.venv\Scripts\privacytap.exe start --provider anthropic
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:8080"
$env:ANTHROPIC_API_KEY="sk-ant-..."
claude --bare -p "Reply with exactly OK"
```

- [ ] **Step 4: Extend experiment document**

Document:

- controlled Anthropic Mock evidence;
- installed Claude Code 2.1.177 protocol smoke;
- real Anthropic cloud test when Key exists;
- text/tool restoration accuracy;
- count_tokens behavior;
- 10-run Claude task table.

- [ ] **Step 5: Extend evaluation**

Add `evaluate_anthropic_streaming_restoration()` that builds
`content_block_delta` events for each placeholder and every split boundary,
passes them through `AnthropicEventRestorer`, and returns:

```python
{
    "cases": ...,
    "accuracy": 1.0,
    "leakage_count": 0,
    "p95_ms": ...,
}
```

Print:

```text
Anthropic streaming cases: <n>
Anthropic restore accuracy: 1.0000
Anthropic raw secret leakage count: 0
Anthropic transform P95: <20ms
```

- [ ] **Step 6: Run tests and evaluation**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standalone_contract.py tests/test_evaluate_privacy.py -q
.\.venv\Scripts\python.exe scripts/evaluate_privacy.py
```

- [ ] **Step 7: Commit**

```powershell
git add README.md docs/experiment.md tests/test_standalone_contract.py scripts/evaluate_privacy.py tests/test_evaluate_privacy.py
git commit -m "docs: add Claude Code privacy gateway guide"
```

### Task 9: Full verification and real Claude CLI protocol smoke

**Files:**
- Modify only when a failing verification demonstrates a defect.

- [ ] **Step 1: Run complete tests**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Enforce coverage**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  --cov=privacytap `
  --cov-report=term-missing `
  --cov-fail-under=90 -q
```

Expected: at least 90%.

- [ ] **Step 3: Run evaluation and build**

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_privacy.py
.\.venv\Scripts\python.exe -m build
```

Expected:

- detection Precision/Recall/F1 = 1.0;
- OpenAI and Anthropic restoration accuracy = 1.0;
- raw leakage counts = 0;
- P95 values below 20 ms;
- wheel contains `privacytap/anthropic.py`.

- [ ] **Step 4: Run direct offline Anthropic endpoint smoke**

Start hidden/local Mock on `18082`, PrivacyTap on `18083`; send JSON and SSE
requests. Assert:

- Mock sees placeholders only.
- Client sees original values.
- trace files contain no originals or Key.
- count_tokens returns valid JSON.

- [ ] **Step 5: Run installed Claude Code against Mock**

Set only for child process:

```powershell
$env:ANTHROPIC_BASE_URL="http://127.0.0.1:18083"
$env:ANTHROPIC_API_KEY="sk-ant-local-test-key-123456"
claude --bare -p --model claude-sonnet-4-5 `
  "Reply with exactly OK"
```

Capture:

- exit code;
- Claude stdout;
- Mock request paths and sanitized bodies;
- PrivacyTap trace leakage scan.

Claude must call the PrivacyTap Anthropic endpoints. Adjust Mock response shape
only when Claude debug/network evidence proves a required official field is
missing.

- [ ] **Step 6: Run real Anthropic smoke when Key exists**

Check only presence, never print value:

```powershell
if ($env:ANTHROPIC_API_KEY) {
  "ANTHROPIC_API_KEY=set"
} else {
  "ANTHROPIC_API_KEY=unset"
}
```

If set, run PrivacyTap with `https://api.anthropic.com` and:

```powershell
claude --bare -p "Reply with exactly OK"
```

Then run a file-tool task containing email and phone.

If unset, record cloud verification as externally blocked. Do not substitute
OAuth or invent success.

- [ ] **Step 7: Final repository audit**

```powershell
git status --short --branch
git log -12 --oneline
```

Ensure no Keys, traces, debug logs, build directories or user Claude settings
are staged. Commit verification fixes only after their regression tests pass.
