from __future__ import annotations

import copy
import time
from collections import Counter
from typing import Any

from privacytap.privacy.detectors import detect_sensitive
from privacytap.privacy.models import (
    EntityType,
    Finding,
    SanitizedPayload,
    SensitiveCredentialError,
    TransformStats,
)
from privacytap.privacy.vault import RequestVault


def _sanitize_text(
    text: str,
    vault: RequestVault,
    all_findings: list[Finding],
    blocked_credentials: frozenset[str],
    block_all_credentials: bool,
) -> str:
    findings = detect_sensitive(text)
    blocked = [
        item
        for item in findings
        if item.entity_type == EntityType.API_KEY
        and (
            block_all_credentials
            or item.value in blocked_credentials
            or _credential_value(item.value) in blocked_credentials
        )
    ]
    if blocked:
        raise SensitiveCredentialError(blocked)
    normalized = [
        Finding(
            entity_type=(
                EntityType.CREDENTIAL
                if item.entity_type == EntityType.API_KEY
                else item.entity_type
            ),
            start=item.start,
            end=item.end,
            value=item.value,
            confidence=item.confidence,
        )
        for item in findings
    ]
    replaced = text
    for finding in reversed(normalized):
        placeholder = vault.get_or_create(finding.entity_type, finding.value)
        replaced = (
            replaced[: finding.start] + placeholder + replaced[finding.end :]
        )
    all_findings.extend(normalized)
    return replaced


def _credential_value(value: str) -> str:
    scheme, separator, credential = value.partition(" ")
    if separator and scheme.lower() == "bearer":
        return credential
    return value


def _walk_sanitize(
    value: Any,
    vault: RequestVault,
    findings: list[Finding],
    blocked_credentials: frozenset[str],
    block_all_credentials: bool,
) -> Any:
    if isinstance(value, str):
        return _sanitize_text(
            value,
            vault,
            findings,
            blocked_credentials,
            block_all_credentials,
        )
    if isinstance(value, list):
        return [
            _walk_sanitize(
                item,
                vault,
                findings,
                blocked_credentials,
                block_all_credentials,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _walk_sanitize(
                item,
                vault,
                findings,
                blocked_credentials,
                block_all_credentials,
            )
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


def sanitize_payload(
    payload: dict[str, Any],
    blocked_credentials: set[str] | frozenset[str] | None = None,
) -> SanitizedPayload:
    started = time.perf_counter()
    vault = RequestVault()
    findings: list[Finding] = []
    block_all_credentials = blocked_credentials is None
    blocked = frozenset(blocked_credentials or ())
    safe_payload = _walk_sanitize(
        copy.deepcopy(payload),
        vault,
        findings,
        blocked,
        block_all_credentials,
    )
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
