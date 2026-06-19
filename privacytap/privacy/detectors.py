import re
from collections.abc import Iterable

from privacytap.privacy.models import EntityType, Finding
from privacytap.privacy.validators import is_valid_cn_id, is_valid_luhn


PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
CN_ID_RE = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9._%+-])"
)
BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
STUDENT_ID_RE = re.compile(
    r"(?i)(?:学号|student\s*(?:id|no\.?))\s*[:：]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9_-]{5,19})"
)
API_KEY_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
)
PRIORITY = {
    EntityType.API_KEY: 100,
    EntityType.CN_ID: 90,
    EntityType.BANK_CARD: 80,
    EntityType.EMAIL: 70,
    EntityType.PHONE: 60,
    EntityType.STUDENT_ID: 50,
}


def _finding(
    match: re.Match[str], entity_type: EntityType, group: int = 0
) -> Finding:
    start, end = match.span(group)
    return Finding(
        entity_type=entity_type,
        start=start,
        end=end,
        value=match.group(group),
    )


def _candidates(text: str) -> Iterable[Finding]:
    for pattern in API_KEY_PATTERNS:
        for match in pattern.finditer(text):
            yield _finding(match, EntityType.API_KEY)
    for match in CN_ID_RE.finditer(text):
        if is_valid_cn_id(match.group()):
            yield _finding(match, EntityType.CN_ID)
    for match in BANK_CARD_RE.finditer(text):
        if is_valid_luhn(match.group()):
            yield _finding(match, EntityType.BANK_CARD)
    for match in EMAIL_RE.finditer(text):
        yield _finding(match, EntityType.EMAIL)
    for match in PHONE_RE.finditer(text):
        yield _finding(match, EntityType.PHONE)
    for match in STUDENT_ID_RE.finditer(text):
        yield _finding(match, EntityType.STUDENT_ID, group=1)


def _overlaps(left: Finding, right: Finding) -> bool:
    return left.start < right.end and right.start < left.end


def resolve_overlaps(findings: Iterable[Finding]) -> list[Finding]:
    selected: list[Finding] = []
    ordered = sorted(
        findings,
        key=lambda item: (
            -PRIORITY[item.entity_type],
            -(item.end - item.start),
            item.start,
        ),
    )
    for candidate in ordered:
        if not any(_overlaps(candidate, existing) for existing in selected):
            selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def detect_sensitive(text: str) -> list[Finding]:
    if not text:
        return []
    return resolve_overlaps(_candidates(text))
