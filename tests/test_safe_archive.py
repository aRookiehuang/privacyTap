import json

from privacytap.archive import FileExporter, save_safe_event


def test_archive_contains_only_sanitized_data(tmp_path):
    event = {
        "timestamp": "2026-06-18T12:00:00",
        "provider": "openai-compatible",
        "model": "demo-model",
        "tokens": 12,
        "request": {"messages": [{"role": "user", "content": "[PHONE_1]"}]},
        "response": {
            "choices": [{"message": {"content": "联系 [PHONE_1]"}}]
        },
        "privacy": {"detected": {"PHONE": 1}, "processing_ms": 0.5},
    }
    files = save_safe_event(event, tmp_path)
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in files
    )
    assert "[PHONE_1]" in combined
    assert "13812345678" not in combined
    json_file = next(path for path in files if path.suffix == ".json")
    parsed = json.loads(json_file.read_text(encoding="utf-8"))
    assert parsed["privacy"]["detected"]["PHONE"] == 1


def test_file_exporter_delegates_to_safe_archive(tmp_path):
    event = {
        "timestamp": "2026-06-18T12:00:00",
        "provider": "openai-compatible",
        "model": "demo-model",
        "tokens": 0,
        "request": {},
        "response": {},
        "privacy": {"detected": {}, "processing_ms": 0.1},
    }
    FileExporter(tmp_path).export(event)
    assert len(list(tmp_path.glob("*.json"))) == 1
