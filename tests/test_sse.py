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
    events = feed_chunks(
        [raw[index : index + 1] for index in range(len(raw))]
    )
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


def test_event_id_and_retry_round_trip():
    event = SSEEvent(
        event="demo",
        data="first\nsecond",
        event_id="event-1",
        retry=500,
    )
    assert feed_chunks([encode_sse(event)]) == [event]


def test_invalid_retry_is_rejected():
    parser = SSEParser()
    with pytest.raises(SSEDecodeError, match="invalid retry"):
        parser.feed(b"retry: later\ndata: demo\n\n")


def test_comment_only_frame_is_ignored():
    assert feed_chunks([b": keepalive\n\n"]) == []


def test_invalid_utf8_is_rejected_during_feed():
    parser = SSEParser()
    with pytest.raises(SSEDecodeError, match="invalid UTF-8"):
        parser.feed(b"\xff")


def test_incomplete_utf8_is_rejected_during_finish():
    parser = SSEParser()
    parser.feed(b"\xe4")
    with pytest.raises(SSEDecodeError, match="invalid UTF-8"):
        parser.finish()
