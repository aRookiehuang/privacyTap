from privacytap.exporters import CompositeExporter


class RecordingExporter:
    def __init__(self, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def export(self, event: dict) -> None:
        if self.fail:
            raise RuntimeError("export failed")
        self.events.append(event)


def test_composite_exporter_continues_after_optional_exporter_failure():
    failed = RecordingExporter(fail=True)
    working = RecordingExporter()
    event = {"request": {"messages": [{"content": "[PHONE_1]"}]}}

    CompositeExporter([failed, working]).export(event)

    assert working.events == [event]
