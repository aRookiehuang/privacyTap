import json

from privacytap.privacy.models import EntityType
from privacytap.privacy.vault import RequestVault
from privacytap.responses import ResponsesEventRestorer
from privacytap.sse import SSEEvent


def test_codex_event_metadata_is_preserved_while_delta_is_restored():
    vault = RequestVault()
    vault.get_or_create(EntityType.EMAIL, "alice@example.com")
    restorer = ResponsesEventRestorer(vault)
    source = {
        "type": "response.function_call_arguments.delta",
        "item_id": "call_1",
        "output_index": 3,
        "sequence_number": 9,
        "delta": '{"email":"[EMAIL_1]"}',
    }
    transformed = restorer.transform(
        SSEEvent(
            event=source["type"],
            event_id="event-9",
            retry=500,
            data=json.dumps(source),
        )
    )
    assert len(transformed) == 1
    event = transformed[0]
    payload = json.loads(event.data)
    assert event.event == source["type"]
    assert event.event_id == "event-9"
    assert event.retry == 500
    assert payload == {
        **source,
        "delta": '{"email":"alice@example.com"}',
    }
