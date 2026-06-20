# Codex Responses Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让真实 Codex CLI 使用 `OPENAI_API_KEY` 通过 PrivacyTap 的 `/v1/responses` 端点安全访问 OpenAI，并支持 SSE 文本流、工具参数恢复及无原文安全归档。

**Architecture:** 保留现有 Chat Completions 路由，在独立模块中增加 OpenAI Responses 上游适配器和 SSE 编解码/有状态恢复器。请求仍由现有递归隐私转换器处理，但凭证策略调整为“当前传输 Key 精确阻断，其他凭证可逆替换”；上游事件作为安全副本归档，恢复后的事件只返回 Codex。

**Tech Stack:** Python 3.10+、aiohttp、Click、pytest、pytest-asyncio、pytest-cov、OpenAI Responses API、Server-Sent Events。

---

## File map

- Create: `privacytap/sse.py`
  - SSE frame 增量解析、序列化和合法结束处理。
- Create: `privacytap/responses.py`
  - OpenAI Responses 上游转发、JSON/SSE 分流、安全事件收集。
- Create: `privacytap/privacy/streaming.py`
  - 按输出流维护占位符尾缓冲并恢复文本和工具参数增量。
- Create: `tests/test_sse.py`
  - 网络块、换行、多行 data、UTF-8 和非法 frame 测试。
- Create: `tests/test_streaming_restorer.py`
  - 所有占位符切分边界、并行工具调用和流尾刷新测试。
- Create: `tests/test_responses_proxy.py`
  - `/v1/responses` 非流式、SSE、Header、状态码和异常集成测试。
- Create: `tests/test_codex_contract.py`
  - Codex 所需 Responses 事件和安全不变量契约测试。
- Create: `examples/mock_responses_upstream.py`
  - 无真实 Key 的 Codex 协议演示上游。
- Modify: `privacytap/privacy/models.py`
  - 增加 `CREDENTIAL` 实体及凭证策略参数。
- Modify: `privacytap/privacy/transformer.py`
  - 支持传入当前认证 Key并只阻断该 Key，其他凭证进入 Vault。
- Modify: `privacytap/privacy/vault.py`
  - 暴露只读占位符列表，供流式前缀判断使用。
- Modify: `privacytap/proxy.py`
  - 注册 `/v1/responses`、抽取认证 Key、调用 Responses Adapter、统一错误映射。
- Modify: `privacytap/cli.py`
  - 增加 `--provider`、OpenAI 默认上游、超时配置及启动提示。
- Modify: `tests/test_transformer.py`
  - 更新凭证策略测试。
- Modify: `tests/test_privacy_proxy.py`
  - 保证旧 Chat Completions 行为兼容。
- Modify: `tests/test_privacy_invariants.py`
  - 增加 Responses 并发隔离和 Key 不落盘断言。
- Modify: `README.md`
  - 增加真实 Codex 配置、运行、验证和故障排查。
- Modify: `.env.example`
  - 增加 OpenAI 和 PrivacyTap 环境变量示例。
- Modify: `docs/experiment.md`
  - 增加可控 SSE 与真实 Codex 双证据实验。
- Modify: `scripts/evaluate_privacy.py`
  - 纳入 `CREDENTIAL` 和流式恢复性能。

### Task 1: Credential policy for real coding-agent prompts

**Files:**
- Modify: `privacytap/privacy/models.py`
- Modify: `privacytap/privacy/transformer.py`
- Modify: `privacytap/privacy/vault.py`
- Modify: `tests/test_transformer.py`
- Modify: `tests/test_vault.py`

- [ ] **Step 1: Write failing tests for exact transport-key blocking and reversible example credentials**

Add to `tests/test_transformer.py`:

```python
def test_current_transport_key_is_blocked_exactly():
    transport_key = "sk-proj-currenttransportkey123456"
    with pytest.raises(SensitiveCredentialError):
        sanitize_payload(
            {"input": f"不要泄露 {transport_key}"},
            blocked_credentials={transport_key},
        )


def test_other_credential_like_text_is_reversibly_sanitized():
    example_key = "sk-proj-examplecredential123456789"
    result = sanitize_payload(
        {"input": f"请审查代码中的 {example_key}"},
        blocked_credentials={"sk-proj-currenttransportkey123456"},
    )
    assert result.payload["input"] == "请审查代码中的 [CREDENTIAL_1]"
    assert restore_payload(result.payload, result.vault)["input"].endswith(
        example_key
    )
```

Add to `tests/test_vault.py`:

```python
def test_placeholders_are_exposed_without_original_values():
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.EMAIL, "alice@example.com"
    )
    assert vault.placeholders == (placeholder,)
    assert "alice@example.com" not in repr(vault.placeholders)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_transformer.py tests/test_vault.py -q
```

Expected: FAIL because `blocked_credentials`, `EntityType.CREDENTIAL`, and `RequestVault.placeholders` do not exist.

- [ ] **Step 3: Add the credential entity and transformation policy**

In `privacytap/privacy/models.py` add:

```python
class EntityType(str, Enum):
    PHONE = "PHONE"
    CN_ID = "CN_ID"
    EMAIL = "EMAIL"
    BANK_CARD = "BANK_CARD"
    STUDENT_ID = "STUDENT_ID"
    CREDENTIAL = "CREDENTIAL"
    API_KEY = "API_KEY"
```

In `privacytap/privacy/transformer.py`, change the public signature and credential branch:

```python
def _sanitize_text(
    text: str,
    vault: RequestVault,
    all_findings: list[Finding],
    blocked_credentials: frozenset[str],
) -> str:
    findings = detect_sensitive(text)
    blocked = [
        item
        for item in findings
        if item.entity_type == EntityType.API_KEY
        and item.value in blocked_credentials
    ]
    if blocked:
        raise SensitiveCredentialError(blocked)

    normalized = [
        Finding(
            entity_type=(
                EntityType.CREDENTIAL
                if item.entity_type == EntityType.API_KEY
                else item.entity_type
            ),
            start=item.start,
            end=item.end,
            value=item.value,
            confidence=item.confidence,
        )
        for item in findings
    ]
    replaced = text
    for finding in reversed(normalized):
        placeholder = vault.get_or_create(
            finding.entity_type, finding.value
        )
        replaced = (
            replaced[: finding.start]
            + placeholder
            + replaced[finding.end :]
        )
    all_findings.extend(normalized)
    return replaced


def sanitize_payload(
    payload: dict[str, Any],
    blocked_credentials: set[str] | frozenset[str] | None = None,
) -> SanitizedPayload:
    started = time.perf_counter()
    vault = RequestVault()
    findings: list[Finding] = []
    blocked = frozenset(blocked_credentials or ())
    safe_payload = _walk_sanitize(
        copy.deepcopy(payload), vault, findings, blocked
    )
    ...
```

Thread `blocked` through `_walk_sanitize`.

In `privacytap/privacy/vault.py` add:

```python
@property
def placeholders(self) -> tuple[str, ...]:
    return tuple(self._reverse)
```

- [ ] **Step 4: Preserve legacy blocking when no transport credential context exists**

To avoid weakening `/v1/chat/completions`, use this default in `sanitize_payload`:

```python
block_all_credentials = blocked_credentials is None
blocked = frozenset(blocked_credentials or ())
```

Pass `block_all_credentials` into `_sanitize_text` and define blocked findings as:

```python
blocked = [
    item
    for item in findings
    if item.entity_type == EntityType.API_KEY
    and (block_all_credentials or item.value in blocked_credentials)
]
```

Responses calls will pass a set, even when empty; legacy calls will omit the argument and retain current behavior.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_transformer.py tests/test_vault.py tests/test_privacy_proxy.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/privacy/models.py privacytap/privacy/transformer.py privacytap/privacy/vault.py tests/test_transformer.py tests/test_vault.py
git commit -m "feat: add request-aware credential privacy policy"
```

### Task 2: Incremental SSE parser

**Files:**
- Create: `privacytap/sse.py`
- Create: `tests/test_sse.py`

- [ ] **Step 1: Write failing SSE parser tests**

Create `tests/test_sse.py`:

```python
import json

import pytest

from privacytap.sse import SSEDecodeError, SSEEvent, SSEParser, encode_sse


def feed_chunks(chunks: list[bytes]) -> list[SSEEvent]:
    parser = SSEParser()
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.finish())
    return events


def test_parses_event_split_across_every_byte():
    raw = (
        b"event: response.output_text.delta\r\n"
        b"data: {\"type\":\"response.output_text.delta\","
        b"\"delta\":\"hello\"}\r\n\r\n"
    )
    events = feed_chunks([raw[index:index + 1] for index in range(len(raw))])
    assert len(events) == 1
    assert events[0].event == "response.output_text.delta"
    assert json.loads(events[0].data)["delta"] == "hello"


def test_joins_multiple_data_lines_and_ignores_comments():
    events = feed_chunks(
        [b": keepalive\n", b"event: demo\ndata: first\ndata: second\n\n"]
    )
    assert events == [SSEEvent(event="demo", data="first\nsecond")]


def test_utf8_can_cross_network_chunks():
    raw = "data: 中文\n\n".encode()
    events = feed_chunks([raw[:8], raw[8:9], raw[9:]])
    assert events[0].data == "中文"


def test_finish_rejects_incomplete_frame():
    parser = SSEParser()
    parser.feed(b"data: unfinished")
    with pytest.raises(SSEDecodeError):
        parser.finish()


def test_encode_sse_produces_parseable_frame():
    encoded = encode_sse(SSEEvent(event="demo", data='{"ok":true}'))
    assert feed_chunks([encoded]) == [
        SSEEvent(event="demo", data='{"ok":true}')
    ]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sse.py -q
```

Expected: FAIL with `ModuleNotFoundError: privacytap.sse`.

- [ ] **Step 3: Implement the minimal incremental parser**

Create `privacytap/sse.py`:

```python
from __future__ import annotations

import codecs
from dataclasses import dataclass


class SSEDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SSEEvent:
    event: str | None
    data: str
    event_id: str | None = None
    retry: int | None = None


class SSEParser:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._text = ""

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        try:
            self._text += self._decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise SSEDecodeError("invalid UTF-8 in SSE stream") from exc
        self._text = self._text.replace("\r\n", "\n").replace("\r", "\n")
        events: list[SSEEvent] = []
        while "\n\n" in self._text:
            frame, self._text = self._text.split("\n\n", 1)
            event = self._parse_frame(frame)
            if event is not None:
                events.append(event)
        return events

    def finish(self) -> list[SSEEvent]:
        try:
            self._text += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise SSEDecodeError("invalid UTF-8 in SSE stream") from exc
        if self._text.strip():
            raise SSEDecodeError("incomplete SSE frame")
        return []

    @staticmethod
    def _parse_frame(frame: str) -> SSEEvent | None:
        event_name = None
        event_id = None
        retry = None
        data: list[str] = []
        for line in frame.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "data":
                data.append(value)
            elif field == "id":
                event_id = value
            elif field == "retry":
                try:
                    retry = int(value)
                except ValueError as exc:
                    raise SSEDecodeError("invalid retry field") from exc
        if not data and event_name is None:
            return None
        return SSEEvent(
            event=event_name,
            data="\n".join(data),
            event_id=event_id,
            retry=retry,
        )


def encode_sse(event: SSEEvent) -> bytes:
    lines: list[str] = []
    if event.event is not None:
        lines.append(f"event: {event.event}")
    if event.event_id is not None:
        lines.append(f"id: {event.event_id}")
    if event.retry is not None:
        lines.append(f"retry: {event.retry}")
    for line in event.data.split("\n"):
        lines.append(f"data: {line}")
    return ("\n".join(lines) + "\n\n").encode()
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sse.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/sse.py tests/test_sse.py
git commit -m "feat: add incremental SSE codec"
```

### Task 3: Stateful placeholder restoration for streaming deltas

**Files:**
- Create: `privacytap/privacy/streaming.py`
- Create: `tests/test_streaming_restorer.py`

- [ ] **Step 1: Write failing split-boundary and parallel-stream tests**

Create `tests/test_streaming_restorer.py`:

```python
import pytest

from privacytap.privacy.models import EntityType
from privacytap.privacy.streaming import StreamingRestorer
from privacytap.privacy.vault import RequestVault


@pytest.mark.parametrize("split_at", range(1, len("[EMAIL_1]")))
def test_placeholder_restores_across_every_split(split_at):
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.EMAIL, "alice@example.com"
    )
    restorer = StreamingRestorer(vault)
    output = (
        restorer.feed("text:0", placeholder[:split_at])
        + restorer.feed("text:0", placeholder[split_at:])
        + restorer.finish("text:0")
    )
    assert output == "alice@example.com"


def test_parallel_tool_calls_keep_independent_buffers():
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.STUDENT_ID, "2023123456"
    )
    restorer = StreamingRestorer(vault)
    left = restorer.feed("call:a", placeholder[:5])
    right = restorer.feed("call:b", "safe")
    left += restorer.feed("call:a", placeholder[5:])
    left += restorer.finish("call:a")
    right += restorer.finish("call:b")
    assert left == "2023123456"
    assert right == "safe"


def test_finish_releases_non_placeholder_tail():
    vault = RequestVault()
    vault.get_or_create(EntityType.PHONE, "13800138000")
    restorer = StreamingRestorer(vault)
    assert restorer.feed("text:0", "hello [PH") == "hello "
    assert restorer.finish("text:0") == "[PH"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_streaming_restorer.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement a bounded per-stream suffix buffer**

Create `privacytap/privacy/streaming.py`:

```python
from __future__ import annotations

from privacytap.privacy.vault import RequestVault


class StreamingRestorer:
    def __init__(self, vault: RequestVault) -> None:
        self._vault = vault
        self._buffers: dict[str, str] = {}
        self._max_placeholder_length = max(
            (len(item) for item in vault.placeholders),
            default=0,
        )

    def feed(self, stream_id: str, text: str) -> str:
        combined = self._buffers.get(stream_id, "") + text
        if not self._max_placeholder_length:
            return combined
        keep = min(len(combined), self._max_placeholder_length - 1)
        emit_length = len(combined) - keep
        while emit_length > 0 and self._could_split_placeholder(
            combined[emit_length:]
        ):
            break
        if emit_length == 0:
            self._buffers[stream_id] = combined
            return ""
        emitted = combined[:emit_length]
        tail = combined[emit_length:]
        restored = self._vault.restore_text(emitted)
        restored_tail = self._restore_complete_prefixes(tail)
        self._buffers[stream_id] = restored_tail[1]
        return restored + restored_tail[0]

    def finish(self, stream_id: str) -> str:
        return self._vault.restore_text(self._buffers.pop(stream_id, ""))

    def finish_all(self) -> dict[str, str]:
        return {
            stream_id: self.finish(stream_id)
            for stream_id in tuple(self._buffers)
        }

    def _could_split_placeholder(self, tail: str) -> bool:
        return any(
            placeholder.startswith(tail)
            for placeholder in self._vault.placeholders
        )

    def _restore_complete_prefixes(self, tail: str) -> tuple[str, str]:
        emitted = ""
        pending = tail
        changed = True
        while changed:
            changed = False
            for placeholder in self._vault.placeholders:
                if pending.startswith(placeholder):
                    emitted += self._vault.restore_text(placeholder)
                    pending = pending[len(placeholder):]
                    changed = True
                    break
        return emitted, pending
```

If the first implementation fails a split case, simplify around this invariant:

```python
safe_cut = len(combined)
for suffix_start in range(
    max(0, len(combined) - self._max_placeholder_length + 1),
    len(combined),
):
    suffix = combined[suffix_start:]
    if any(
        placeholder.startswith(suffix)
        for placeholder in self._vault.placeholders
    ):
        safe_cut = suffix_start
        break
emitted = self._vault.restore_text(combined[:safe_cut])
self._buffers[stream_id] = combined[safe_cut:]
return emitted
```

Use the simpler invariant-based implementation as the final version.

- [ ] **Step 4: Run exhaustive tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_streaming_restorer.py -q
```

Expected: PASS for every placeholder split index.

Commit:

```powershell
git add privacytap/privacy/streaming.py tests/test_streaming_restorer.py
git commit -m "feat: restore placeholders across stream boundaries"
```

### Task 4: OpenAI Responses adapter for JSON and SSE

**Files:**
- Create: `privacytap/responses.py`
- Create: `tests/test_responses_proxy.py`
- Modify: `privacytap/proxy.py`

- [ ] **Step 1: Write failing non-streaming Responses integration test**

Create `tests/test_responses_proxy.py` with shared upstream setup and:

```python
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
                "output": [{
                    "type": "message",
                    "content": [{
                        "type": "output_text",
                        "text": "联系 [PHONE_1]",
                    }],
                }],
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
    try:
        async with ClientSession() as session:
            response = await session.post(
                f"http://127.0.0.1:{proxy.bound_port}/v1/responses",
                headers={
                    "Authorization": "Bearer sk-proj-currenttransportkey123456"
                },
                json={
                    "model": "gpt-5.4",
                    "input": "联系 13800138000",
                    "stream": False,
                },
            )
            body = await response.json()
        assert response.status == 200
        assert captured["body"]["input"] == "联系 [PHONE_1]"
        assert body["output"][0]["content"][0]["text"] == "联系 13800138000"
        assert "13800138000" not in json.dumps(events, ensure_ascii=False)
        assert "sk-proj-currenttransportkey123456" not in json.dumps(events)
    finally:
        await proxy.stop()
        await runner.cleanup()
```

- [ ] **Step 2: Run focused test and verify 404 failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_responses_proxy.py::test_responses_json_anonymizes_upstream_and_restores_client -q
```

Expected: FAIL because `/v1/responses` is not registered.

- [ ] **Step 3: Add adapter result types and safe Header filtering**

Create `privacytap/responses.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

import aiohttp


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "content-encoding",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def forward_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def response_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS | {"content-type"}
    }


@dataclass(slots=True)
class UpstreamResponse:
    response: aiohttp.ClientResponse
    session: aiohttp.ClientSession

    async def close(self) -> None:
        self.response.release()
        await self.session.close()


class OpenAIResponsesAdapter:
    def __init__(
        self,
        upstream_base_url: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._url = (
            f"{upstream_base_url.rstrip('/')}/v1/responses"
        )
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def post(self, headers, payload: dict) -> UpstreamResponse:
        session = aiohttp.ClientSession(timeout=self._timeout)
        try:
            response = await session.post(
                self._url,
                headers=forward_headers(headers),
                json=payload,
            )
        except Exception:
            await session.close()
            raise
        return UpstreamResponse(response=response, session=session)
```

- [ ] **Step 4: Register the route and implement non-streaming response handling**

In `privacytap/proxy.py`:

```python
from privacytap.responses import (
    OpenAIResponsesAdapter,
    response_headers,
)


def _bearer_credential(request: web.Request) -> set[str]:
    value = request.headers.get("Authorization", "")
    scheme, separator, credential = value.partition(" ")
    if separator and scheme.lower() == "bearer" and credential:
        return {credential}
    return set()
```

In `__init__`:

```python
self.responses = OpenAIResponsesAdapter(self.upstream_base_url)
self.app.router.add_post("/v1/responses", self.handle_responses)
```

Add:

```python
async def handle_responses(self, request: web.Request) -> web.StreamResponse:
    try:
        original_payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return self._error(
            400, "invalid_json", "Request body must be a JSON object"
        )
    if not isinstance(original_payload, dict):
        return self._error(
            400, "invalid_json", "Request body must be a JSON object"
        )
    try:
        sanitized = sanitize_payload(
            original_payload,
            blocked_credentials=_bearer_credential(request),
        )
    except SensitiveCredentialError as exc:
        return self._credential_error(exc)

    upstream = await self.responses.post(
        request.headers, sanitized.payload
    )
    try:
        content_type = upstream.response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            return await self._stream_responses(
                request, upstream, sanitized
            )
        raw = await upstream.response.read()
        if "application/json" not in content_type:
            return web.Response(
                status=upstream.response.status,
                body=raw,
                headers=response_headers(upstream.response.headers),
            )
        safe_response = json.loads(raw)
        self._emit_safe_event(
            self._build_responses_event(sanitized, safe_response)
        )
        return web.json_response(
            restore_payload(safe_response, sanitized.vault),
            status=upstream.response.status,
            headers=response_headers(upstream.response.headers),
        )
    finally:
        await upstream.close()
```

Add safe callback helpers that catch exporter exceptions and a Responses usage calculation:

```python
tokens = int(usage.get("total_tokens") or (
    int(usage.get("input_tokens") or 0)
    + int(usage.get("output_tokens") or 0)
))
```

- [ ] **Step 5: Run JSON test and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_responses_proxy.py::test_responses_json_anonymizes_upstream_and_restores_client -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/responses.py privacytap/proxy.py tests/test_responses_proxy.py
git commit -m "feat: proxy non-streaming Responses API calls"
```

### Task 5: Responses SSE text and function-call restoration

**Files:**
- Modify: `privacytap/responses.py`
- Modify: `privacytap/proxy.py`
- Modify: `tests/test_responses_proxy.py`
- Create: `tests/test_codex_contract.py`

- [ ] **Step 1: Write failing streaming text and tool-call tests**

Add an SSE helper to `tests/test_responses_proxy.py`:

```python
async def write_events(response, events):
    await response.prepare(events["request"])
    for event_name, payload in events["items"]:
        frame = (
            f"event: {event_name}\n"
            f"data: {json.dumps(payload)}\n\n"
        ).encode()
        for byte in frame:
            await response.write(bytes([byte]))
    await response.write_eof()
    return response
```

Add a test whose upstream emits:

```python
items = [
    (
        "response.output_text.delta",
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "联系 [PHO",
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
        },
    ),
    (
        "response.function_call_arguments.delta",
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "call_1",
            "output_index": 1,
            "delta": "{\"path\":\"[EMAIL_1]\"}",
        },
    ),
    (
        "response.completed",
        {
            "type": "response.completed",
            "response": {
                "id": "resp_demo",
                "status": "completed",
                "usage": {"input_tokens": 4, "output_tokens": 4},
            },
        },
    ),
]
```

Parse the client response with `SSEParser` and assert:

```python
assert text_deltas == ["联系 ", "13800138000"]
assert tool_deltas == ['{"path":"alice@example.com"}']
assert "13800138000" not in json.dumps(events, ensure_ascii=False)
assert "alice@example.com" not in json.dumps(events, ensure_ascii=False)
```

Create `tests/test_codex_contract.py` and assert that event names, JSON `type`,
`item_id`, indexes, and completion event are preserved byte-semantically except
for restored delta content.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_responses_proxy.py tests/test_codex_contract.py -q
```

Expected: FAIL because `_stream_responses` is not implemented.

- [ ] **Step 3: Implement event transformation**

In `privacytap/responses.py` add:

```python
import json

from privacytap.privacy.streaming import StreamingRestorer
from privacytap.sse import SSEDecodeError, SSEEvent


def stream_key(payload: dict) -> str | None:
    event_type = payload.get("type")
    if event_type == "response.output_text.delta":
        return (
            f"text:{payload.get('item_id', '')}:"
            f"{payload.get('content_index', 0)}"
        )
    if event_type == "response.function_call_arguments.delta":
        return f"call:{payload.get('item_id', payload.get('output_index', 0))}"
    return None


def restore_event(
    event: SSEEvent,
    restorer: StreamingRestorer,
) -> SSEEvent:
    try:
        payload = json.loads(event.data)
    except json.JSONDecodeError as exc:
        raise SSEDecodeError("SSE data is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SSEDecodeError("SSE data must be a JSON object")
    key = stream_key(payload)
    if key is not None and isinstance(payload.get("delta"), str):
        payload["delta"] = restorer.feed(key, payload["delta"])
    return SSEEvent(
        event=event.event,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        event_id=event.event_id,
        retry=event.retry,
    )
```

Before a terminal event, flush pending text into an additional event of the same
delta type only when non-empty. For normal placeholder completion the buffers
must already be empty. Treat non-empty unresolved tails at `response.completed`
as literal text and emit them before completion.

- [ ] **Step 4: Implement streaming proxy with safe upstream capture**

In `privacytap/proxy.py`, `_stream_responses` must:

```python
client = web.StreamResponse(
    status=upstream.response.status,
    headers={
        **response_headers(upstream.response.headers),
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
    },
)
await client.prepare(request)
parser = SSEParser()
restorer = StreamingRestorer(sanitized.vault)
safe_events: list[dict] = []
try:
    async for chunk in upstream.response.content.iter_any():
        for event in parser.feed(chunk):
            safe_events.append({
                "event": event.event,
                "data": json.loads(event.data),
            })
            restored = restore_event(event, restorer)
            await client.write(encode_sse(restored))
    parser.finish()
    await client.write_eof()
finally:
    self._emit_safe_event(
        self._build_responses_event(sanitized, safe_events)
    )
return client
```

Refine this minimal version so that:

- `ConnectionResetError` and `asyncio.CancelledError` cancel upstream work.
- Invalid SSE raises before any raw unprocessed chunk is written.
- Exporter exceptions are swallowed.
- Captured safe events remain upstream values, never restored values.
- Upstream non-2xx SSE streams preserve status.

- [ ] **Step 5: Run streaming and contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sse.py tests/test_streaming_restorer.py tests/test_responses_proxy.py tests/test_codex_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add privacytap/responses.py privacytap/proxy.py tests/test_responses_proxy.py tests/test_codex_contract.py
git commit -m "feat: restore Responses SSE text and tool calls"
```

### Task 6: Error mapping, disconnect cleanup, and security invariants

**Files:**
- Modify: `privacytap/proxy.py`
- Modify: `privacytap/responses.py`
- Modify: `tests/test_responses_proxy.py`
- Modify: `tests/test_privacy_invariants.py`

- [ ] **Step 1: Write failing error-path tests**

Add tests for:

```python
@pytest.mark.asyncio
async def test_responses_rejects_current_header_key_in_prompt(...):
    # Header contains Bearer <key>; input contains the same raw key.
    # Assert HTTP 422, no upstream call, and response body excludes key.


@pytest.mark.asyncio
async def test_responses_maps_connect_error_to_502(...):
    # Point upstream to an unused port.
    # Assert code == "upstream_unavailable".


@pytest.mark.asyncio
async def test_responses_maps_timeout_to_504(...):
    # Adapter timeout 0.01s; upstream sleeps.
    # Assert code == "upstream_timeout".


@pytest.mark.asyncio
async def test_invalid_upstream_sse_does_not_forward_raw_secret(...):
    # Upstream sends malformed/incomplete frame containing raw-looking data.
    # Assert stream terminates and archives contain neither transport Key
    # nor client secrets.
```

Extend `tests/test_privacy_invariants.py` with 50 concurrent `/v1/responses`
requests. Each upstream request must contain `[PHONE_1]`, each restored client
response must contain its own phone, and no event may contain any original phone.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_responses_proxy.py tests/test_privacy_invariants.py -q
```

Expected: FAIL on missing timeout/error mapping and Responses concurrency setup.

- [ ] **Step 3: Add explicit exception mapping**

In `handle_responses`:

```python
except asyncio.TimeoutError:
    return self._error(
        504, "upstream_timeout", "Upstream model API timed out"
    )
except aiohttp.ClientError:
    return self._error(
        502,
        "upstream_unavailable",
        "Unable to reach upstream model API",
    )
```

Never interpolate exception text into client responses because URLs or Headers
may appear in third-party exception messages.

- [ ] **Step 4: Ensure request-scoped cleanup**

Use `try/finally` around every `UpstreamResponse` and streaming loop:

```python
upstream = None
try:
    upstream = await self.responses.post(...)
    ...
finally:
    if upstream is not None:
        await upstream.close()
```

No Vault may be stored on `PrivacyProxyServer`, adapter instances, exporters, or
module globals.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_responses_proxy.py tests/test_privacy_invariants.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/proxy.py privacytap/responses.py tests/test_responses_proxy.py tests/test_privacy_invariants.py
git commit -m "test: enforce Responses privacy invariants"
```

### Task 7: CLI, configuration, and offline Responses demo

**Files:**
- Modify: `privacytap/cli.py`
- Modify: `tests/test_cli.py`
- Create: `examples/mock_responses_upstream.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing CLI tests**

Add to `tests/test_cli.py`:

```python
def test_start_help_exposes_openai_provider_and_timeout():
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    assert "--provider" in result.output
    assert "--upstream-timeout" in result.output
    assert "openai" in result.output


def test_openai_upstream_has_a_safe_default():
    from privacytap.cli import DEFAULT_OPENAI_BASE_URL
    assert DEFAULT_OPENAI_BASE_URL == "https://api.openai.com"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q
```

Expected: FAIL because new options and constant do not exist.

- [ ] **Step 3: Add CLI options without breaking existing invocations**

In `privacytap/cli.py`:

```python
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"


@click.option(
    "--provider",
    type=click.Choice(["openai"]),
    default="openai",
    show_default=True,
)
@click.option(
    "--upstream-base-url",
    envvar="PRIVACYTAP_UPSTREAM_BASE_URL",
    default=DEFAULT_OPENAI_BASE_URL,
    show_default=True,
)
@click.option(
    "--upstream-timeout",
    envvar="PRIVACYTAP_UPSTREAM_TIMEOUT",
    default=300.0,
    show_default=True,
    type=click.FloatRange(min=0.1),
)
```

Pass timeout into `PrivacyProxyServer`, then print:

```python
click.echo("Codex endpoint: /v1/responses (JSON + SSE)")
click.echo("Legacy endpoint: /v1/chat/completions (non-streaming)")
```

Do not read or print `OPENAI_API_KEY` in PrivacyTap CLI.

- [ ] **Step 4: Add an offline mock Responses upstream**

Create `examples/mock_responses_upstream.py` with aiohttp:

```python
async def responses(request: web.Request) -> web.StreamResponse:
    payload = await request.json()
    text = json.dumps(payload, ensure_ascii=False)
    response = web.StreamResponse(
        headers={"Content-Type": "text/event-stream"}
    )
    await response.prepare(request)
    events = [
        {
            "type": "response.output_text.delta",
            "item_id": "msg_demo",
            "output_index": 0,
            "content_index": 0,
            "delta": f"上游实际收到：{text}",
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp_demo",
                "status": "completed",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
    ]
    for event in events:
        await response.write(
            encode_sse(SSEEvent(event=event["type"], data=json.dumps(event)))
        )
    await response.write_eof()
    return response
```

Run on `127.0.0.1:18080` and print the received sanitized payload to console.

- [ ] **Step 5: Update `.env.example`**

Add:

```dotenv
OPENAI_API_KEY=sk-your-openai-api-key
PRIVACYTAP_UPSTREAM_BASE_URL=https://api.openai.com
PRIVACYTAP_UPSTREAM_TIMEOUT=300
```

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -q
```

Expected: PASS.

Commit:

```powershell
git add privacytap/cli.py tests/test_cli.py examples/mock_responses_upstream.py .env.example
git commit -m "feat: expose Codex Responses proxy from CLI"
```

### Task 8: Documentation and measurable evidence

**Files:**
- Modify: `README.md`
- Modify: `docs/experiment.md`
- Modify: `scripts/evaluate_privacy.py`
- Modify: `tests/test_standalone_contract.py`

- [ ] **Step 1: Add a failing standalone documentation contract**

In `tests/test_standalone_contract.py` add:

```python
def test_readme_documents_real_codex_responses_setup():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert 'wire_api = "responses"' in readme
    assert "codex --profile privacytap" in readme
    assert "OPENAI_API_KEY" in readme
    assert "/v1/responses" in readme
```

- [ ] **Step 2: Run the contract test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standalone_contract.py -q
```

Expected: FAIL because README lacks Codex setup.

- [ ] **Step 3: Document exact Codex setup**

Add to `README.md`:

```toml
[profiles.privacytap]
model = "gpt-5.4"
model_provider = "privacytap"

[model_providers.privacytap]
name = "PrivacyTap"
base_url = "http://127.0.0.1:8080/v1"
wire_api = "responses"
env_key = "OPENAI_API_KEY"
```

Add exact commands:

```powershell
$env:OPENAI_API_KEY="sk-..."
.\.venv\Scripts\privacytap.exe start --provider openai
codex --profile privacytap
```

Clearly state that Provider config belongs in user-level
`$HOME\.codex\config.toml`; project-level `.codex/config.toml` cannot override
provider settings. Document that DeepSeek direct Responses support is not part
of this release.

- [ ] **Step 4: Extend the evaluation script**

Add a benchmark that:

1. Creates a Vault with all supported entity types.
2. Splits every placeholder at every character boundary.
3. Measures `StreamingRestorer.feed` and `finish`.
4. Prints restore correctness, secret leakage count, and P95 latency.

Expected output fields:

```text
Streaming cases: <n>
Streaming restore accuracy: 1.0000
Raw secret leakage count: 0
Streaming transform P95: <20.00 ms
```

- [ ] **Step 5: Document the two-evidence experiment**

In `docs/experiment.md`, separate:

- Controlled upstream: proves exact sanitized bytes left PrivacyTap.
- Real OpenAI/Codex: proves Responses/SSE/tool compatibility.
- Archive scan: proves logs contain zero raw secrets.
- Ten-run task table: records Codex success count and failure reason.

- [ ] **Step 6: Run docs contract and evaluation**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_standalone_contract.py -q
.\.venv\Scripts\python.exe scripts/evaluate_privacy.py
```

Expected: tests PASS; accuracy `1.0000`; leakage count `0`.

- [ ] **Step 7: Commit**

```powershell
git add README.md docs/experiment.md scripts/evaluate_privacy.py tests/test_standalone_contract.py
git commit -m "docs: add real Codex privacy proxy demo"
```

### Task 9: Full verification and real Codex smoke test

**Files:**
- Modify only if verification exposes a defect.

- [ ] **Step 1: Run formatting-independent diff checks**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 2: Run complete test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 3: Enforce coverage**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=privacytap --cov-report=term-missing --cov-fail-under=90 -q
```

Expected: coverage at least 90%, all tests PASS.

- [ ] **Step 4: Run privacy and latency evaluation**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_privacy.py
```

Expected:

- Precision/Recall/F1 remain `1.0`.
- Streaming restore accuracy is `1.0`.
- Raw secret leakage count is `0`.
- Transform P95 is below `20 ms`.

- [ ] **Step 5: Run the offline SSE demo**

Terminal 1:

```powershell
.\.venv\Scripts\python.exe examples\mock_responses_upstream.py
```

Terminal 2:

```powershell
.\.venv\Scripts\privacytap.exe start `
  --provider openai `
  --upstream-base-url http://127.0.0.1:18080
```

Send an SSE request containing phone and email. Expected:

- Mock upstream console shows placeholders only.
- Client stream shows original values.
- `privacytap-traces` contains placeholders only.

- [ ] **Step 6: Run the real Codex smoke test when `OPENAI_API_KEY` is available**

Do not print the Key. Start PrivacyTap:

```powershell
.\.venv\Scripts\privacytap.exe start --provider openai
```

Run:

```powershell
codex --profile privacytap
```

Use:

```text
请记住邮箱 test2026@example.com 和手机号 13800138000。
在临时目录创建 contact.txt，写入上述信息，然后读取并报告内容。
```

Expected:

- Codex completes the tool call.
- Created file contains original values.
- Trace files contain neither original value nor API Key.

If no valid Key is available, record the real smoke test as externally blocked;
do not substitute a fake success. Offline protocol tests remain required and
must pass.

- [ ] **Step 7: Inspect repository status and commit final fixes**

Run:

```powershell
git status --short
git log -8 --oneline
```

Expected: only intended files changed and no generated traces, coverage HTML,
Keys, or user-level Codex config are staged.

Commit any verification-only fixes with:

```powershell
git add <only-intended-files>
git commit -m "fix: harden Codex Responses integration"
```
