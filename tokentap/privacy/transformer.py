from __future__ import annotations

import copy
import time
from collections import Counter
from typing import Any

from tokentap.privacy.detectors import detect_sensitive
from tokentap.privacy.models import (
    EntityType,
    Finding,
    SanitizedPayload,
    SensitiveCredentialError,
    TransformStats,
)
from tokentap.privacy.vault import RequestVault


def _sanitize_text(
    text: str,
    vault: RequestVault,
    all_findings: list[Finding],
) -> str:
    findings = detect_sensitive(text)
    credentials = [
        item for item in findings if item.entity_type == EntityType.API_KEY
    ]
    if credentials:
        raise SensitiveCredentialError(credentials)
    replaced = text
    for finding in reversed(findings):
        placeholder = vault.get_or_create(finding.entity_type, finding.value)
        replaced = (
            replaced[: finding.start] + placeholder + replaced[finding.end :]
        )
    all_findings.extend(findings)
    return replaced


def _walk_sanitize(
    value: Any, vault: RequestVault, findings: list[Finding]
) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, vault, findings)
    if isinstance(value, list):
        return [_walk_sanitize(item, vault, findings) for item in value]
    if isinstance(value, dict):
        return {
            key: _walk_sanitize(item, vault, findings)
            for key, item in value.items()
        }
    return value


def _walk_restore(value: Any, vault: RequestVault) -> Any:
    if isinstance(value, str):
        return vault.restore_text(value)
    if isinstance(value, list):
        return [_walk_restore(item, vault) for item in value]
    if isinstance(value, dict):
        return {key: _walk_restore(item, vault) for key, item in value.items()}
    return value


def sanitize_payload(payload: dict[str, Any]) -> SanitizedPayload:
    started = time.perf_counter()
    vault = RequestVault()
    findings: list[Finding] = []
    safe_payload = _walk_sanitize(copy.deepcopy(payload), vault, findings)
    counts = Counter(item.entity_type.value for item in findings)
    return SanitizedPayload(
        payload=safe_payload,
        vault=vault,
        findings=findings,
        stats=TransformStats(
            detected=dict(counts),
            processing_ms=(time.perf_counter() - started) * 1000,
        ),
    )


def restore_payload(
    payload: dict[str, Any], vault: RequestVault
) -> dict[str, Any]:
    return _walk_restore(copy.deepcopy(payload), vault)
