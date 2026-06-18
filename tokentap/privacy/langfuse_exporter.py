from __future__ import annotations

from typing import Any


class LangfuseSafeExporter:
    """Export only the already-sanitized privacy event to Langfuse."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from langfuse import get_client

            client = get_client()
        self.client = client

    def export(self, event: dict) -> None:
        observation = self.client.start_observation(
            name="privacytap-chat-completion",
            as_type="generation",
            model=event["model"],
            input=event["request"],
            metadata={
                "provider": event["provider"],
                "privacy_detected": str(
                    event["privacy"]["detected"]
                ),
                "privacy_processing_ms": str(
                    event["privacy"]["processing_ms"]
                ),
                "placeholder_count": str(
                    event["privacy"]["placeholder_count"]
                ),
            },
        )
        try:
            observation.update(
                output=event["response"],
                usage_details={"total_tokens": event["tokens"]},
            )
        finally:
            observation.end()
