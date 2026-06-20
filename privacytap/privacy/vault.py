from collections import defaultdict

from privacytap.privacy.models import EntityType


class RequestVault:
    """Request-scoped in-memory mapping that must never be serialized."""

    def __init__(self) -> None:
        self._forward: dict[tuple[EntityType, str], str] = {}
        self._reverse: dict[str, str] = {}
        self._counters: dict[EntityType, int] = defaultdict(int)

    def get_or_create(self, entity_type: EntityType, value: str) -> str:
        key = (entity_type, value)
        existing = self._forward.get(key)
        if existing is not None:
            return existing
        self._counters[entity_type] += 1
        placeholder = f"[{entity_type.value}_{self._counters[entity_type]}]"
        self._forward[key] = placeholder
        self._reverse[placeholder] = value
        return placeholder

    def restore_text(self, text: str) -> str:
        restored = text
        for placeholder in sorted(self._reverse, key=len, reverse=True):
            restored = restored.replace(placeholder, self._reverse[placeholder])
        return restored

    @property
    def placeholder_count(self) -> int:
        return len(self._reverse)

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(self._reverse)
