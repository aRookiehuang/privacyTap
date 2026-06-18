from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    PHONE = "PHONE"
    CN_ID = "CN_ID"
    EMAIL = "EMAIL"
    BANK_CARD = "BANK_CARD"
    STUDENT_ID = "STUDENT_ID"
    API_KEY = "API_KEY"


@dataclass(frozen=True, slots=True)
class Finding:
    entity_type: EntityType
    start: int
    end: int
    value: str
    confidence: float = 1.0


@dataclass(slots=True)
class TransformStats:
    detected: dict[str, int] = field(default_factory=dict)
    processing_ms: float = 0.0


@dataclass(slots=True)
class SanitizedPayload:
    payload: dict[str, Any]
    vault: "RequestVault"
    findings: list[Finding]
    stats: TransformStats


class SensitiveCredentialError(ValueError):
    def __init__(self, findings: list[Finding]):
        super().__init__("Request blocked because API credentials were detected")
        self.findings = findings
