import pytest

from tokentap.privacy.models import SensitiveCredentialError
from tokentap.privacy.transformer import restore_payload, sanitize_payload


def test_sanitizes_nested_openai_payload_and_restores_response():
    source = {
        "model": "demo-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "联系 13812345678 或 alice@example.com，学号：2023123456",
                    }
                ],
            }
        ],
    }
    result = sanitize_payload(source)
    text = result.payload["messages"][0]["content"][0]["text"]
    assert text == "联系 [PHONE_1] 或 [EMAIL_1]，学号：[STUDENT_ID_1]"
    assert "13812345678" not in repr(result.payload)
    assert "alice@example.com" not in repr(result.payload)

    restored = restore_payload(
        {"choices": [{"message": {"content": "发送至 [PHONE_1] 与 [EMAIL_1]"}}]},
        result.vault,
    )
    assert (
        restored["choices"][0]["message"]["content"]
        == "发送至 13812345678 与 alice@example.com"
    )


def test_input_payload_is_not_mutated():
    source = {"messages": [{"role": "user", "content": "电话 13812345678"}]}
    sanitize_payload(source)
    assert source["messages"][0]["content"] == "电话 13812345678"


def test_api_key_blocks_before_result_is_returned():
    source = {
        "messages": [
            {"role": "user", "content": "请检查 sk-proj-abcdefghijklmnopqrstuv"}
        ]
    }
    with pytest.raises(SensitiveCredentialError):
        sanitize_payload(source)


def test_non_text_values_are_preserved():
    source = {
        "model": "demo-model",
        "temperature": 0.2,
        "stream": False,
        "messages": [{"role": "user", "content": "hello"}],
    }
    result = sanitize_payload(source)
    assert result.payload == source
