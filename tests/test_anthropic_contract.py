import json

import pytest

from privacytap.anthropic import (
    AnthropicEventRestorer,
    AnthropicMessagesAdapter,
    forward_anthropic_headers,
)
from privacytap.privacy.models import EntityType
from privacytap.privacy.vault import RequestVault
from privacytap.sse import SSEDecodeError, SSEEvent


def test_anthropic_headers_preserve_protocol_and_auth_headers():
    result = forward_anthropic_headers(
        {
            "Host": "127.0.0.1:8080",
            "Content-Length": "10",
            "X-Api-Key": "sk-ant-demo",
            "Anthropic-Version": "2023-06-01",
            "Anthropic-Beta": "prompt-caching-2024-07-31",
            "X-Claude-Code-Session-Id": "session-1",
            "User-Agent": "claude-code/2.1.177",
        }
    )
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


def delta_event(index: int, delta: dict) -> SSEEvent:
    return SSEEvent(
        event="content_block_delta",
        data=json.dumps(
            {
                "type": "content_block_delta",
                "index": index,
                "delta": delta,
            }
        ),
    )


@pytest.mark.parametrize("split_at", range(1, len("[EMAIL_1]")))
def test_anthropic_text_delta_restores_every_split(split_at):
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.EMAIL, "alice@example.com"
    )
    restorer = AnthropicEventRestorer(vault)
    output = []
    for text in (placeholder[:split_at], placeholder[split_at:]):
        output.extend(
            restorer.transform(
                delta_event(
                    0, {"type": "text_delta", "text": text}
                )
            )
        )
    output.extend(restorer.finish())
    assert "".join(
        json.loads(event.data)["delta"]["text"]
        for event in output
    ) == "alice@example.com"


def test_anthropic_tool_partial_json_restores_and_isolates_indexes():
    vault = RequestVault()
    placeholder = vault.get_or_create(
        EntityType.STUDENT_ID, "2023123456"
    )
    restorer = AnthropicEventRestorer(vault)
    left = restorer.transform(
        delta_event(
            1,
            {
                "type": "input_json_delta",
                "partial_json": f'{{"id":"{placeholder[:5]}',
            },
        )
    )
    right = restorer.transform(
        delta_event(
            2,
            {
                "type": "input_json_delta",
                "partial_json": '{"safe":true}',
            },
        )
    )
    left += restorer.transform(
        delta_event(
            1,
            {
                "type": "input_json_delta",
                "partial_json": f'{placeholder[5:]}"}}',
            },
        )
    )
    assert "".join(
        json.loads(event.data)["delta"]["partial_json"]
        for event in left
    ) == '{"id":"2023123456"}'
    assert json.loads(right[0].data)["delta"]["partial_json"] == (
        '{"safe":true}'
    )


def test_content_block_stop_flushes_pending_text_before_stop():
    vault = RequestVault()
    vault.get_or_create(EntityType.EMAIL, "alice@example.com")
    restorer = AnthropicEventRestorer(vault)
    initial = restorer.transform(
        delta_event(0, {"type": "text_delta", "text": "[EMAI"})
    )
    assert json.loads(initial[0].data)["delta"]["text"] == ""
    stop = SSEEvent(
        event="content_block_stop",
        data=json.dumps({"type": "content_block_stop", "index": 0}),
    )
    output = restorer.transform(stop)
    assert len(output) == 2
    assert json.loads(output[0].data)["delta"]["text"] == "[EMAI"
    assert json.loads(output[1].data)["type"] == "content_block_stop"


def test_signature_delta_is_unchanged():
    restorer = AnthropicEventRestorer(RequestVault())
    payload = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {
            "type": "signature_delta",
            "signature": "[EMAIL_1]-signed",
        },
    }
    output = restorer.transform(
        SSEEvent(
            event="content_block_delta",
            data=json.dumps(payload),
        )
    )
    assert json.loads(output[0].data) == payload


def test_ping_and_unknown_event_are_preserved():
    vault = RequestVault()
    vault.get_or_create(EntityType.EMAIL, "alice@example.com")
    restorer = AnthropicEventRestorer(vault)
    ping = {"type": "ping"}
    assert json.loads(
        restorer.transform(
            SSEEvent(event="ping", data=json.dumps(ping))
        )[0].data
    ) == ping
    unknown = {"type": "future_event", "value": "[EMAIL_1]"}
    restored = restorer.transform(
        SSEEvent(event="future_event", data=json.dumps(unknown))
    )
    assert json.loads(restored[0].data)["value"] == "alice@example.com"


@pytest.mark.parametrize("data", ["not-json", "[]"])
def test_invalid_anthropic_event_is_rejected(data):
    restorer = AnthropicEventRestorer(RequestVault())
    with pytest.raises(SSEDecodeError):
        restorer.transform(SSEEvent(event="demo", data=data))
