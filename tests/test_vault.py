from tokentap.privacy.models import EntityType
from tokentap.privacy.vault import RequestVault


def test_same_value_gets_same_placeholder():
    vault = RequestVault()
    first = vault.get_or_create(EntityType.PHONE, "13812345678")
    second = vault.get_or_create(EntityType.PHONE, "13812345678")
    assert first == second == "[PHONE_1]"


def test_entity_counters_are_independent():
    vault = RequestVault()
    assert vault.get_or_create(EntityType.PHONE, "13812345678") == "[PHONE_1]"
    assert vault.get_or_create(EntityType.EMAIL, "a@example.com") == "[EMAIL_1]"
    assert vault.get_or_create(EntityType.PHONE, "13912345678") == "[PHONE_2]"


def test_restore_replaces_longer_placeholders_safely():
    vault = RequestVault()
    for index in range(10):
        vault.get_or_create(EntityType.PHONE, f"1381234567{index}")
    assert vault.restore_text("联系 [PHONE_10]") == "联系 13812345679"


def test_two_vaults_are_isolated():
    first = RequestVault()
    second = RequestVault()
    first.get_or_create(EntityType.EMAIL, "first@example.com")
    second.get_or_create(EntityType.EMAIL, "second@example.com")
    assert first.restore_text("[EMAIL_1]") == "first@example.com"
    assert second.restore_text("[EMAIL_1]") == "second@example.com"
