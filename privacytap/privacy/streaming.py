from __future__ import annotations

from privacytap.privacy.vault import RequestVault


class StreamingRestorer:
    """Restore placeholders that may span multiple streamed deltas."""

    def __init__(self, vault: RequestVault) -> None:
        self._vault = vault
        self._buffers: dict[str, str] = {}
        self._placeholders = vault.placeholders
        self._max_placeholder_length = max(
            (len(item) for item in self._placeholders),
            default=0,
        )

    def feed(self, stream_id: str, text: str) -> str:
        combined = self._buffers.get(stream_id, "") + text
        if not self._placeholders:
            self._buffers.pop(stream_id, None)
            return combined

        safe_cut = len(combined)
        first_possible_suffix = max(
            0, len(combined) - self._max_placeholder_length + 1
        )
        for suffix_start in range(first_possible_suffix, len(combined)):
            suffix = combined[suffix_start:]
            if any(
                placeholder.startswith(suffix)
                for placeholder in self._placeholders
            ):
                safe_cut = suffix_start
                break

        emitted = self._vault.restore_text(combined[:safe_cut])
        pending = combined[safe_cut:]
        if pending:
            self._buffers[stream_id] = pending
        else:
            self._buffers.pop(stream_id, None)
        return emitted

    def finish(self, stream_id: str) -> str:
        return self._vault.restore_text(self._buffers.pop(stream_id, ""))

    def finish_all(self) -> dict[str, str]:
        return {
            stream_id: self.finish(stream_id)
            for stream_id in tuple(self._buffers)
        }
