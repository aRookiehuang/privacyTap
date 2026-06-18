from unittest.mock import MagicMock

from tokentap.privacy.langfuse_exporter import LangfuseSafeExporter


def test_exporter_sends_only_safe_event():
    client = MagicMock()
    observation = MagicMock()
    client.start_observation.return_value = observation
    exporter = LangfuseSafeExporter(client=client)
    event = {
        "timestamp": "2026-06-18T12:00:00",
        "provider": "openai-compatible",
        "model": "demo-model",
        "tokens": 18,
        "request": {"messages": [{"content": "[PHONE_1]"}]},
        "response": {
            "choices": [{"message": {"content": "[PHONE_1]"}}]
        },
        "privacy": {
            "detected": {"PHONE": 1},
            "processing_ms": 0.5,
            "placeholder_count": 1,
        },
    }
    exporter.export(event)
    kwargs = client.start_observation.call_args.kwargs
    assert kwargs["as_type"] == "generation"
    assert kwargs["input"] == event["request"]
    assert "13812345678" not in repr(kwargs)
    observation.update.assert_called_once_with(
        output=event["response"],
        usage_details={"total_tokens": 18},
    )
    observation.end.assert_called_once()
