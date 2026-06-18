import pytest

from tokentap.privacy.detectors import detect_sensitive
from tokentap.privacy.models import EntityType


@pytest.mark.parametrize(
    ("text", "entity", "value"),
    [
        ("联系电话 13812345678", EntityType.PHONE, "13812345678"),
        ("身份证 11010519491231002X", EntityType.CN_ID, "11010519491231002X"),
        ("邮箱 alice@example.com", EntityType.EMAIL, "alice@example.com"),
        ("银行卡 4532 0151 1283 0366", EntityType.BANK_CARD, "4532 0151 1283 0366"),
        ("学号：2023123456", EntityType.STUDENT_ID, "2023123456"),
        ("Student ID: S20240001", EntityType.STUDENT_ID, "S20240001"),
        (
            "密钥 sk-proj-abcdefghijklmnopqrstuv",
            EntityType.API_KEY,
            "sk-proj-abcdefghijklmnopqrstuv",
        ),
        (
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
            EntityType.API_KEY,
            "Bearer abcdefghijklmnopqrstuvwxyz123456",
        ),
    ],
)
def test_detects_supported_entity(text, entity, value):
    findings = detect_sensitive(text)
    assert any(item.entity_type == entity and item.value == value for item in findings)


@pytest.mark.parametrize(
    "text",
    [
        "版本号 2023123456 不应在没有学号上下文时被识别",
        "电话号码 12345678901 不符合大陆手机号规则",
        "银行卡候选 4532015112830367 未通过 Luhn",
        "普通短 token abcdefghijklmnop 不应被阻断",
        "身份证 110105194912310021 校验位错误",
    ],
)
def test_rejects_false_positives(text):
    assert detect_sensitive(text) == []


def test_id_card_wins_over_bank_card_overlap():
    findings = detect_sensitive("11010519491231002X")
    assert [item.entity_type for item in findings] == [EntityType.CN_ID]


def test_findings_are_ordered_by_text_position():
    findings = detect_sensitive("alice@example.com 和 13812345678")
    assert [item.entity_type for item in findings] == [
        EntityType.EMAIL,
        EntityType.PHONE,
    ]
